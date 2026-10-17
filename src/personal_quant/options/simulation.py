"""Import archived mature-engine fills into an isolated demo plan, atomically."""
import hashlib
import json
from datetime import timedelta
from pathlib import Path
from ..common import QuantError,canonical,decimal as D,digest,now_utc,utc
from ..locks import publication_lock
from ..data.calendar import Calendar
from .contracts import OptionContract
from .data import quality
from .lifecycle import review
from .monthly_report import load_monthly_report
from .qualification import assess_engine,ENGINE_TEMPLATES
from .engine import LEAN_COMMIT

FIELDS={'plan_id','report_id','execution_snapshot_id','as_of','expected_sequence'}


def execute(book,store,request):
    if not isinstance(request,dict) or set(request) not in (FIELDS,FIELDS|{'hedge_stage_check'},FIELDS|{'state_as_of'},FIELDS|{'hedge_stage_check','state_as_of'}) or type(request['expected_sequence']) is not int or request['expected_sequence']<0:
        raise QuantError('INVALID_OPTION_SIMULATION','模拟任务需计划、归档报告、收盘报价、处理时点及账户序号')
    name=request['report_id']
    if not isinstance(name,str) or not name or name in {'.','..'} or Path(name).name!=name or '/' in name or '\\' in name:
        raise QuantError('INVALID_OPTION_SIMULATION','报告ID必须是工作区内单一目录名')
    clock=utc(request['as_of'])
    if clock>utc(now_utc()):raise QuantError('INVALID_OPTION_SIMULATION','不能在未来处理模拟成交')
    identity='option-simulation:'+digest({'plan_id':request['plan_id']})
    with publication_lock(book.path.parent),book.transaction():
        existing=book.connection.execute('SELECT details FROM tasks WHERE task_id=?',(identity,)).fetchone()
        if existing:
            audit=json.loads(existing[0])
            if audit['request_hash']!=digest(request):raise QuantError('EVENT_CONFLICT','同计划模拟批次已经处理，不能换输入重复成交')
            from ..hedging.stage_gate import validate_cached
            validate_cached(book,audit,'OPEN')
            return audit
        if book.environment!='demo':raise QuantError('FIXTURE_ONLY','此任务只处理隔离demo合成引擎成交')
        row=book.connection.execute('SELECT payload FROM option_plans WHERE plan_id=?',(request['plan_id'],)).fetchone()
        if not row:raise QuantError('UNKNOWN_OPTION_PLAN','模拟计划不存在')
        saved=json.loads(row[0]);activation=saved.get('activation')
        close=utc(activation['valid_until']) if activation else None;state_as_of=request.get('state_as_of')
        if state_as_of is not None and (close is None or utc(state_as_of)!=close):
            raise QuantError('INVALID_SIMULATION_STATE_TIME','期权OPEN迟到只允许原冻结收盘')
        if close is not None and clock>close+timedelta(days=1) and request.get('hedge_stage_check') and state_as_of is None:
            raise QuantError('HEDGE_REPLAY_STATE_REQUIRED','迟到期权阶段须显式冻结成交状态，不能套用处理日风险')
        from ..hedging.monitor import require_planning
        from ..hedging.stage_gate import require_for_plan
        stage_check=require_for_plan(book,saved['account_id'],'option',request['plan_id'],'OPEN',request['as_of'],request.get('hedge_stage_check'),state_as_of=state_as_of)
        if state_as_of is not None and stage_check.get('status')!='CHECKED':raise QuantError('UNBOUND_HEDGE_EXECUTION','显式期权重放时钟须已绑定执行组')
        if close is not None and clock>close+timedelta(days=1) and stage_check.get('status')=='CHECKED' and state_as_of is None:
            raise QuantError('HEDGE_REPLAY_STATE_REQUIRED','迟到期权阶段须显式冻结成交状态，不能套用处理日风险')
        require_planning(book,saved['account_id'],request['as_of'],stage_check=stage_check)
        if not activation:raise QuantError('OPTION_PLAN_NOT_READY','模拟前需显式激活计划')
        if clock<close:raise QuantError('EXECUTION_NOT_AVAILABLE','尚未到达计划收盘成交时点')
        body=review(book,request['plan_id'],close)
        if book.sequence(body['account_id'])!=request['expected_sequence']:raise QuantError('STALE_PREVIEW','模拟前账户序号已变化')
        if not body['executable'] or body['selection']['template_id'] not in ENGINE_TEMPLATES:
            raise QuantError('OPTION_PLAN_NOT_READY','计划检查失败或有在途订单，不能模拟成交')
        current=review(book,request['plan_id'],clock)
        if current.get('manual_execution',{}).get('pending'):
            raise QuantError('PENDING_MANUAL_ORDER','处理时仍有人工在途订单，不能重复模拟成交')
        activation_audits=[json.loads(r[0]) for r in book.connection.execute("SELECT details FROM tasks WHERE task_id LIKE 'option-activation:%'")]
        activated=[a for a in activation_audits if a['status']=='ACTIVATED' and a['request']['plan_id']==body['plan_id']]
        if len(activated)!=1:raise QuantError('CORRUPT_OPTION_AUDIT','计划缺少唯一激活审计')
        book.check_reconciliation(body['account_id'],clock,int(D(activated[0]['request']['reconciliation_max_days'])))
        if any('未核实期权凭据' in issue for issue in current['progress']['fact_anomalies']):
            raise QuantError('UNRESOLVED_RECONCILIATION','处理时存在未核实期权凭据')
        if any(e['seq']>activation['basis_sequence'] and e['plan_id']!=body['plan_id'] for e in book.active_events(body['account_id'],clock)):
            raise QuantError('STALE_PREVIEW','处理前账户发生未关联变化')
        qualification=assess_engine(book.path.parent/'options/engine-evidence'/activation['engine_evidence_id']/'verification.json',body['selection']['template_id'])
        if qualification['status']!='PASSED':raise QuantError('ENGINE_LIFECYCLE_UNQUALIFIED','激活后引擎资格发生变化')
        directory=book.path.parent/'options/monthly-research'/name
        report=load_monthly_report(directory)
        if report['data_type']!='synthetic_monthly_mechanical':raise QuantError('FIXTURE_ONLY','仅合成月度报告可用于工程模拟')
        member=body['selection']['template_id'];engine=directory/member
        proof=json.loads((engine/'verification.json').read_text());input_body=json.loads((engine/'input.json').read_text())
        from .adapter_resources import source_hashes
        sources=source_hashes()
        if sources!=proof['adapter_source'] or digest(input_body)!=proof['input_hash'] or proof['engine_commit']!=LEAN_COMMIT or hashlib.sha256((engine/'bin/LyraX.Options.dll').read_bytes()).hexdigest()!=proof['adapter_dll_sha256']:
            raise QuantError('ENGINE_SOURCE_CHANGED','模拟成交输入/引擎源码与当前验证版本不一致')
        signals=json.loads((engine/'signals.json').read_text())
        matches=[s for s in signals if s['monthly_signal_id']==activation['monthly_signal_id'] and s['selection']['decision_hash']==body['selection']['decision_hash']]
        if len(matches)!=1:raise QuantError('MONTHLY_SIGNAL_MISMATCH','引擎报告未使用计划冻结的月度信号')
        tag=activation['monthly_signal_id']+'|OPEN'
        events=[e for e in json.loads((engine/'engine-events.json').read_text()) if e['tag']==tag]
        underlying_events=[e for e in events if e['right'] is None]
        events=[e for e in events if e['right'] is not None]
        # Research starts with cash and constructs stock cover. The account plan
        # already owns its required stock; never buy those shares a second time.
        needs_stock=body['selection']['template_id'] in {'covered_call','protective_put','collar'}
        if len(underlying_events)!=(1 if needs_stock else 0):raise QuantError('INVALID_ENGINE_FILL','研究持股构造与模板不符')
        for e in underlying_events:
            if utc(e['utc_time'])!=close or e['symbol']!=body['selection']['underlying'] or e['order_type']!='MarketOnClose' or D(e['quantity'])!=100 or D(e['price'])!=100:
                raise QuantError('INVALID_ENGINE_FILL','研究持股入口不是已验证的标准单份构造')
            if D(body['account_basis']['positions'].get(e['symbol'],0))<D(e['quantity']):raise QuantError('INSUFFICIENT_UNDERLYING','账户没有研究模板所需的原有股票')
        contracts,quotes,metadata,_=store.load(request['execution_snapshot_id'])
        if metadata['data_type']!='synthetic':raise QuantError('FIXTURE_ONLY','收盘报价必须明确为合成工程数据')
        selected={leg['contract']['contract_id']:OptionContract.from_dict(leg['contract']) for leg in body['selection']['legs']}
        lines={line['contract_id']:line for line in body['sizing']['lines']};quantities={};rows=[];marks={}
        calendar=Calendar.market(str(close.date()),str(close.date()+timedelta(days=40)))
        parameters=body['request']['selection']['parameters'];risk=body['request']['risk']
        for e in events:
            candidates=[c for c in selected.values() if c.right==e['right'] and c.expiry==e['expiry'] and c.strike==D(e['strike'])]
            if len(candidates)!=1 or utc(e['utc_time'])!=close or e['order_type']!='MarketOnClose' or e['fee_currency']!='USD':
                raise QuantError('INVALID_ENGINE_FILL','引擎成交单位、时点或订单类型不符')
            c=candidates[0];line=lines[c.contract_id];q=abs(D(e['quantity']))
            if q<=0 or q!=q.to_integral_value() or ('BUY' if D(e['quantity'])>0 else 'SELL')!=line['side']:
                raise QuantError('INVALID_ENGINE_FILL','引擎成交方向或张数不符')
            quantities[c.contract_id]=quantities.get(c.contract_id,D(0))+q
            if quantities[c.contract_id]>D(body['progress']['remaining_contracts'][c.contract_id]):
                raise QuantError('INVALID_ENGINE_FILL','不能按事后价格增加事前计划数量')
            candidates=[r for r in quotes if r['contract_id']==c.contract_id and utc(r['exchange_timestamp'])==close and utc(r['available_at'])<=clock and utc(r['received_at'])<=clock]
            if len(candidates)!=1 or c.contract_id not in contracts or contracts[c.contract_id].version_hash!=c.version_hash:
                raise QuantError('MISSING_EXECUTION_QUOTE','缺少已到达、确切单位的收盘报价')
            quote=candidates[0]
            issues=quality(quote,c,close,knowledge_cutoff=clock,max_age_seconds=float(parameters['max_age_seconds']),max_underlying_skew_seconds=float(parameters['max_underlying_skew_seconds']),max_spread_fraction=parameters['max_spread_fraction'])
            fill=D(e['price']);fee=D(e['fee']);reference=D(line['reference_ask'] if line['side']=='BUY' else line['reference_bid'])
            size=D(quote['ask_size'] if line['side']=='BUY' else quote['bid_size'])
            if issues or D(quote['underlying_price'])!=100 or q>size or fill!=D(quote['ask'] if line['side']=='BUY' else quote['bid']) or fee<0 or fee>q*D(risk['fee_per_contract']) or abs(fill/reference-1)>D(risk['adverse_slippage_fraction']):
                raise QuantError('INVALID_EXECUTION_QUOTE','报价/费用/偏离未通过冻结风险约定')
            marks[c.contract_id]=(D(quote['bid'])+D(quote['ask']))/2;marks[c.underlying]=quote['underlying_price']
            rows.append({'event_id':identity+':'+str(e['order_id'])+':'+str(e['event_id']),
                'kind':'OPTION_TRADE','contract_version':c.version_hash,'quantity':str(q),'price':str(fill),'fee':str(fee),
                'action':'OPEN','trade_side':line['side'],'effective_at':close.isoformat(),
                'settlement_at':calendar.close(calendar.next(close.date())).isoformat(),
                'plan_id':body['plan_id'],'source':'synthetic_monthly_lean','evidence_type':'test'})
        if not rows:raise QuantError('INVALID_ENGINE_FILL','归档没有对应计划的实际成交')
        imported=book.import_events(body['account_id'],rows,expected_sequence=request['expected_sequence'])
        state=book.snapshot(body['account_id'],clock,marks)
        if state['anomalies'] or state['equity'] is None or D(state['available_cash'])<0:
            raise QuantError('OPTION_SIMULATION_RESOURCE_FAILED','模拟批次资源/估值异常，全部回滚')
        result=review(book,body['plan_id'],clock)
        audit={'status':'SIMULATED','request':request,'request_hash':digest(request),'recorded_at':now_utc(),
            'hedge_stage_check':stage_check,'report_hash':digest(report),'execution_snapshot_id':request['execution_snapshot_id'],
            'engine_events_hash':digest(events),'rows':rows,'import':imported,'result':result,'account':state,
            'research_underlying_events_not_imported':underlying_events,
            'underlying_basis':'所需股票已在账户；研究从现金构造持股的事件及费用不重复入账',
            'data_type':'synthetic_historical_demonstration','delayed_processing':clock>close,
            'meaning':'成熟引擎历史演示成交，T+1工程结算；不提交券商订单或冒充真实成交'}
        book.record_task(identity,'SUCCESS',audit)
        return audit
