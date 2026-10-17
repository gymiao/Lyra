"""Immutable native-plan groups and prefix-based progress, without second reservations."""
import json
from collections import defaultdict

from ..common import QuantError, canonical, decimal as D, digest, now_utc, utc
from ..locks import publication_lock
from .allocation_store import resources

PREFIX='hedge-group:'
FIELDS={'schema_version','request_id','hedge_id','parent_version','expected_resource_hash','stages','reason'}
STAGE={'stage_id','plan_kind','plan_id','action','depends_on'}


def _plan(book,account_id,kind,plan_id):
    table='plans' if kind=='stock' else 'option_plans'
    if not book.connection.execute("SELECT 1 FROM sqlite_master WHERE name=? AND type='table'",(table,)).fetchone():
        raise QuantError('UNKNOWN_HEDGE_PLAN','账户尚无该类型计划')
    row=book.connection.execute('SELECT * FROM '+table+' WHERE plan_id=? AND account_id=?',(plan_id,account_id)).fetchone()
    if row is None:raise QuantError('UNKNOWN_HEDGE_PLAN','执行计划不属于该账户')
    body=json.loads(row['payload'])
    lines=body['sizing']['lines']
    result=[];seen=set()
    for line in lines:
        symbol=line['symbol'] if kind=='stock' else line['contract_id']
        quantity=D(line['quantity'] if kind=='stock' else line['contracts'])
        if quantity<=0 or line['side'] not in {'BUY','SELL'}:
            raise QuantError('INVALID_HEDGE_PLAN','计划数量和方向无效')
        if symbol in seen:raise QuantError('INVALID_HEDGE_PLAN','同计划不能重复或反向列出同证券/合约')
        seen.add(symbol)
        result.append({'symbol':symbol,'contract_version':None if kind=='stock' else line['contract_version'],
                       'side':line['side'],'quantity':str(quantity)})
    return dict(row),body,result


def history(book,account_id):
    from .intents import records
    book._require_account(account_id)
    parents={r['version_hash']:r for r in records(book,account_id)}
    result=[];seen=set()
    for row in book.connection.execute('SELECT task_id,details FROM tasks WHERE task_id LIKE ?',(PREFIX+'%',)):
        try:
            record=json.loads(row['details'])
            if record['account_id']!=account_id:continue
            parent=parents[record['parent_version']]
            if (record['environment']!=book.environment
                    or record['hedge_id']!=parent['hedge_id']
                    or record['parent_record_hash']!=parent['record_hash']
                    or record['record_hash']!=digest({k:v for k,v in record.items() if k!='record_hash'})
                    or record['group_id']!=digest(record['group_basis'])
                    or record['group_basis']!={'account_id':account_id,'parent_version':record['parent_version'],'stages':record['stages']}
                    or record['request_hash']!=digest(record['request'])
                    or row['task_id']!=PREFIX+digest({'account_id':account_id,'request_id':record['request']['request_id']})
                    or record['parent_version'] in seen):
                raise ValueError('identity')
            supplied=defaultdict(lambda:D(0))
            requested=record['request']['stages']
            if len(requested)!=len(record['stages']):raise ValueError('root stage contract')
            for stage,original in zip(record['stages'],requested):
                if (set(original)!=STAGE or set(stage)!=STAGE|{'lines','initial_plan_hash'}
                        or {k:stage[k] for k in STAGE}!=original):raise ValueError('root stage contract')
                _,_,native=_plan(book,account_id,stage['plan_kind'],stage['plan_id'])
                if native!=stage['lines']:raise ValueError('root native quantities')
                if stage['action']=='OPEN':
                    for line in stage['lines']:
                        supplied[(stage['plan_kind'],line['symbol'],line['contract_version'],line['side'])]+=D(line['quantity'])
            if dict(supplied)!=_candidate_lines(parent['candidate']):raise ValueError('frozen candidate quantities')
            _check_stock_closes(book,account_id,record['stages'])
            seen.add(record['parent_version']);result.append(record)
        except (KeyError,TypeError,ValueError) as exc:
            raise QuantError('CORRUPT_HEDGE_GROUP','执行组记录或原父/计划引用改变') from exc
    roots=sorted(result,key=lambda r:r['group_id'])
    from .group_revisions import history as revisions
    return roots+revisions(book,account_id,roots)


def _check_stock_closes(book,account_id,stages):
    """One reverse obligation per original stock stage, including archived reads."""
    prior={};closed=set()
    for stage in stages:
        if stage['plan_kind']=='stock':
            _,body,_=_plan(book,account_id,'stock',stage['plan_id'])
            context=body.get('hedge_context',{})
            if body.get('purpose')=='hedge_stage' and context.get('action','OPEN')!=stage['action']:
                raise QuantError('HEDGE_STOCK_STAGE_DIRECTION','股票用途与阶段方向不一致')
            if stage['action']=='CLOSE':
                openings=[prior[d] for d in stage['depends_on'] if d in prior and prior[d]['plan_kind']=='stock' and prior[d]['action']=='OPEN']
                ids={s['stage_id'] for s in openings}
                if not ids or ids&closed:raise QuantError('DUPLICATE_HEDGE_CLOSE','原股票阶段须有且仅有一次反向退出义务')
                reverse=defaultdict(lambda:D(0));actual=defaultdict(lambda:D(0))
                for opening in openings:
                    for line in opening['lines']:reverse[(line['symbol'],'SELL' if line['side']=='BUY' else 'BUY')]+=D(line['quantity'])
                for line in stage['lines']:actual[(line['symbol'],line['side'])]+=D(line['quantity'])
                if dict(actual)!=dict(reverse):raise QuantError('HEDGE_CLOSE_BASIS_REQUIRED','原退出数量须与依赖OPEN反向一致')
                if body.get('purpose')=='hedge_stage' and not any(s['plan_id']==context['opening_plan_id'] for s in openings):
                    raise QuantError('HEDGE_CLOSE_BASIS_REQUIRED','原退出引用不能改为其他OPEN')
                closed.update(ids)
        prior[stage['stage_id']]=stage


def _candidate_lines(candidate):
    result=defaultdict(lambda:D(0))
    for trade in candidate['trades']:
        kind=trade.get('kind','stock')
        if kind=='stock':
            q=D(trade['quantity'])
            if 'side' in trade:q*=1 if trade['side']=='BUY' else -1
            key=(kind,trade['symbol'],None,'BUY' if q>0 else 'SELL')
        else:
            q=D(trade['contracts'])*(1 if trade['side']=='BUY' else -1)
            key=(kind,trade['contract_id'],trade['contract_version'],trade['side'])
        result[key]+=abs(q)
    return dict(result)


def prepare(book,account_id,request):
    from .intents import records
    from .intent_actions import history as closures
    if (not isinstance(request,dict) or set(request)!=FIELDS
            or type(request['schema_version']) is not int or request['schema_version']!=1
            or any(not isinstance(request[k],str) or not request[k].strip() for k in FIELDS-{'schema_version','stages'})
            or not isinstance(request['stages'],list) or not 1<=len(request['stages'])<=50):
        raise QuantError('INVALID_HEDGE_GROUP','执行组需完整父版本/资源版本和明确阶段依赖')
    chain=[r for r in records(book,account_id) if r['hedge_id']==request['hedge_id']]
    if not chain:raise QuantError('UNKNOWN_HEDGE_INTENT','父意图不存在于该账户')
    parent=max(chain,key=lambda r:r['revision'])
    if parent['version_hash']!=request['parent_version']:
        raise QuantError('STALE_HEDGE_INTENT_VERSION','执行组需最新父版本')
    if any(r['hedge_id']==parent['hedge_id'] for r in closures(book,account_id)):
        raise QuantError('HEDGE_INTENT_CLOSED','已关闭父意图不能绑定执行组')
    existing=history(book,account_id)
    if any(r['parent_version']==parent['version_hash'] for r in existing):
        raise QuantError('HEDGE_GROUP_ALREADY_BOUND','父修订已绑定执行组；不能新增第二套')
    if resources(book,account_id)!=request['expected_resource_hash']:
        raise QuantError('STALE_HEDGE_RESOURCES','执行组预检资源已变化')
    if parent['candidate']['status']!='SELECTED_FOR_RESEARCH':
        raise QuantError('NO_HEDGE_TRADES','没有选定的候选交易')
    used={(s['plan_kind'],s['plan_id']) for r in existing for s in r['stages']}
    stages=[];ids=set();actions=set();supplied=defaultdict(lambda:D(0))
    for stage in request['stages']:
        if (not isinstance(stage,dict) or set(stage)!=STAGE
                or any(not isinstance(stage[k],str) or not stage[k] for k in STAGE-{'depends_on'})
                or stage['stage_id'] in ids or stage['plan_kind'] not in {'stock','option'}
                or stage['action'] not in {'OPEN','CLOSE'}
                or not isinstance(stage['depends_on'],list)
                or any(not isinstance(x,str) or x not in ids for x in stage['depends_on'])
                or len(set(stage['depends_on']))!=len(stage['depends_on'])):
            raise QuantError('INVALID_HEDGE_GROUP','阶段ID/计划类型/开平仓或前序依赖无效')
        key=stage['plan_kind'],stage['plan_id']
        if key in used:raise QuantError('HEDGE_PLAN_ALREADY_BOUND','同计划不能重复归属其他父版本')
        action_key=(*key,stage['action'])
        if action_key in actions:raise QuantError('DUPLICATE_HEDGE_STAGE','同计划同方向不能重复登记')
        row,body,lines=_plan(book,account_id,*key)
        if body.get('purpose')=='hedge_stage' and body['hedge_context'].get('action','OPEN')!=stage['action']:
            raise QuantError('HEDGE_STOCK_STAGE_DIRECTION','独立股票草案开平仓用途须与组阶段一致')
        if stage['action']=='CLOSE' and not stage['depends_on']:
            raise QuantError('INVALID_HEDGE_GROUP','退出阶段必须显式依赖前序阶段')
        if stage['action']=='CLOSE':
            openings=[s for s in stages if s['action']=='OPEN' and s['stage_id'] in stage['depends_on']]
            if stage['plan_kind']=='option':
                if not any(s['plan_kind']=='option' and s['plan_id']==stage['plan_id'] for s in openings):
                    raise QuantError('HEDGE_CLOSE_BASIS_REQUIRED','期权退出需引用本组原开仓计划和直接依赖')
            else:
                if body.get('purpose')=='hedge_stage' and not any(s['plan_kind']=='stock' and s['plan_id']==body['hedge_context']['opening_plan_id'] for s in openings):
                    raise QuantError('HEDGE_CLOSE_BASIS_REQUIRED','股票退出须直接依赖其原OPEN计划')
                reverse=defaultdict(lambda:D(0))
                for opening in openings:
                    if opening['plan_kind']!='stock':continue
                    for line in opening['lines']:
                        reverse[(line['symbol'],'SELL' if line['side']=='BUY' else 'BUY')]+=D(line['quantity'])
                closing=defaultdict(lambda:D(0))
                for line in lines:closing[(line['symbol'],line['side'])]+=D(line['quantity'])
                if dict(reverse)!=dict(closing):
                    raise QuantError('HEDGE_CLOSE_BASIS_REQUIRED','股票退出须与所依赖开仓的反向数量一致')
        if stage['action']=='OPEN':
            for line in lines:
                supplied[(stage['plan_kind'],line['symbol'],line['contract_version'],line['side'])]+=D(line['quantity'])
        stages.append({**stage,'lines':lines,'initial_plan_hash':digest(row)})
        ids.add(stage['stage_id']);actions.add(action_key)
    _check_stock_closes(book,account_id,stages)
    if dict(supplied)!=_candidate_lines(parent['candidate']):
        raise QuantError('HEDGE_CANDIDATE_PLAN_MISMATCH','全部开仓/筹资计划必须与冻结候选的确切数量/方向/版本一致')
    if parent['candidate'].get('funding_requires_settlement'):
        funding={s['stage_id'] for s in stages if s['plan_kind']=='stock' and s['action']=='OPEN'}
        if any(not funding<=set(s['depends_on']) for s in stages if s['plan_kind']=='option' and s['action']=='OPEN'):
            raise QuantError('HEDGE_FUNDING_DEPENDENCY_REQUIRED','期权开仓必须显式等待全部筹资成交及结算')
    basis={'account_id':account_id,'parent_version':parent['version_hash'],'stages':stages}
    return {'group_id':digest(basis),'group_basis':basis,'hedge_id':parent['hedge_id'],
            'parent_version':parent['version_hash'],'parent_record_hash':parent['record_hash'],
            'stages':stages,'executable':False,'creates_reservations':False,
            'meaning':'引用原计划与财务事实；不重复预留，不替代逐阶段交易前风险/来源/压力检查'}


def save(book,account_id,request,*,commit=False):
    with publication_lock(book.path.parent),book.transaction():
        book._require_account(account_id)
        key=PREFIX+digest({'account_id':account_id,'request_id':request.get('request_id') if isinstance(request,dict) else None})
        row=book.connection.execute('SELECT details FROM tasks WHERE task_id=?',(key,)).fetchone()
        if row:
            old=json.loads(row[0]);history(book,account_id)
            if old['request_hash']!=digest(request):raise QuantError('HEDGE_GROUP_REQUEST_CONFLICT','执行组请求ID与内容冲突')
            return old
        body=prepare(book,account_id,request)
        if not commit:return {'status':'PREVIEW',**body}
        record={'schema_version':1,'status':'BOUND','account_id':account_id,'environment':book.environment,
                'request':request,'request_hash':digest(request),'recorded_at':now_utc(),**body}
        record['record_hash']=digest(record)
        book.connection.execute('INSERT INTO tasks VALUES(?,?,?,?)',(key,'BOUND',canonical(record),record['recorded_at']))
        return record


def progress(book,account_id,group,as_of,*,ledger_seq=None):
    with publication_lock(book.path.parent),book.transaction():
        return _progress(book,account_id,group,as_of,ledger_seq=ledger_seq,cache={})


def _progress(book,account_id,group,as_of,*,ledger_seq=None,cache):
    """Actual linked receipts; dependency completion includes settlement, not just fills."""
    sequence=book.sequence(account_id) if ledger_seq is None else ledger_seq
    if type(sequence) is not int or not 0<=sequence<=book.sequence(account_id):
        raise QuantError('INVALID_LEDGER_SEQUENCE','执行组序号必须是已存在账户前缀')
    clock=utc(as_of)
    if clock>utc(now_utc()):raise QuantError('FUTURE_HEDGE_PROGRESS','不能读取未来执行状态')
    cache_key=(len(group['stages']),sequence,clock.isoformat())
    if cache_key in cache:return cache[cache_key]
    events=book.active_events(account_id,clock,sequence)
    stages=[];completed={};issues=[]
    option_bodies=None
    for stage in group['stages']:
        row,body,current=_plan(book,account_id,stage['plan_kind'],stage['plan_id'])
        problems=[]
        if current!=stage.get('native_lines',stage['lines']):problems.append('NATIVE_PLAN_LINES_CHANGED')
        stock_events=events;stock_clock=clock;stock_expected=stage['lines'];stock_conversion=False
        if stage['plan_kind']=='stock':
            from .stock_units import stage_basis,lines_at,quantity
            try:
                basis,basis_seq=stage_basis(stage,body)
            except QuantError:
                problems.append('NATIVE_STOCK_UNIT_BASIS_MISSING')
            else:
                stock_conversion=True;stock_clock=max(clock,utc(basis))
                stock_events=book.active_events(account_id,stock_clock,sequence)
                stock_expected=lines_at(stock_events,stage['lines'],basis,stock_clock,origin_seq=basis_seq)
                if any(e['kind']=='SPLIT' and e['symbol'] in {l['symbol'] for l in stage['lines']}
                        and (utc(e['effective_at'])>utc(basis) or (utc(e['effective_at'])==utc(basis) and (basis_seq is None or e['seq']>basis_seq)))
                        and utc(e['effective_at'])<=clock for e in stock_events):
                    problems.append('STOCK_UNITS_CHANGED_REQUIRES_GROUP_REVISION')
        linked=[e for e in events if e['plan_id']==stage['plan_id']]
        filled=defaultdict(lambda:D(0));pending=[];receipts=[]
        for e in linked:
            if stage['plan_kind']=='stock':
                if e['kind'] not in {'BUY','SELL'}:continue
                key=(e['symbol'],None,e['kind'])
                q=D(quantity(stock_events,e['symbol'],e['quantity'],e['effective_at'],stock_clock,origin_seq=e['seq'])['quantity']) if stock_conversion else D(e['quantity'])
            else:
                if not e['kind'].startswith('OPTION_'):continue
                opening=e['kind']=='OPTION_TRADE' and e.get('action')=='OPEN'
                if opening!=(stage['action']=='OPEN'):continue
                side=(e['trade_side'] if e['kind']=='OPTION_TRADE' else
                      'SELL' if e.get('position_side')=='LONG' else 'BUY')
                if stage['action']=='CLOSE':side='SELL' if side=='BUY' else 'BUY'
                key=(e['symbol'],e['contract_version'],side);q=D(e['quantity'])
            filled[key]+=q
            receipts.append(e)
            if group.get('schema_version')==2 and e['seq']>group['basis_sequence'] and utc(e['effective_at'])<utc(group['as_of']):
                problems.append('LATE_FACT_BEFORE_GROUP_REVISION')
            if not e.get('settlement_at') or utc(e['settlement_at'])>clock:pending.append(e['event_id'])
        expected={(l['symbol'],l['contract_version'],l['side']):D(l['quantity']) for l in stock_expected}
        if set(filled)-set(expected) or any(filled[k]>q for k,q in expected.items()):
            problems.append('UNEXPECTED_OR_EXCESS_LINKED_FACT')
        missing={str(k):str(max(D(0),q-filled[k])) for k,q in expected.items()}
        pending_manual=bool(row.get('manual_pending',0))
        if stage['plan_kind']=='option':
            if option_bodies is None:
                from ..options.lifecycle import refresh
                option_bodies={p['plan_id']:p for p in refresh(book,account_id,clock,persist=False,ledger_seq=sequence)}
            native=option_bodies[stage['plan_id']]
            pending_manual=bool(native.get('manual_execution',{}).get('pending'))
            problems.extend(native['progress']['fact_anomalies'])
        done=all(D(q)==0 for q in missing.values()) and not pending and not pending_manual and not problems
        unmet=[d for d in stage['depends_on'] if not completed[d]]
        for receipt in receipts:
            if not stage['depends_on']:break
            previous=_progress(book,account_id,{**group,'stages':group['stages'][:len(stages)]},receipt['effective_at'],ledger_seq=sequence,cache=cache)
            historical={r['stage_id']:r['status'] for r in previous['stages']}
            if any(historical[d]!='COMPLETE' for d in stage['depends_on']):
                problems.append('DEPENDENCY_NOT_COMPLETED_AT_FILL');break
        completed[stage['stage_id']]=done and not unmet
        status=('BLOCKED' if problems else 'COMPLETE' if completed[stage['stage_id']] else
                'WAITING_DEPENDENCY' if unmet else 'SETTLEMENT_PENDING' if pending else
                'PARTIAL' if any(filled.values()) else 'WAITING_FACTS')
        stages.append({'stage_id':stage['stage_id'],'status':status,'remaining':missing,
                       'event_ids':[e['event_id'] for e in linked],'pending_settlements':pending,
                       'manual_pending':pending_manual,'unmet_dependencies':unmet,'checks':problems})
        issues.extend(problems)
    result={'group_id':group['group_id'],'parent_version':group['parent_version'],'as_of':clock.isoformat(),
            'ledger_seq':sequence,'stages':stages,'status':'BLOCKED' if issues else
            'COMPLETE' if all(completed.values()) else 'IN_PROGRESS','executable':False,
            'creates_reservations':False,'ledger_view':'restated',
            'meaning':'依据已记录事实重建执行/结算时序；不是当时实时获知或交易资格证明'}
    cache[cache_key]=result
    return result

