"""Generate existing option-service drafts and bind exact native stock references atomically."""
import json
from ..common import QuantError,canonical,digest,decimal as D,now_utc,utc
from ..locks import publication_lock
from ..options.plans import draft,sizing,RISK_FIELDS
from ..options.data import OptionDataStore
from .allocation_store import resources
from .intents import records
from .intent_actions import history as closures
from .groups import save as bind,history as groups,_plan

PREFIX='hedge-native-plans:'
FIELDS={'schema_version','request_id','hedge_id','parent_version','expected_resource_hash','as_of',
        'option_risk','stock_stages','include_option_close','reason'}


def prepare(book,account_id,request):
    if (not isinstance(request,dict) or set(request)!=FIELDS or type(request['schema_version']) is not int
            or request['schema_version']!=1 or type(request['include_option_close']) is not bool
            or not isinstance(request['stock_stages'],list)
            or any(not isinstance(request[k],str) or not request[k].strip() for k in
                   FIELDS-{'schema_version','option_risk','stock_stages','include_option_close'})):
        raise QuantError('INVALID_NATIVE_HEDGE_PLANS','需父/资源版本、时点、明确期权风险参数及股票阶段引用')
    chain=[p for p in records(book,account_id) if p['hedge_id']==request['hedge_id']]
    parent=max(chain,key=lambda p:p['revision']) if chain else None
    if parent is None:raise QuantError('UNKNOWN_HEDGE_INTENT','该账户没有原父意图')
    if parent['version_hash']!=request['parent_version']:raise QuantError('STALE_HEDGE_INTENT_VERSION','须原父最新版本')
    clock=utc(request['as_of'])
    if clock>utc(now_utc()) or not utc(parent['decision_at'])<=clock<=utc(parent['valid_until']):
        raise QuantError('HEDGE_INTENT_EXPIRED','新计划必须在原父有效窗口')
    if any(c['hedge_id']==parent['hedge_id'] for c in closures(book,account_id)):raise QuantError('HEDGE_INTENT_CLOSED','原父已关闭')
    if any(e['seq']>parent['ledger_seq'] and e['kind'] in {'DEPOSIT','WITHDRAWAL'} for e in book.active_events(account_id,request['as_of'])):
        raise QuantError('HEDGE_CAPITAL_CHANGED','父冻结后外部资金改变，不能用旧决定投入新资金；等待新合格决策')
    if resources(book,account_id)!=request['expected_resource_hash']:raise QuantError('STALE_HEDGE_RESOURCES','原计划或资源已变化')
    if any(g['parent_version']==parent['version_hash'] for g in groups(book,account_id)):
        raise QuantError('HEDGE_GROUP_ALREADY_BOUND','父已绑定执行组，剩余数量使用显式修订')
    candidate=parent['candidate']
    if candidate['status']!='SELECTED_FOR_RESEARCH':raise QuantError('NO_HEDGE_TRADES','原父没有可生成的选定交易')
    stages=[];actual={};ids=set()
    for stage in request['stock_stages']:
        if (not isinstance(stage,dict) or set(stage)!={'stage_id','plan_kind','plan_id','action','depends_on'}
                or any(not isinstance(stage[k],str) or not stage[k] for k in ('stage_id','plan_kind','plan_id','action'))
                or not isinstance(stage['depends_on'],list) or any(not isinstance(d,str) for d in stage['depends_on'])
                or stage['plan_kind']!='stock' or stage['action'] not in {'OPEN','CLOSE'}
                or stage['stage_id'] in ids or stage['stage_id'] in {'option-open','option-close'}):
            raise QuantError('INVALID_NATIVE_HEDGE_PLANS','股票阶段须引用明确原计划，不占用生成的期权阶段ID')
        ids.add(stage['stage_id']);row,_,lines=_plan(book,account_id,'stock',stage['plan_id'])
        if row['manual_pending']:raise QuantError('PENDING_MANUAL_ORDER','股票计划已有在途，不能重新绑定')
        if stage['action']=='OPEN':
            for line in lines:actual[(line['symbol'],line['side'])]=actual.get((line['symbol'],line['side']),D(0))+D(line['quantity'])
        stages.append(stage)
    expected={}
    for trade in candidate['trades']:
        if trade.get('kind','stock')!='stock':continue
        q=D(trade['quantity']);side=trade.get('side','BUY' if q>0 else 'SELL')
        expected[(trade['symbol'],side)]=expected.get((trade['symbol'],side),D(0))+abs(q)
    if expected!=actual:raise QuantError('HEDGE_CANDIDATE_PLAN_MISMATCH','股票原计划须包含全部且仅包含父冻结股票交易')
    selection=candidate.get('selection');option_request=None;option_preview=None
    if selection:
        risk=request['option_risk']
        if not isinstance(risk,dict) or set(risk)!=RISK_FIELDS:raise QuantError('INVALID_OPTION_RISK','须明确完整期权风险参数，不继承示例')
        original=parent['request']['preview_request']['option']
        if D(risk['fee_per_contract'])!=D(candidate['spec']['option_fee_per_contract']) or D(risk['adverse_slippage_fraction'])!=D(original['limits']['adverse_slippage_fraction']):
            raise QuantError('HEDGE_COST_ASSUMPTION_MISMATCH','费用/滑点不得静默改变原父条件')
        packages=D(candidate['incremental_packages'])
        if packages<=0 or packages!=packages.to_integral_value():raise QuantError('NO_HEDGE_TRADES','没有新增整组张数')
        option_request=dict(selection=original['selection_request'],packages=int(packages),risk=risk,revision=1)
        marks={}
        for leg in selection['legs']:
            q=leg['reference_quote'];marks[selection['underlying']]=q['underlying_price']
            marks[leg['contract']['contract_id']]=str((D(q['bid'])+D(q['ask']))/2)
        snapshot=book.snapshot(account_id,selection['decision_at'],marks)
        option_preview=sizing(selection,snapshot,int(packages),risk)
    elif request['option_risk'] is not None or request['include_option_close']:
        raise QuantError('INVALID_NATIVE_HEDGE_PLANS','纯股票父应显式option_risk=null且不生成期权退出')
    return parent,stages,option_request,option_preview


def save(book,account_id,request,*,commit=False):
    with publication_lock(book.path.parent),book.transaction():
        key=PREFIX+digest({'account_id':account_id,'request_id':request.get('request_id') if isinstance(request,dict) else None})
        previous=book.connection.execute('SELECT details FROM tasks WHERE task_id=?',(key,)).fetchone()
        if previous:
            body=json.loads(previous[0]);validate_references(book)
            if body['request_hash']!=digest(request):raise QuantError('HEDGE_NATIVE_REQUEST_CONFLICT','同请求ID不能改变生成条件')
            if body['record_hash']!=digest({k:v for k,v in body.items() if k!='record_hash'}):raise QuantError('CORRUPT_NATIVE_HEDGE_PLANS','原生成审计已改变')
            found=[g for g in groups(book,account_id) if g['group_id']==body['group']['group_id']]
            if len(found)!=1 or found[0]['record_hash']!=body['group']['record_hash']:raise QuantError('CORRUPT_NATIVE_HEDGE_PLANS','原执行组已改变')
            return body
        parent,stages,option_request,preview=prepare(book,account_id,request)
        if not commit:return dict(status='PREVIEW',parent_version=parent['version_hash'],stock_stages=stages,
            option_request=option_request,option_sizing=preview,executable=False,creates_reservations=False)
        native=None
        if option_request:
            native=draft(book,OptionDataStore(book.path.parent/'options/chains'),parent['candidate']['option_snapshot_id'],account_id,option_request)
            if native['status']!='DRAFT' or native.get('manual_execution',{}).get('pending') or any(
                    e['plan_id']==native['plan_id'] for e in book.active_events(account_id,request['as_of'])):
                raise QuantError('NATIVE_PLAN_ALREADY_USED','新生成阶段不能借用已有成交/激活/在途的计划')
            if native['selection']['decision_hash']!=parent['candidate']['selection']['decision_hash']:
                raise QuantError('HEDGE_SELECTION_CHANGED','原选约不能在生成时变化')
        opens=[s for s in stages if s['action']=='OPEN'];closes=[s for s in stages if s['action']=='CLOSE'];assembled=list(opens)
        if native:
            depends=[s['stage_id'] for s in opens] if parent['candidate'].get('funding_requires_settlement') else []
            assembled.append(dict(stage_id='option-open',plan_kind='option',plan_id=native['plan_id'],action='OPEN',depends_on=depends))
            if request['include_option_close']:assembled.append(dict(stage_id='option-close',plan_kind='option',plan_id=native['plan_id'],action='CLOSE',depends_on=['option-open']))
        assembled+=closes
        group=bind(book,account_id,dict(schema_version=1,request_id='native:'+request['request_id'],hedge_id=parent['hedge_id'],
            parent_version=parent['version_hash'],expected_resource_hash=resources(book,account_id),stages=assembled,reason=request['reason']),commit=True)
        result=dict(schema_version=1,status='GENERATED_DRAFTS',request=request,request_hash=digest(request),account_id=account_id,
            parent_version=parent['version_hash'],option_plan_id=native['plan_id'] if native else None,group=group,
            option_checks=native['checks'] if native else [],executable=False,creates_reservations=False,recorded_at=now_utc(),
            meaning='复用原期权草案服务和明确股票计划引用；尚须逐阶段激活，不写成交或额外预留')
        result['record_hash']=digest(result);book.record_task(key,'BOUND',result);return result


def validate_references(book):
    for row in book.connection.execute('SELECT task_id,details FROM tasks WHERE task_id LIKE ?',(PREFIX+'%',)):
        try:
            body=json.loads(row['details']);request=body['request'];account=body['account_id']
            if (body['schema_version']!=1 or body['status']!='GENERATED_DRAFTS' or set(request)!=FIELDS
                    or body['request_hash']!=digest(request)
                    or body['record_hash']!=digest({k:v for k,v in body.items() if k!='record_hash'})
                    or row['task_id']!=PREFIX+digest({'account_id':account,'request_id':request['request_id']})):
                raise ValueError('identity')
            original=next(g for g in groups(book,account) if g['group_id']==body['group']['group_id'])
            if (original['record_hash']!=body['group']['record_hash'] or original['parent_version']!=request['parent_version']
                    or original['hedge_id']!=request['hedge_id'] or original['request']['request_id']!='native:'+request['request_id']):
                raise ValueError('group')
            if body['option_plan_id'] is not None:
                _,plan,_=_plan(book,account,'option',body['option_plan_id'])
                if plan['request']['risk']!=request['option_risk'] or not any(s['plan_id']==body['option_plan_id'] and s['plan_kind']=='option' for s in original['stages']):
                    raise ValueError('native option')
        except (KeyError,ValueError,TypeError,StopIteration) as exc:
            raise QuantError('CORRUPT_NATIVE_HEDGE_PLANS','原生成记录/执行组/原生期权条件改变') from exc
