"""Mandatory fresh stage checks for native plans bound to a hedge execution group."""
from ..common import QuantError,utc,digest,decimal as D
from .groups import history
from .group_revisions import heads
from .stage_assessment import analyze


def require_for_plan(book,account_id,kind,plan_id,action,as_of,request=None,*,state_as_of=None):
    groups=heads(history(book,account_id),as_of,book.sequence(account_id))
    matches=[(g,s) for g in groups for s in g['stages'] if s['plan_kind']==kind and s['plan_id']==plan_id
             and s['action']==action and not s.get('historical_slice')]
    if not matches:
        if request is not None:raise QuantError('UNBOUND_STAGE_CHECK','阶段请求不能绑定不属于当前组的计划')
        return {'status':'UNBOUND_NATIVE_PLAN','executable':False}
    if len(matches)!=1:raise QuantError('AMBIGUOUS_HEDGE_STAGE','原计划没有唯一当前执行阶段')
    group,stage=matches[0]
    if request is None:raise QuantError('HEDGE_STAGE_CHECK_REQUIRED','组内原计划激活/模拟须显式提供本次阶段检查请求')
    if (not isinstance(request,dict) or request.get('group_id')!=group['group_id']
            or request.get('stage_id')!=stage['stage_id']):
        raise QuantError('HEDGE_STAGE_PLAN_MISMATCH','检查必须属于本计划、本开平仓方向及当前组')
    result=analyze(book,account_id,request)
    if utc(result['as_of'])!=utc(state_as_of or as_of):raise QuantError('HEDGE_STAGE_TIME_MISMATCH','阶段风险时点须等于本次操作时点，不继承旧压力检查')
    if result['status']!='CHECKED':raise QuantError('HEDGE_STAGE_BLOCKED','阶段中间状态检查失败：'+','.join(result['checks']))
    if state_as_of is not None:
        from .archive import load
        risk=load(book.path.parent/'hedging/exposures',result['exposure_id'])
        replay=risk['request'].get('execution_replay',{})
        if (replay.get('plan_id')!=plan_id or replay.get('plan_kind')!=kind
                or utc(replay.get('processing_at',risk['as_of']))!=utc(as_of)
                or utc(risk['knowledge_cutoff'])>utc(as_of)):
            raise QuantError('HEDGE_REPLAY_TIME_MISMATCH','迟到阶段须原计划及本次实际处理知识截止')
        result['processing_as_of']=utc(as_of).isoformat()
        result['assessment_id']=digest({k:v for k,v in result.items() if k!='assessment_id'})
    return result


def validate_record(book,account_id,plan_id,action,request,assessment):
    """Validate frozen activation/simulation evidence without replaying it as a new operation."""
    if assessment.get('status')=='UNBOUND_NATIVE_PLAN':
        if request is not None:raise QuantError('CORRUPT_HEDGE_STAGE_AUDIT','无组计划不能保存阶段请求')
        return
    try:
        if (assessment['status']!='CHECKED' or assessment['account_id']!=account_id
                or assessment['environment']!=book.environment or assessment['stage_request']!=request
                or assessment['assessment_id']!=digest({k:v for k,v in assessment.items() if k!='assessment_id'})):
            raise ValueError('identity')
        groups=history(book,account_id)
        group=next(g for g in groups if g['group_id']==assessment['group_id'])
        stage=next(s for s in group['stages'] if s['stage_id']==assessment['group_stage_id'])
        if (group['record_hash']!=assessment['group_record_hash'] or stage['plan_id']!=plan_id or stage['action']!=action
                or request['group_id']!=group['group_id'] or request['stage_id']!=stage['stage_id']):raise ValueError('stage')
        from .archive import load
        risk=load(book.path.parent/'hedging/exposures',assessment['exposure_id'])
        if (risk['account_id']!=account_id or risk['ledger_seq']!=assessment['ledger_seq']
                or risk['as_of']!=assessment['as_of'] or request['exposure_id']!=risk['exposure_id']):raise ValueError('risk')
        from .stage_assessment import require_operation_risk
        require_operation_risk(risk,action)
        if action=='OPEN' and book.environment!='demo':
            from .greek_evidence import assess as assess_greek,assess_candidate
            from ..options.contracts import OptionContract
            provided={item['contract_version']:item for item in risk['request']['greeks']}
            frozen=risk.get('greek_qualification',{})
            for event in book.active_events(account_id,risk['as_of'],ledger_seq=risk['ledger_seq']):
                if event['symbol'] not in risk['account'].get('option_positions',{}):continue
                contract=OptionContract.from_dict(event['contract']);item=provided.get(contract.version_hash)
                if item is None or assess_greek(book,item,contract,risk['knowledge_cutoff'])!=frozen.get(event['symbol']):
                    raise ValueError('held Greek evidence')
            from .intents import records as parent_records
            parent=next(p for p in parent_records(book,account_id) if p['version_hash']==group['parent_version'])
            if assess_candidate(book,parent['candidate'],risk['knowledge_cutoff'])!=assessment.get('candidate_greek_assessment',{}):
                raise ValueError('candidate Greek evidence')
        if assessment.get('security_assessment') is not None:
            from .securities import assess
            original=assessment['security_assessment']
            if assess(book,account_id,original['request'])!=original:raise ValueError('security qualification')
        if assessment.get('permission_assessment') is not None:
            from ..options.permissions import assess as permissions
            original=assessment['permission_assessment']
            fields=('account_id','template_id','operation','as_of','contract_count','physical_cash','exit_days')
            if permissions(book,**{k:original[k] for k in fields})!=original:raise ValueError('account permissions')
        if assessment.get('processing_as_of') is not None:
            replay=risk['request'].get('execution_replay',{})
            if (replay.get('plan_id')!=plan_id or replay.get('processing_at') is None
                    or utc(replay['processing_at'])!=utc(assessment['processing_as_of'])
                    or utc(risk['knowledge_cutoff'])!=utc(assessment['processing_as_of'])):raise ValueError('replay clock')
        if assessment['option_snapshot_id']:
            from ..options.data import OptionDataStore
            OptionDataStore(book.path.parent/'options/chains').load(assessment['option_snapshot_id'])
        from .groups import progress
        view=progress(book,account_id,group,assessment['as_of'],ledger_seq=assessment['ledger_seq'])
        phase=next(s for s in view['stages'] if s['stage_id']==stage['stage_id'])
        if view['status']=='BLOCKED' or phase['remaining']!=assessment['remaining_quantities']:raise ValueError('remaining')
        # Financial balances are independently rebuilt at the frozen prefix; current reservations may legitimately differ.
        actual=book.snapshot(account_id,risk['as_of'],risk['account']['prices'],ledger_seq=risk['ledger_seq'])
        for key in ('settled_cash','receivables','payables','positions','option_positions','equity','net_contributions'):
            # V1 archives predate the option_positions field. An omitted field
            # means no options only if the independently rebuilt prefix is empty.
            neutral={} if key=='option_positions' else None
            if actual.get(key,neutral)!=risk['account'].get(key,neutral):raise ValueError('financial prefix')
        from copy import deepcopy
        from .groups import _plan
        from .stage_stress import evaluate
        projected=deepcopy(risk);cash=D(assessment['own_native_cash_reservation'])
        shares=assessment.get('own_native_share_reservation',{})
        if cash<0 or cash>D(risk['account']['reserved_cash']):raise ValueError('own cash reservation')
        if any(D(q)<0 or D(q)>D(risk['account'].get('reserved_positions',{}).get(s,0)) for s,q in shares.items()):
            raise ValueError('own share reservation')
        projected['account']['available_cash']=str(D(risk['account']['available_cash'])+cash)
        projected['account']['reserved_positions']={s:str(max(D(0),D(q)-D(shares.get(s,0))))
            for s,q in risk['account'].get('reserved_positions',{}).items()}
        terms={e['symbol']:e['contract'] for e in book.active_events(account_id,risk['as_of'],ledger_seq=risk['ledger_seq']) if e['kind'].startswith('OPTION_')}
        _,body,_=_plan(book,account_id,stage['plan_kind'],plan_id)
        if stage['plan_kind']=='option':terms.update({l['contract']['contract_id']:l['contract'] for l in body['selection']['legs']})
        quotes={}
        if assessment['option_snapshot_id']:
            from ..options.data import OptionDataStore
            _,rows,_,_=OptionDataStore(book.path.parent/'options/chains').load(assessment['option_snapshot_id'])
            symbols=set(risk['account'].get('option_positions',{}))|({l['symbol'] for l in stage['lines']} if stage['plan_kind']=='option' else set())
            for symbol in symbols:
                known=[r for r in rows if r['contract_id']==symbol and utc(r['exchange_timestamp'])<=utc(risk['as_of']) and all(utc(r[k])<=utc(risk['knowledge_cutoff']) for k in ('exchange_timestamp','available_at','received_at'))]
                quotes[symbol]=max(known,key=lambda r:utc(r['exchange_timestamp']))
        rebuilt=evaluate(projected,stage,phase['remaining'],terms,quotes,request['stress'])
        for key in ('vertices','checks','status','request'):
            if rebuilt[key]!=assessment[key]:raise ValueError('pressure calculation')
    except (KeyError,ValueError,TypeError,StopIteration) as exc:
        raise QuantError('CORRUPT_HEDGE_STAGE_AUDIT','原阶段检查、父组/风险/数量引用改变') from exc


def validate_cached(book,audit,action,*,proposal=False):
    """Exact retries return historical evidence only after validating that evidence."""
    request=audit['request'];body=audit['proposal'] if proposal else audit
    assessment=body.get('hedge_stage_check')
    if assessment is None:
        if request.get('hedge_stage_check') is not None:raise QuantError('CORRUPT_HEDGE_STAGE_AUDIT','原阶段审计丢失')
        return
    if assessment.get('status')=='CHECKED':
        decision_at=body['as_of'] if proposal else request.get('state_as_of',request['as_of'])
        sequence=body['ledger_seq'] if proposal else request['expected_sequence']
        if utc(decision_at)!=utc(assessment['as_of']) or sequence!=assessment['ledger_seq']:
            raise QuantError('CORRUPT_HEDGE_STAGE_AUDIT','原操作/阶段风险时点或财务前缀改变')
        if request.get('state_as_of') is not None:
            from .archive import load
            risk=load(book.path.parent/'hedging/exposures',assessment['exposure_id'])
            if (utc(request['as_of'])!=utc(assessment['processing_as_of'])
                    or (action=='CLOSE' and risk['request'].get('execution_replay',{}).get('exit_id')!=request['exit_id'])):
                raise QuantError('CORRUPT_HEDGE_STAGE_AUDIT','迟到操作处理时点或原退出ID改变')
    plan_id=request['review']['plan_id'] if proposal else audit['result']['plan_id'] if action=='CLOSE' else request['plan_id']
    owner=book.connection.execute('SELECT account_id FROM option_plans WHERE plan_id=?',(plan_id,)).fetchone()
    if owner is None:raise QuantError('CORRUPT_HEDGE_STAGE_AUDIT','原计划丢失')
    validate_record(book,owner[0],plan_id,action,request.get('hedge_stage_check'),assessment)
