"""Immutable amendments of remaining native-plan stages, without financial writes."""
import json
from ..common import QuantError,canonical,digest,now_utc,utc,decimal as D
from ..locks import publication_lock
from .allocation_store import resources

PREFIX='hedge-group-revision:'
FIELDS={'schema_version','request_id','previous_group_id','expected_group_hash','expected_resource_hash','as_of','replacements','reason'}


def _stock_invariants(book,account_id,record,previous,root):
    """Rebuild stock fact slices at the original prefix, and one full exit obligation."""
    from .groups import _plan,_check_stock_closes
    source={s['stage_id']:s for s in previous['stages']};current={s['stage_id']:s for s in record['stages']}
    events=book.active_events(account_id,record['as_of'],ledger_seq=record['basis_sequence'])
    from .stock_units import stage_basis,stage_quantities,lines_at,rebase_stage
    normalize=lambda rows:sorted((l['symbol'],l['side'],D(l['quantity'])) for l in rows)
    for identity,new_id in record['request']['replacements'].items():
        old=source[identity]
        if old['plan_kind']!='stock':continue
        _,old_body,old_native=_plan(book,account_id,'stock',old['plan_id'])
        origin,origin_seq=stage_basis(old,old_body)
        units=stage_quantities(events,old['plan_id'],old['lines'],origin,record['as_of'],origin_seq=origin_seq)
        expected=units['expected'];actual=units['filled']
        filled=[dict(symbol=s,side=side,quantity=str(actual.get((s,side),D(0)))) for s,side in expected if actual.get((s,side),D(0))>0]
        remaining=[dict(symbol=s,side=side,quantity=str(v)) for (s,side),v in units['remaining'].items()]
        retired=current[identity+'__retired_r'+str(record['revision'])];replacement=current[identity]
        _,old_body,old_native=_plan(book,account_id,'stock',old['plan_id'])
        _,new_body,new_native=_plan(book,account_id,'stock',new_id)
        if (normalize(retired['lines'])!=normalize(filled) or not retired.get('historical_slice')
                or retired['plan_id']!=old['plan_id'] or retired['native_lines']!=old_native
                or replacement['plan_id']!=new_id or replacement.get('historical_slice')
                or normalize(replacement['lines'])!=normalize(remaining) or normalize(new_native)!=normalize(remaining)
                or retired['action']!=old['action'] or replacement['action']!=old['action']):raise ValueError('stock slices')
        if old_body.get('purpose')=='hedge_stage':
            c=new_body.get('hedge_context',{})
            if (new_body.get('purpose')!='hedge_stage' or c.get('revision_of')!=old['plan_id']
                    or c.get('parent_version')!=root['parent_version'] or c.get('action','OPEN')!=old['action']):raise ValueError('typed stock reprice')
        if old['action']=='CLOSE':
            obligation=old.get('close_obligation_id',identity)
            if retired.get('close_obligation_id')!=obligation or replacement.get('close_obligation_id')!=obligation:raise ValueError('close origin')
    unit_mode=bool(record.get('unit_rebase'))
    for old in previous['stages']:
        if old['plan_kind']!='stock':continue
        _,body,_=_plan(book,account_id,'stock',old['plan_id'])
        if old['stage_id'] not in record['request']['replacements']:
            expected_stage=rebase_stage(events,old,body,record['as_of'],record['basis_sequence']) if unit_mode else old
            dependencies=list(old['depends_on'])
            for dep in old['depends_on']:
                if dep in record['request']['replacements']:dependencies.append(dep+'__retired_r'+str(record['revision']))
            expected_stage={**expected_stage,'depends_on':dependencies}
            if canonical(current[old['stage_id']])!=canonical(expected_stage):raise ValueError('untouched stock stage')
        elif unit_mode:
            for identity in (old['stage_id'],old['stage_id']+'__retired_r'+str(record['revision'])):
                if current[identity].get('unit_basis_at')!=record['as_of'] or current[identity].get('unit_basis_sequence')!=record['basis_sequence']:
                    raise ValueError('stock unit basis')
            _,new_body,_=_plan(book,account_id,'stock',record['request']['replacements'][old['stage_id']])
            u=new_body.get('hedge_context',{}).get('unit_rebase')
            origin,seq=stage_basis(old,body)
            actual_units=stage_quantities(events,old['plan_id'],old['lines'],origin,record['as_of'],origin_seq=seq)
            if (not u or u!={'group_id':previous['group_id'],'as_of':record['as_of'],'ledger_seq':record['basis_sequence'],'actions':actual_units['actions']}):
                raise ValueError('stock unit request')
    if unit_mode:
        if (any(s['plan_kind']!='stock' for s in previous['stages']) or
                record['unit_rebase']!={'as_of':record['as_of'],'ledger_seq':record['basis_sequence']}):raise ValueError('unit group mode')
    else:
        for identity in record['request']['replacements']:
            if source[identity]['plan_kind']!='stock':continue
            for sid in (identity,identity+'__retired_r'+str(record['revision'])):
                for field in ('unit_basis_at','unit_basis_sequence'):
                    if current[sid].get(field)!=source[identity].get(field):raise ValueError('unrequested unit basis')
    # Several retired/replacement CLOSE slices are one original obligation.
    root_closes={s['stage_id']:s for s in root['stages'] if s['plan_kind']=='stock' and s['action']=='CLOSE'}
    exits={};last={}
    for index,stage in enumerate(record['stages']):
        if stage['plan_kind']!='stock' or stage['action']!='CLOSE':continue
        identity=stage.get('close_obligation_id',stage['stage_id'])
        original=root_closes[identity];_,original_body,_=_plan(book,account_id,'stock',original['plan_id'])
        _,body,_=_plan(book,account_id,'stock',stage['plan_id'])
        if body.get('purpose')=='hedge_stage' and body['hedge_context']['opening_plan_id']!=original_body['hedge_context']['opening_plan_id']:raise ValueError('close opening origin')
        if identity not in exits:exits[identity]={**original,'lines':[],'depends_on':[]}
        exits[identity]['lines']+=stage['lines'];last[identity]=index
        for d in stage['depends_on']:
            if d not in exits[identity]['depends_on']:exits[identity]['depends_on'].append(d)
    consolidated=[]
    for index,stage in enumerate(record['stages']):
        if stage['plan_kind']=='stock' and stage['action']=='CLOSE':
            identity=stage.get('close_obligation_id',stage['stage_id'])
            if last[identity]==index:consolidated.append(exits[identity])
        else:consolidated.append(stage)
    _check_stock_closes(book,account_id,consolidated)


def history(book,account_id,roots):
    known={r['group_id']:r for r in roots};heads={r['group_id']:r for r in roots};result=[]
    for row in book.connection.execute('SELECT task_id,details FROM tasks WHERE task_id LIKE ? ORDER BY rowid',(PREFIX+'%',)):
        try:
            record=json.loads(row['details'])
            if record['account_id']!=account_id:continue
            request=record['request'];previous=known[request['previous_group_id']];root=known[record['root_group_id']]
            if (record['record_hash']!=digest({k:v for k,v in record.items() if k!='record_hash'})
                    or record['schema_version']!=2 or record['status']!='BOUND'
                    or record['previous_group_id']!=previous['group_id']
                    or record['as_of']!=utc(request['as_of']).isoformat()
                    or type(record['basis_sequence']) is not int or not 0<=record['basis_sequence']<=book.sequence(account_id)
                    or record['request_hash']!=digest(request)
                    or record['group_id']!=digest(record['group_basis'])
                    or record['group_basis']!={'account_id':account_id,'parent_version':record['parent_version'],
                                              'previous_group_id':previous['group_id'],'stages':record['stages']}
                    or record['parent_version']!=root['parent_version'] or record['hedge_id']!=root['hedge_id']
                    or record['parent_record_hash']!=root['parent_record_hash']
                    or record['environment']!=book.environment
                    or request['expected_group_hash']!=previous['record_hash']
                    or heads[record['root_group_id']]['group_id']!=previous['group_id']
                    or record['revision']!=previous.get('revision',1)+1
                    or row['task_id']!=PREFIX+digest({'account_id':account_id,'request_id':request['request_id']})):
                raise ValueError('identity/chain')
            from .groups import _plan
            from collections import defaultdict
            actual=defaultdict(lambda:D(0));ids=set()
            for stage in record['stages']:
                if stage['stage_id'] in ids or any(d not in ids for d in stage['depends_on']):raise ValueError('stage dependencies')
                ids.add(stage['stage_id']);_plan(book,account_id,stage['plan_kind'],stage['plan_id'])
                for line in stage['lines']:
                    if D(line['quantity'])<=0:raise ValueError('quantity')
                    if stage['action']=='OPEN':actual[(stage['plan_kind'],line['symbol'],line['contract_version'],line['side'])]+=D(line['quantity'])
            expected=defaultdict(lambda:D(0))
            for stage in root['stages']:
                if stage['action']=='OPEN':
                    lines=stage['lines']
                    if stage['plan_kind']=='stock':
                        from .stock_units import lines_at,stage_basis
                        _,body,_=_plan(book,account_id,'stock',stage['plan_id'])
                        origin,origin_seq=stage_basis(stage,body)
                        lines=lines_at(book.active_events(account_id,record['as_of'],record['basis_sequence']),lines,origin,record['as_of'],origin_seq=origin_seq)
                    for line in lines:expected[(stage['plan_kind'],line['symbol'],line['contract_version'],line['side'])]+=D(line['quantity'])
            if dict(actual)!=dict(expected):raise ValueError('candidate quantities')
            _stock_invariants(book,account_id,record,previous,root)
            known[record['group_id']]=record;heads[root['group_id']]=record;result.append(record)
        except (KeyError,TypeError,ValueError) as exc:
            raise QuantError('CORRUPT_HEDGE_GROUP_REVISION','执行组修订链、数量或原父/计划引用改变') from exc
    return result


def heads(records,as_of=None,ledger_seq=None):
    result={}
    for record in records:
        if record.get('schema_version')==2 and ((as_of is not None and utc(record['as_of'])>utc(as_of))
                or (ledger_seq is not None and record['basis_sequence']>ledger_seq)):continue
        root=record.get('root_group_id',record['group_id'])
        if root not in result or record.get('revision',1)>result[root].get('revision',1):result[root]=record
    return [result[k] for k in sorted(result)]


def prepare(book,account_id,request):
    from .groups import history as groups,_plan,progress
    from .intent_actions import history as closures
    if (not isinstance(request,dict) or set(request)!=FIELDS or type(request['schema_version']) is not int
            or request['schema_version']!=1
            or any(not isinstance(request[k],str) or not request[k].strip() for k in FIELDS-{'schema_version','replacements'})
            or not isinstance(request['replacements'],dict) or not request['replacements']
            or any(not isinstance(k,str) or not k or not isinstance(v,str) or not v for k,v in request['replacements'].items())):
        raise QuantError('INVALID_HEDGE_GROUP_REVISION','修订需原组版本、资源哈希、时点和明确阶段→新计划映射')
    clock=utc(request['as_of'])
    if clock>utc(now_utc()):raise QuantError('FUTURE_HEDGE_REVISION','不能修订未来执行状态')
    records=groups(book,account_id);current=heads(records)
    matched=[r for r in current if r['group_id']==request['previous_group_id']]
    if len(matched)!=1 or matched[0]['record_hash']!=request['expected_group_hash']:
        raise QuantError('STALE_HEDGE_GROUP_REVISION','需当前有效执行组修订和原记录哈希')
    previous=matched[0];root_id=previous.get('root_group_id',previous['group_id'])
    from .intents import records as parents
    parent=next(p for p in parents(book,account_id) if p['version_hash']==previous['parent_version'])
    only_stock_close=all(any(s['stage_id']==key and s['plan_kind']=='stock' and s['action']=='CLOSE' for s in previous['stages']) for key in request['replacements'])
    if not only_stock_close and not utc(parent['decision_at'])<=clock<=utc(parent['valid_until']):
        raise QuantError('HEDGE_INTENT_EXPIRED','修订须仍在原父目标有效窗口，不重开历史方向')
    if not only_stock_close and any(r['hedge_id']==previous['hedge_id'] for r in closures(book,account_id)):
        raise QuantError('HEDGE_INTENT_CLOSED','父意图已关闭，不能重新修订剩余执行')
    if ((previous.get('as_of') and clock<utc(previous['as_of']))
            or (book.environment!='demo' and clock<utc(previous['recorded_at']))):
        raise QuantError('HEDGE_REVISION_TIME_REVERSED','修订不得倒退生效/实际记录时点')
    if resources(book,account_id)!=request['expected_resource_hash']:
        raise QuantError('STALE_HEDGE_RESOURCES','修订预检资源已变化')
    unit_mode=any(_plan(book,account_id,'stock',new_id)[1].get('hedge_context',{}).get('unit_rebase',{}).get('group_id')==previous['group_id'] for identity,new_id in request['replacements'].items() if any(s['stage_id']==identity and s['plan_kind']=='stock' for s in previous['stages']))
    if unit_mode and any(s['plan_kind']!='stock' for s in previous['stages']):raise QuantError('OPTION_UNIT_REQUALIFICATION_REQUIRED','股票单位修订不能隐式改期权阶段')
    view=progress(book,account_id,previous,clock)
    unit_only=unit_mode and all(set(s['checks'])<={'STOCK_UNITS_CHANGED_REQUIRES_GROUP_REVISION'} for s in view['stages'])
    if (view['status']=='BLOCKED' and not unit_only) or any(s['manual_pending'] for s in view['stages']):
        raise QuantError('UNRESOLVED_HEDGE_EXECUTION','原执行异常或人工在途尚未解决，不能用新修订掩盖')
    source={s['stage_id']:s for s in previous['stages']};states={s['stage_id']:s for s in view['stages']}
    if set(request['replacements'])-set(source):raise QuantError('UNKNOWN_HEDGE_STAGE','要替换的阶段不存在')
    events=book.active_events(account_id,clock)
    if unit_mode:
        from .stock_units import stage_basis,stage_quantities,rebase_stage
        for stage in previous['stages']:
            if stage.get('historical_slice'):continue
            _,body,_=_plan(book,account_id,'stock',stage['plan_id'])
            origin,seq=stage_basis(stage,body)
            units=stage_quantities(events,stage['plan_id'],stage['lines'],origin,clock,origin_seq=seq)
            if units['actions'] and units['remaining'] and stage['stage_id'] not in request['replacements']:
                raise QuantError('INCOMPLETE_STOCK_UNIT_REVISION','全部受影响未成交阶段须一起显式替换，包括关闭义务')
    used={(s['plan_kind'],s['plan_id']) for r in records for s in r['stages']}
    replacements={};carry={};number=previous.get('revision',1)+1
    for identity,new_id in request['replacements'].items():
        stage=source[identity]
        if stage.get('historical_slice') or (stage['action']!='OPEN' and not (stage['plan_kind']=='stock' and stage['action']=='CLOSE')):
            raise QuantError('INVALID_HEDGE_STAGE_REPLACEMENT','已冻结事实切片和退出阶段不能作为新增开仓方向替换')
        row,body,native=_plan(book,account_id,stage['plan_kind'],stage['plan_id'])
        status=row.get('execution_status',row.get('status'))
        if status not in {'CANCELLED','EXPIRED','SUPERSEDED'} or D(row['reserved_cash'])!=0 or json.loads(row['reserved_positions']):
            raise QuantError('NATIVE_PLAN_NOT_RELEASED','原计划须明确结束未成交部分并释放原预留；修订不撤单或释放资源')
        if (stage['plan_kind'],new_id) in used:raise QuantError('HEDGE_PLAN_ALREADY_BOUND','新计划已绑定其他或历史阶段，不能重复使用')
        used.add((stage['plan_kind'],new_id))
        _,_,new_lines=_plan(book,account_id,stage['plan_kind'],new_id)
        if stage['plan_kind']=='stock':
            _,new_body,_=_plan(book,account_id,'stock',new_id)
            if body.get('purpose')=='hedge_stage':
                from .stock_plans import validate_references
                validate_references(book)
                if (new_body.get('purpose')!='hedge_stage' or new_body['hedge_context'].get('revision_of')!=stage['plan_id']
                        or new_body['hedge_context'].get('action','OPEN')!=stage['action']):
                    raise QuantError('HEDGE_STOCK_REPRICE_REQUIRED','独立股票剩余引用须明确原修订草案')
            if stage['action']=='CLOSE' and (new_body.get('purpose')!='hedge_stage' or clock>=utc(new_body['execution_deadline'])):
                raise QuantError('HEDGE_CLOSE_WINDOW_EXPIRED','关闭修订须明确未到期原生退出草案')
        if any(e['plan_id']==new_id for e in book.active_events(account_id,clock)):
            raise QuantError('NEW_HEDGE_PLAN_HAS_FACTS','新剩余计划必须在实际成交前绑定')
        remaining=[];filled=[]
        stage_lines=stage['lines']
        if unit_mode:stage_lines=rebase_stage(events,stage,body,clock,book.sequence(account_id))['lines']
        for line in stage_lines:
            q=D(states[identity]['remaining'][str((line['symbol'],line['contract_version'],line['side']))])
            if q>0:remaining.append({**line,'quantity':str(q)})
            if D(line['quantity'])-q>0:filled.append({**line,'quantity':str(D(line['quantity'])-q)})
        if not remaining:raise QuantError('HEDGE_STAGE_ALREADY_FILLED','已完成方向不能因价格漂移重新开启')
        norm=lambda lines:sorted([(l['symbol'],l['contract_version'] or '',l['side'],D(l['quantity'])) for l in lines])
        if norm(new_lines)!=norm(remaining):raise QuantError('HEDGE_REMAINING_QUANTITY_MISMATCH','新计划须等于原方向/单位/合约的确切未成交数量')
        cid=identity+'__retired_r'+str(number)
        if cid in source:raise QuantError('DUPLICATE_HEDGE_STAGE','保留事实阶段ID冲突')
        carry[identity]={**stage,'stage_id':cid,'lines':filled,'native_lines':native,
                         'historical_slice':True,'retired_at':clock.isoformat()}
        replacements[identity]={**stage,'plan_id':new_id,'lines':new_lines,'initial_plan_hash':digest(_plan(book,account_id,stage['plan_kind'],new_id)[0])}
        if stage['plan_kind']=='stock':
            replacements[identity].pop('native_lines',None)
            if unit_mode:
                carry[identity].update(unit_basis_at=clock.isoformat(),unit_basis_sequence=book.sequence(account_id))
                replacements[identity].update(unit_basis_at=clock.isoformat(),unit_basis_sequence=book.sequence(account_id))
        if stage['plan_kind']=='stock' and stage['action']=='CLOSE':
            obligation=stage.get('close_obligation_id',identity)
            carry[identity]['close_obligation_id']=obligation;replacements[identity]['close_obligation_id']=obligation
    stages=[];closing_alias={}
    for stage in previous['stages']:
        identity=stage['stage_id']
        if identity in carry:stages.append(carry[identity])
        current=replacements.get(identity,dict(stage))
        if unit_mode and identity not in replacements:
            _,body,_=_plan(book,account_id,'stock',stage['plan_id'])
            current=rebase_stage(events,current,body,clock,book.sequence(account_id))
        if current['plan_kind']=='option' and current['action']=='CLOSE':
            related=[k for k in replacements if source[k]['plan_kind']=='option' and source[k]['plan_id']==stage['plan_id']]
            if related:
                key=related[0];opening=replacements[key]
                if key in carry:
                    current={**current,'lines':carry[key]['lines'],'native_lines':source[key].get('native_lines',source[key]['lines']),
                             'depends_on':[carry[key]['stage_id'] if d==key else d for d in stage['depends_on']], 'historical_slice':True}
                    stages.append(current)
                    current={**stage,'stage_id':identity+'__replacement_r'+str(number),'plan_id':opening['plan_id'],
                             'lines':opening['lines'],'depends_on':list(stage['depends_on']),'initial_plan_hash':opening['initial_plan_hash']}
                    closing_alias[identity]=current['stage_id']
                else:current={**current,'plan_id':opening['plan_id'],'lines':opening['lines'],'initial_plan_hash':opening['initial_plan_hash']}
        dependencies=list(current['depends_on'])
        for dep in list(dependencies):
            if dep in carry and carry[dep]['stage_id'] not in dependencies:dependencies.append(carry[dep]['stage_id'])
            if dep in closing_alias and closing_alias[dep] not in dependencies:dependencies.append(closing_alias[dep])
        stages.append({**current,'depends_on':dependencies})
    basis={'account_id':account_id,'parent_version':previous['parent_version'],'previous_group_id':previous['group_id'],'stages':stages}
    return {**({'unit_rebase':{'as_of':clock.isoformat(),'ledger_seq':book.sequence(account_id)}} if unit_mode else {}),'group_id':digest(basis),'group_basis':basis,'root_group_id':root_id,'revision':number,
            'previous_group_id':previous['group_id'],'hedge_id':previous['hedge_id'],'parent_version':previous['parent_version'],
            'parent_record_hash':previous['parent_record_hash'],'stages':stages,'as_of':clock.isoformat(),
            'basis_sequence':book.sequence(account_id),'executable':False,'creates_reservations':False,
            'meaning':'保留原成交切片，替换确切未成交计划引用；不释放预留、撤订单或授予逐阶段执行资格'}


def save(book,account_id,request,*,commit=False):
    from .groups import history as groups
    with publication_lock(book.path.parent),book.transaction():
        book._require_account(account_id)
        key=PREFIX+digest({'account_id':account_id,'request_id':request.get('request_id') if isinstance(request,dict) else None})
        old=book.connection.execute('SELECT details FROM tasks WHERE task_id=?',(key,)).fetchone()
        if old:
            value=json.loads(old[0]);groups(book,account_id)
            if value['request_hash']!=digest(request):raise QuantError('HEDGE_GROUP_REQUEST_CONFLICT','同修订请求不能更换输入')
            return value
        body=prepare(book,account_id,request)
        if not commit:return {'status':'PREVIEW',**body}
        value={'schema_version':2,'status':'BOUND','account_id':account_id,'environment':book.environment,
               'request':request,'request_hash':digest(request),'recorded_at':now_utc(),**body}
        value['record_hash']=digest(value)
        book.record_task(key,'BOUND',value)
        # Re-read proves the complete chain before committing the logical amendment.
        groups(book,account_id)
        return value
