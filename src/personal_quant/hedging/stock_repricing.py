"""Explicit immutable repricing of remaining hedge stock quantities."""
import json
from datetime import timedelta
from copy import deepcopy
from zoneinfo import ZoneInfo

from ..common import QuantError,canonical,digest,decimal as D,now_utc,utc
from ..config import Config
from ..data.calendar import Calendar
from ..data.store import DataStore
from ..data.quality import price_quality,require_quality
from ..locks import publication_lock
from .allocation_store import resources
from .archive import load
from .groups import history,_plan
from .group_revisions import heads
from .stock_plans import FROZEN

PREFIX='hedge-stock-reprice:'
UNIT_PREFIX='hedge-stock-unit-rebase:'
FIELDS={'schema_version','request_id','plan_id','group_id','expected_group_hash',
        'expected_resource_hash','exposure_id','as_of','execution_session','reason'}


def _request(request,unit_mode=False):
    fields=FIELDS|{'unit_actions'} if unit_mode else FIELDS
    if (not isinstance(request,dict) or set(request)!=fields or type(request['schema_version']) is not int
            or request['schema_version']!=1 or any(not isinstance(request[k],str) or not request[k].strip()
            for k in FIELDS-{'schema_version'})):
        raise QuantError('INVALID_HEDGE_STOCK_REPRICE','修订须原计划/组/资源、当前风险、显式交易日及原因')
    if unit_mode and (not isinstance(request['unit_actions'],list) or not request['unit_actions']
            or any(not isinstance(a,dict) or set(a)!={'event_id','seq','content_hash'}
                   or not isinstance(a['event_id'],str) or not a['event_id'] or type(a['seq']) is not int
                   or a['seq']<=0 or not isinstance(a['content_hash'],str) or len(a['content_hash'])!=64
                   for a in request['unit_actions'])):
        raise QuantError('INVALID_STOCK_UNIT_ACTIONS','单位重规划须明确已入账拆股事件、序号及内容哈希')


def _forward_basis(environment,old,group,parent,metadata,clock):
    if environment=='demo':return
    times=(old['created_at'],group['recorded_at'],parent['generated_at'],metadata['acquired_at'])
    if any(utc(t)>clock for t in times):
        raise QuantError('LOOKAHEAD_REPRICE','前向报价修订不得早于实际计划、组、父意图或行情采集时间')


def _rebuild(book,config,account_id,request,*,unit_mode=False):
    """Independent frozen-prefix calculation, shared by writes and archive reads."""
    from .intents import records
    row,old,_=_plan(book,account_id,'stock',request['plan_id'])
    if old.get('purpose')!='hedge_stage':raise QuantError('NON_HEDGE_STOCK_PLAN','只能修订独立股票对冲用途')
    group=next((g for g in history(book,account_id) if g['group_id']==request['group_id']),None)
    if group is None or group['record_hash']!=request['expected_group_hash']:
        raise QuantError('STALE_HEDGE_GROUP','须确切原组版本')
    stages=[s for s in group['stages'] if s['plan_kind']=='stock' and s['plan_id']==request['plan_id'] and not s.get('historical_slice')]
    if len(stages)!=1:raise QuantError('UNBOUND_HEDGE_STOCK_PLAN','原股票计划须唯一非历史执行阶段')
    stage=stages[0];context=old['hedge_context'];action=context.get('action','OPEN')
    if stage['action']!=action:raise QuantError('HEDGE_STOCK_STAGE_DIRECTION','原操作方向与执行组不同')
    parent=next(p for p in records(book,account_id) if p['version_hash']==group['parent_version'])
    if context['parent_version']!=parent['version_hash']:raise QuantError('HEDGE_PARENT_MISMATCH','不能借用其他父数量')
    risk=load(book.path.parent/'hedging/exposures',request['exposure_id']);clock=utc(request['as_of'])
    if (risk['account_id']!=account_id or risk['environment']!=book.environment
            or utc(risk['as_of'])!=clock or utc(risk['knowledge_cutoff'])!=clock
            or risk['purpose']!='current_risk'):
        raise QuantError('INVALID_REPRICE_EXPOSURE','新修订须同账户、同当前决策时点的完整风险，不用迟到重放风险')
    from .stage_assessment import require_operation_risk
    require_operation_risk(risk,action)
    if config.hash!=old['execution_config_hash'] or config.environment!=book.environment:
        raise QuantError('HEDGE_EXECUTION_CONFIG_CHANGED','报价修订保留原执行/风险配置，配置变化须另行明确决策')
    prefix=risk['ledger_seq']
    basis=digest([dict(r) for r in book.connection.execute(
        'SELECT seq,event_id,content_hash,effective_at,recorded_at,payload FROM events WHERE account_id=? AND seq<=? ORDER BY seq',(account_id,prefix))])
    if basis!=risk['ledger_basis_hash']:raise QuantError('CORRUPT_EXPOSURE_ARCHIVE','修订原财务前缀改变')
    financial=book.snapshot(account_id,clock,risk['account']['prices'],ledger_seq=prefix)
    for key in ('settled_cash','receivables','payables','positions','option_positions','equity','net_contributions'):
        neutral={} if key=='option_positions' else None
        if financial.get(key,neutral)!=risk['account'].get(key,neutral):raise QuantError('CORRUPT_REPRICE_ACCOUNT','修订风险财务依据改变')
    events=book.active_events(account_id,clock,ledger_seq=prefix)
    allowed={s['plan_id'] for s in group['stages']}
    internal={'FEE','DIVIDEND_ACCRUAL','DIVIDEND_PAYMENT'}
    if unit_mode:
        if any(s['plan_kind']!='stock' for s in group['stages']) or risk['account'].get('option_positions'):
            raise QuantError('OPTION_UNIT_REQUALIFICATION_REQUIRED','股票拆股重规划只支持纯股票组，不能缩放期权合约或交割单位')
        affected={l['symbol'] for l in stage['lines']}
        if any(e['kind']=='SPLIT' and e['seq']>old['snapshot']['ledger_seq'] and e['symbol'] not in affected for e in events):
            raise QuantError('UNRELATED_UNIT_ACTION','本草案不能授权其他证券拆股')
        if any(json.loads(r['payload'])['kind']=='REVERSAL' for r in book.connection.execute(
                'SELECT payload FROM events WHERE account_id=? AND seq>? AND seq<=?',(account_id,old['snapshot']['ledger_seq'],prefix))):
            raise QuantError('UNIT_FACT_CORRECTION_REQUIRES_REVIEW','拆股或成交冲销后须重新核实，不能沿用原单位请求')
        internal.add('SPLIT')
    if any(e['seq']>old['snapshot']['ledger_seq'] and e['kind'] not in internal
            and (e['plan_id'] not in allowed or e['kind'] not in {'BUY','SELL','OPTION_TRADE'}) for e in events):
        raise QuantError('ACCOUNT_CHANGED','可沿用组内成交、分红/费用；外部资金、计划外交易或单位变化须重新决策')
    from .stock_units import stage_quantities
    units=stage_quantities(events,request['plan_id'],stage['lines'],old['as_of'],clock,
        origin_seq=old['snapshot']['ledger_seq'])
    if unit_mode and units['actions']!=request['unit_actions']:
        raise QuantError('STOCK_UNIT_ACTION_MISMATCH','明确行动必须与原数量到本次风险时点的全部实际拆股一致')
    if not unit_mode and units['actions']:
        raise QuantError('ACCOUNT_CHANGED','报价修订不授权单位变化；须明确股票单位重规划')
    quantities=units['remaining']
    if not quantities:raise QuantError('HEDGE_STAGE_ALREADY_FILLED','已完成方向不能因报价变化重新开启')
    if clock<utc(old['as_of']) or clock>utc(now_utc()):raise QuantError('INVALID_REPRICE_TIME','修订不能倒退决定时点或使用未来时点')
    if action=='OPEN' and not utc(parent['decision_at'])<=clock<=utc(parent['valid_until']):
        raise QuantError('HEDGE_INTENT_EXPIRED','新增剩余数量须仍在原父窗口')
    store=DataStore(book.path.parent/'data');frame,metadata,calendar=store.load(risk['valuation_snapshot_id'])
    _forward_basis(book.environment,old,group,parent,metadata,clock)
    reference=calendar.latest_completed(request['as_of'],config.publication_delay_minutes)
    symbols={s for s,_ in quantities}
    require_quality(price_quality(frame,calendar,config,symbols,reference,request['as_of'],require_previous=True))
    rows=frame.loc[(frame.session_date==reference)&frame.symbol.isin(symbols)]
    if set(rows.price_basis)!={'unadjusted'} or (not unit_mode and (rows.split_ratio!=1).any()):
        raise QuantError('UNQUALIFIED_EXECUTION_PRICE','修订须实际原价且单位一致，单位行动不得隐式改数量')
    if unit_mode:
        from pandas import Timestamp
        action_ids={a['event_id'] for a in units['actions']}
        for symbol in symbols:
            facts=[e for e in events if e['kind']=='SPLIT' and e['symbol']==symbol and e['event_id'] in action_ids]
            days={utc(e['effective_at']).astimezone(ZoneInfo('America/New_York')).date() for e in facts}
            # Also reject provider actions absent from the explicit ledger basis.
            start_day=utc(old['as_of']).astimezone(ZoneInfo('America/New_York')).date()
            period=frame.loc[(frame.symbol==symbol)&(frame.session_date>Timestamp(start_day))&(frame.session_date<=reference)]
            source_days=set(period.loc[period.split_ratio!=1,'session_date'].dt.date)
            if source_days!=days:raise QuantError('STOCK_UNIT_PRICE_ACTION_MISMATCH','行情与实际账本的全部行动日期必须一致')
            for day in days:
                ratio=D(1)
                for e in facts:
                    if utc(e['effective_at']).astimezone(ZoneInfo('America/New_York')).date()==day:ratio*=D(e['ratio'])
                supplied=frame.loc[(frame.symbol==symbol)&(frame.session_date.dt.date==day)]
                if len(supplied)!=1 or D(supplied.iloc[0].split_ratio)!=ratio:
                    raise QuantError('STOCK_UNIT_PRICE_ACTION_MISMATCH','执行原价的行动日期/比例须与实际账本拆股核对')
    if book.environment!='demo':
        from ..data.qualification import require_qualification
        require_qualification(book.connection,book.path.parent,metadata,store.series_identity(metadata),request['as_of'])
        if metadata['data_type']!='real_market' or parent['timing']!='forward':raise QuantError('FORWARD_HEDGE_REQUIRED','实际修订须真实合格来源和前向父意图')
    end=utc(parent['valid_until']).date() if action=='OPEN' else utc(old['execution_deadline']).date()+timedelta(days=max(60,config.execution_window_sessions*4))
    calendar_start=min(str(reference.date()),context.get('reprice_close_earliest_session',old['execution_session'])) if action=='CLOSE' else str(reference.date())
    execution_calendar=Calendar.market(calendar_start,str(end))
    if execution_calendar.close(reference)!=calendar.close(reference):raise QuantError('HEDGE_CALENDAR_MISMATCH','参考收盘须与XNYS相同')
    from pandas import Timestamp
    eligible=Timestamp(request['execution_session'])
    if str(eligible.date())!=request['execution_session'] or execution_calendar.close(eligible).to_pydatetime()<=clock:
        raise QuantError('INVALID_REPRICE_EXECUTION','新成交须明确有效未来交易日')
    if action=='OPEN':
        if eligible!=execution_calendar.next(reference) or execution_calendar.close(eligible).to_pydatetime()>utc(parent['valid_until']):
            raise QuantError('HEDGE_INTENT_EXPIRED','剩余OPEN仅在原窗口内下一交易日执行')
    else:
        start=context.get('reprice_close_earliest_session',old['execution_session'])
        cap=context.get('reprice_close_valid_through_session',str(execution_calendar.next(start,config.execution_window_sessions-1).date()))
        if not execution_calendar.close(start)<=execution_calendar.close(eligible)<=execution_calendar.close(cap):
            raise QuantError('HEDGE_CLOSE_WINDOW_EXPIRED','退出修订不反复延长原关闭窗口')
    prices=dict(zip(rows.symbol,rows.close));lines=[];reserve=D(0);fees=D(0)
    rate=(D(config.commission_bps)+D(config.slippage_bps))/10000
    for (symbol,side),q in sorted(quantities.items()):
        p=D(prices[symbol])
        if q%D(config.lot_size) or p!=D(risk['valuation']['prices'][symbol]):raise QuantError('HEDGE_PRICE_OR_UNIT_CHANGED','当前估值/参考原价或交易单位不同')
        fee=q*p*rate+D(config.fixed_fee);fees+=fee
        if side=='BUY':reserve+=q*p+fee
        lines.append(dict(symbol=symbol,side=side,quantity=str(q),price=str(p),estimated_fee=str(fee)))
    new_context=deepcopy(context);new_context.update(eligible_session=str(eligible.date()),reason=request['reason'],revision_of=request['plan_id'],reprice_exposure_id=request['exposure_id'])
    if unit_mode:new_context['unit_rebase']=dict(group_id=group['group_id'],as_of=clock.isoformat(),ledger_seq=prefix,actions=units['actions'])
    if action=='CLOSE':new_context.update(valid_through_session=cap,reprice_close_earliest_session=start,reprice_close_valid_through_session=cap)
    body=dict(purpose='hedge_stage',hedge_context=new_context,environment=book.environment,as_of=clock.isoformat(),
        execution_config=config.content(),execution_config_hash=config.hash,reference_session=str(reference.date()),
        reference_snapshot_id=metadata['snapshot_id'],execution_session=str(eligible.date()),execution_deadline=execution_calendar.close(eligible).isoformat(),
        execution_calendar_hash=execution_calendar.hash,snapshot=risk['account'],
        sizing=dict(lines=lines,reserve=str(reserve),estimated_fee=str(fees),projected_weights={},unallocated_buy_targets={}),
        checks=[dict(code='HEDGE_STAGE_ACTIVATION_REQUIRED',message='显式替换原组剩余引用并以当前阶段风险激活')],
        intent_status='BLOCKED',no_action=False,creates_reservations=False)
    body['draft_basis_hash']=digest({k:body[k] for k in FROZEN})
    return body,old,row,group,stage,risk


def save(book,config,account_id,request,*,commit=False,unit_mode=False):
    _request(request,unit_mode);
    prefix=UNIT_PREFIX if unit_mode else PREFIX;config.validate();config.require_execution()
    with publication_lock(book.path.parent),book.transaction():
        from .stock_plans import validate_references as validate_drafts
        validate_drafts(book)
        key=prefix+digest(dict(account_id=account_id,request_id=request['request_id']))
        previous=book.connection.execute('SELECT details FROM tasks WHERE task_id=?',(key,)).fetchone()
        if previous:
            audit=json.loads(previous[0])
            if audit['request_hash']!=digest(request):raise QuantError('HEDGE_STOCK_REQUEST_CONFLICT','同修订请求不可改变输入')
            return audit
        if resources(book,account_id)!=request['expected_resource_hash']:raise QuantError('STALE_HEDGE_RESOURCES','修订预检资源已变化')
        current=[g for g in heads(history(book,account_id)) if g['group_id']==request['group_id']]
        if len(current)!=1:raise QuantError('STALE_HEDGE_GROUP','只能修订当前组')
        body,old,row,group,stage,risk=_rebuild(book,config,account_id,request,unit_mode=unit_mode)
        if risk['ledger_seq']!=book.sequence(account_id) or book.snapshot(account_id,request['as_of'],risk['account']['prices'])!=risk['account']:
            raise QuantError('STALE_STAGE_ACCOUNT','修订风险之后财务或资源已变化')
        if row['execution_status'] not in {'CANCELLED','EXPIRED','SUPERSEDED'} or D(row['reserved_cash'])!=0 or json.loads(row['reserved_positions']) or row['manual_pending']:
            raise QuantError('NATIVE_PLAN_NOT_RELEASED','先确认人工订单结束并关闭原未执行部分，修订不自动撤单/释放')
        latest=book.connection.execute('SELECT max(revision) FROM plans WHERE account_id=? AND intent_id=?',(account_id,old['intent_id'])).fetchone()[0]
        if latest!=old['revision']:raise QuantError('HEDGE_STOCK_ALREADY_REVISED','原计划已有新修订，须处理现有草案')
        from .groups import progress
        view=progress(book,account_id,group,request['as_of'])
        unit_only=unit_mode and all(set(s['checks'])<={'STOCK_UNITS_CHANGED_REQUIRES_GROUP_REVISION'} for s in view['stages'])
        if (view['status']=='BLOCKED' and not unit_only) or any(s['manual_pending'] for s in view['stages']):raise QuantError('UNRESOLVED_HEDGE_EXECUTION','原组异常或人工在途未解决')
        if stage['action']=='OPEN':
            from .intent_actions import history as closures
            if any(c['hedge_id']==group['hedge_id'] for c in closures(book,account_id)):raise QuantError('HEDGE_INTENT_CLOSED','父已关闭，不能新建剩余OPEN')
        plan_id=digest(dict(account_id=account_id,draft_basis_hash=body['draft_basis_hash']))
        if not commit:return dict(status='PREVIEW',plan_id=plan_id,payload=body,creates_reservations=False,executable=False)
        body.update(plan_id=plan_id,intent_id=old['intent_id'],revision=old['revision']+1,created_at=now_utc())
        book.connection.execute('INSERT INTO plans VALUES(?,?,?,?,?,?,?,?,?,?)',(plan_id,body['intent_id'],body['revision'],account_id,'DRAFT','BLOCKED',canonical(body),'0','{}',0))
        audit=dict(schema_version=1,status='DRAFT',account_id=account_id,environment=book.environment,plan_id=plan_id,
            request=request,request_hash=digest(request),draft_basis_hash=body['draft_basis_hash'],
            source_frozen_hash=digest({k:old[k] for k in FROZEN}),created_at=body['created_at'],executable=False,creates_reservations=False)
        audit['record_hash']=digest(audit);book.record_task(key,'DRAFT',audit)
        validate_references(book)
        return audit


def validate_references(book):
    for r in book.connection.execute('SELECT task_id,details FROM tasks WHERE task_id LIKE ? OR task_id LIKE ? ORDER BY rowid',(PREFIX+'%',UNIT_PREFIX+'%')):
        try:
            audit=json.loads(r['details']);request=audit['request'];unit_mode=r['task_id'].startswith(UNIT_PREFIX);prefix=UNIT_PREFIX if unit_mode else PREFIX;_request(request,unit_mode)
            row,body,_=_plan(book,audit['account_id'],'stock',audit['plan_id'])
            config=Config.from_dict(body['execution_config']);rebuilt,old,_,_,_,_=_rebuild(book,config,audit['account_id'],request,unit_mode=unit_mode)
            if (audit['record_hash']!=digest({k:v for k,v in audit.items() if k!='record_hash'})
                    or audit['request_hash']!=digest(request) or audit['environment']!=book.environment or audit['status']!='DRAFT'
                    or r['task_id']!=prefix+digest(dict(account_id=audit['account_id'],request_id=request['request_id']))
                    or audit['source_frozen_hash']!=digest({k:old[k] for k in FROZEN})
                    or body['revision']!=old['revision']+1 or body['intent_id']!=old['intent_id']
                    or body['created_at']!=audit['created_at'] or body['plan_id']!=audit['plan_id']
                    or audit['plan_id']!=digest(dict(account_id=audit['account_id'],draft_basis_hash=rebuilt['draft_basis_hash']))
                    or audit['draft_basis_hash']!=rebuilt['draft_basis_hash']
                    or canonical({k:body[k] for k in FROZEN})!=canonical({k:rebuilt[k] for k in FROZEN})):raise ValueError('basis')
        except (KeyError,ValueError,TypeError,StopIteration) as exc:
            raise QuantError('CORRUPT_HEDGE_STOCK_REPRICE','原修订引用、财务/价格/剩余数量改变') from exc
