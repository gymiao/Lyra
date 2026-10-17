"""Freeze read-only account inputs before computing portfolio risk."""
import json
from ..common import QuantError,digest,utc,decimal as D,now_utc
from ..data.quotes import quote_set
from ..strategies.archive import source_fingerprint
from ..options.contracts import OptionContract
from ..options.exit_tasks import resource_basis
from .exposure import estimate_betas,normalize_delta,aggregate_exposure

FIELDS={'schema_version','as_of','knowledge_cutoff','ledger_seq','ledger_view','valuation_snapshot_id',
        'return_snapshot_id','benchmark','window','min_r2','max_standard_error','max_mark_skew_seconds',
        'max_greek_age_seconds','greeks','option_valuation'}


def exposure(book,config,store,account_id,request):
    if (not isinstance(request,dict) or set(request) not in (FIELDS,FIELDS|{'proxy_symbols'},FIELDS|{'execution_replay'},FIELDS|{'proxy_symbols','execution_replay'}) or request['schema_version']!=1
            or request['ledger_view'] not in {'known_then','restated'}
            or type(request['ledger_seq']) is not int or request['ledger_seq']<0
            or not isinstance(request['benchmark'],str) or not request['benchmark']
            or not isinstance(request['greeks'],list) or D(request['max_mark_skew_seconds'])<0
            or D(request['max_greek_age_seconds'])<0):
        raise QuantError('INVALID_EXPOSURE_REQUEST','风险请求需完整版本、时点/账户依据、数据/基准和模型阈值')
    if book.environment!=config.environment:raise QuantError('ENVIRONMENT_MISMATCH','风险配置与账户环境不同')
    clock,known=utc(request['as_of']),utc(request['knowledge_cutoff'])
    replay_session=None
    if 'execution_replay' in request:
        from .execution_replay import validate
        replay_session=validate(book,account_id,request['execution_replay'],clock,known)
        if known>utc(now_utc()):raise QuantError('FUTURE_EXPOSURE','处理知识截止不能在未来')
    elif known>clock:raise QuantError('INVALID_EXPOSURE_TIME','知识截止不能晚于风险时点')
    if clock>utc(now_utc()):raise QuantError('FUTURE_EXPOSURE','不能把未来风险时点当成已知账户快照')
    if request['ledger_view']=='restated' and book.environment!='demo':
        raise QuantError('RESTATED_DEMO_ONLY','当前重述风险入口只用于明确标记的demo工程研究')
    checks=[]
    proxies=request.get('proxy_symbols',[])
    if not isinstance(proxies,list) or any(not isinstance(s,str) or not s for s in proxies) or len(set(proxies))!=len(proxies):
        raise QuantError('INVALID_EXPOSURE_REQUEST','候选代理必须显式列出不重复证券代码')
    with book.transaction():
        book._require_account(account_id)
        if request['ledger_seq']>book.sequence(account_id):raise QuantError('INVALID_LEDGER_SEQUENCE','请求账户序号尚不存在')
        if request['ledger_view']=='known_then' and any(utc(row[0])>known for row in book.connection.execute(
                'SELECT recorded_at FROM events WHERE account_id=? AND seq<=?',
                (account_id,request['ledger_seq']))):
            raise QuantError('LEDGER_NOT_KNOWN','指定账户前缀包含当时尚未收到的凭据，不改写当时所知风险')
        sequence=request['ledger_seq'];state=book.snapshot(account_id,clock,ledger_seq=sequence)
        ledger_basis_hash=digest([dict(row) for row in book.connection.execute(
            'SELECT seq,event_id,content_hash,effective_at,recorded_at,payload FROM events WHERE account_id=? AND seq<=? ORDER BY seq',
            (account_id,sequence))])
        terms={}
        for row in book.active_events(account_id,clock,ledger_seq=sequence):
            if row['kind'].startswith('OPTION_'):terms[row['symbol']]=OptionContract.from_dict(row['contract'])
        resources=resource_basis(book,account_id) if book.connection.execute('SELECT version FROM schema_version').fetchone()[0]>=5 else None
        raw,metadata,calendar=store.load(request['valuation_snapshot_id'])
        history,history_meta,historical_calendar=store.load(request['return_snapshot_id'])
        if replay_session is not None and any(c.close(replay_session).to_pydatetime()!=clock for c in (calendar,historical_calendar)):
            raise QuantError('HEDGE_REPLAY_CALENDAR_MISMATCH','迟到行情/收益日历收盘须等于原计划冻结成交时点')
        if calendar.hash!=historical_calendar.hash:checks.append('RISK_CALENDAR_CONFLICT')
        if book.environment!='demo' and (metadata['data_type']=='synthetic' or history_meta['data_type']=='synthetic'):
            raise QuantError('ENVIRONMENT_MISMATCH','实际账户风险不使用合成行情')
        qualification=None
        if metadata['data_type']=='real_market' and book.environment!='demo':
            from ..data.qualification import require_qualification
            series=store.series_identity(metadata)
            qualification=require_qualification(book.connection,book.path.parent,metadata,series,known,knowledge_cutoff=known)
            record=book.connection.execute('SELECT created_at FROM source_qualifications WHERE qualification_id=?',
                (qualification['qualification_id'],)).fetchone()
            if utc(record[0])>known:raise QuantError('SOURCE_NOT_KNOWN','不能倒用后来登记的原价资格')
        symbols=set(state['positions'])|{terms[s].underlying for s in state.get('option_positions',{})}
        model_symbols=symbols|set(proxies)
        marks=quote_set(raw,calendar,config,known,model_symbols,frozen_session=replay_session)
        prices=dict(marks['prices']);option_marks=None
        if state.get('option_positions') and request['option_valuation'] is not None:
            from ..options.data import OptionDataStore
            from ..options.valuation import quote_set as option_quotes
            item=request['option_valuation']
            if not isinstance(item,dict) or set(item)!={'snapshot_id','limits'}:
                raise QuantError('INVALID_OPTION_VALUATION','期权估值需snapshot_id和limits')
            option_marks=option_quotes(book,account_id,OptionDataStore(book.path.parent/'options/chains'),item['snapshot_id'],clock if replay_session else known,item['limits'],ledger_seq=sequence,knowledge_cutoff=known)
            prices.update(option_marks['prices'])
        state=book.snapshot(account_id,clock,prices,ledger_seq=sequence)
    betas=estimate_betas(history,historical_calendar,model_symbols,request['benchmark'],clock,known,
        window=request['window'],min_r2=request['min_r2'],max_standard_error=request['max_standard_error'],execution_replay=replay_session is not None)
    deltas={};provided={};greek_qualifications={}
    for item in request['greeks']:
        if not isinstance(item,dict) or item.get('contract_version') in provided:
            raise QuantError('INVALID_HEDGE_GREEK','重复或畸形合约Greek')
        provided[item.get('contract_version')]=item
    for symbol,quantity in state.get('option_positions',{}).items():
        c=terms[symbol];item=provided.get(c.version_hash)
        if not item:continue
        if book.environment!='demo' and item.get('data_type')=='synthetic':
            raise QuantError('ENVIRONMENT_MISMATCH','实际账户风险不能使用合成Greek')
        try:
            session=marks['quotes'].get(c.underlying,{}).get('session')
            mark=calendar.close(session).isoformat() if session is not None else None
            normalized=normalize_delta(item,c,quantity,clock,known,request['max_greek_age_seconds'])
            if item.get('data_type')=='model':
                from .model_greek import require_mark
                require_mark(item,marks['prices'].get(c.underlying),require_complete=book.environment!='demo')
            if book.environment!='demo':
                from .greek_evidence import assess as assess_greek
                greek_qualifications[symbol]=assess_greek(book,item,c,known)
            if mark is None or abs((utc(item['as_of'])-utc(mark)).total_seconds())>float(request['max_mark_skew_seconds']):
                raise QuantError('HEDGE_GREEK_TIME_MISMATCH','标的与Greek时点未对齐')
            deltas[symbol]={**normalized,'underlying':c.underlying}
        except QuantError as exc:checks.append(exc.code+':'+symbol)
    risk=aggregate_exposure(state,betas['estimates'],deltas,marks['prices'])
    if marks['status'] not in {'COMPLETE','CASH_ONLY'}:checks.append('INCOMPLETE_RAW_MARKS')
    checks.extend(betas['checks']);checks.extend(risk['checks'])
    result={'schema_version':1,'artifact_type':'hedge_exposure','account_id':account_id,'environment':book.environment,
        'as_of':clock.isoformat(),'knowledge_cutoff':known.isoformat(),'purpose':'frozen_execution_replay' if replay_session else 'current_risk','ledger_seq':sequence,'ledger_view':request['ledger_view'],
        'ledger_basis_hash':ledger_basis_hash,
        'status':'INCOMPLETE' if checks else 'COMPLETE','checks':sorted(set(checks)),
        'request':request,'account':state,'risk':risk,'beta_model':betas,'valuation':marks,'option_valuation':option_marks,
        'valuation_snapshot_id':metadata['snapshot_id'],'return_snapshot_id':history_meta['snapshot_id'],
        'data_types':sorted({metadata['data_type'],history_meta['data_type']}),'resource_basis':resources,
        'source_qualification':qualification,'source_fingerprint':source_fingerprint(),
        'greek_qualification':greek_qualifications if book.environment!='demo' else {},
        'executable':False,'meaning':'只读账户风险；重述或历史风险估计不等同于当时已知策略表现，不生成交易计划'}
    result['exposure_id']=digest(result);return result
