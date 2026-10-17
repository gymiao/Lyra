"""Current immutable group and ledger basis for read-only intermediate stress checks."""
from copy import deepcopy
from ..common import QuantError,digest,utc,decimal as D
from ..locks import publication_lock
from ..options.data import OptionDataStore,quality
from ..options.contracts import OptionContract
from ..options.source import assess_source
from ..options.valuation import LIMITS
from .archive import load
from .allocation_store import resources
from .groups import history,progress,_plan
from .group_revisions import heads
from .stage_stress import evaluate

FIELDS={'group_id','expected_group_hash','expected_resource_hash','stage_id','exposure_id',
        'option_snapshot_id','quote_limits','stress'}


def require_operation_risk(risk,action):
    if (action=='OPEN' and risk.get('environment')!='demo' and risk['account'].get('option_positions')):
        qualified=risk.get('greek_qualification')
        if (not isinstance(qualified,dict) or any(
                not isinstance(qualified.get(symbol),dict) or qualified[symbol].get('status')!='QUALIFIED'
                for symbol in risk['account']['option_positions'])):
            raise QuantError('GREEK_QUALIFICATION_REQUIRED','以期权Delta决定新增对冲须独立核验逐笔Greek来源；必要退出另查估值和情景')
    if risk['status']=='COMPLETE':return
    # Closing a frozen obligation can use direct price scenarios without portfolio Beta/Delta.
    # All valuation and financial facts remain mandatory; unknown checks fail closed.
    model_codes={'INSUFFICIENT_COMMON_PRICES','INCOMPLETE_COMMON_PRICES','ZERO_BENCHMARK_VARIANCE',
        'NONTRADABLE_RISK_PRICE','BETA_R2_BELOW_LIMIT','BETA_STANDARD_ERROR_ABOVE_LIMIT',
        'STOCK_BETA_REQUIRED','OPTION_DELTA_REQUIRED','OPTION_UNDERLYING_RISK_REQUIRED',
        'HEDGE_GREEK_TIME_MISMATCH','INVALID_HEDGE_GREEK','MODEL_INPUT_REQUIRED','MODEL_GREEK_PRICE_MISMATCH'}
    if (action!='CLOSE' or not risk.get('checks') or any(c.split(':',1)[0] not in model_codes for c in risk['checks'])
            or risk['valuation']['status'] not in {'COMPLETE','CASH_ONLY'}
            or risk['account'].get('equity') is None or risk['account'].get('missing_prices') or risk['account'].get('anomalies')
            or risk['account'].get('option_positions') and (risk.get('option_valuation') or {}).get('status')!='COMPLETE'):
        raise QuantError('INCOMPLETE_HEDGE_EXPOSURE','本操作需完整估值和账务；新增对冲还需完整风险模型')


def analyze(book,account_id,request):
    if (not isinstance(request,dict) or set(request)!=FIELDS or not isinstance(request['quote_limits'],dict)
            or set(request['quote_limits'])!=LIMITS|{'max_underlying_price_fraction'}
            or any(D(v)<0 for v in request['quote_limits'].values())):
        raise QuantError('INVALID_STAGE_ASSESSMENT','需确切组/阶段/风险/资源版本及当前报价和完整压力参数')
    with publication_lock(book.path.parent),book.transaction():
        risk=load(book.path.parent/'hedging/exposures',request['exposure_id'])
        if risk['account_id']!=account_id or risk['environment']!=book.environment or risk['ledger_seq']!=book.sequence(account_id):
            raise QuantError('STALE_LEDGER_SEQUENCE','阶段检查须同账户当前风险前缀')
        basis=digest([dict(r) for r in book.connection.execute(
            'SELECT seq,event_id,content_hash,effective_at,recorded_at,payload FROM events WHERE account_id=? AND seq<=? ORDER BY seq',
            (account_id,risk['ledger_seq']))])
        if basis!=risk['ledger_basis_hash']:raise QuantError('CORRUPT_EXPOSURE_ARCHIVE','原风险账本前缀改变')
        if resources(book,account_id)!=request['expected_resource_hash']:raise QuantError('STALE_HEDGE_RESOURCES','阶段资源已变化')
        current=book.snapshot(account_id,risk['as_of'],risk['account']['prices'],ledger_seq=risk['ledger_seq'])
        if current!=risk['account']:raise QuantError('STALE_STAGE_ACCOUNT','风险归档之后预留或账户状态变化，需重新冻结风险')
        group=next((g for g in heads(history(book,account_id),risk['as_of'],risk['ledger_seq']) if g['group_id']==request['group_id']),None)
        if group is None or group['record_hash']!=request['expected_group_hash']:raise QuantError('STALE_HEDGE_GROUP','阶段检查需当前组版本')
        from .intents import records as parents
        from .intent_actions import history as closures
        parent=next(p for p in parents(book,account_id) if p['version_hash']==group['parent_version'])
        stage=next((s for s in group['stages'] if s['stage_id']==request['stage_id']),None)
        if stage is None or stage.get('historical_slice'):raise QuantError('INVALID_HEDGE_STAGE','历史成交切片不能成为新增交易阶段')
        require_operation_risk(risk,stage['action'])
        if stage['action']=='OPEN' and (not utc(parent['decision_at'])<=utc(risk['as_of'])<=utc(parent['valid_until'])
                or any(c['hedge_id']==parent['hedge_id'] for c in closures(book,account_id))):
            raise QuantError('HEDGE_INTENT_CLOSED','新增阶段须仍在未关闭父意图窗口')
        view=progress(book,account_id,group,risk['as_of']);state=next(s for s in view['stages'] if s['stage_id']==stage['stage_id'])
        if view['status']=='BLOCKED' or state['manual_pending'] or state['unmet_dependencies']:
            raise QuantError('UNRESOLVED_HEDGE_EXECUTION','阶段有历史异常、人工在途或未完成结算依赖')
        row,body,_=_plan(book,account_id,stage['plan_kind'],stage['plan_id'])
        terms={e['symbol']:e['contract'] for e in book.active_events(account_id,risk['as_of'],ledger_seq=risk['ledger_seq']) if e['kind'].startswith('OPTION_')}
        if stage['plan_kind']=='option':terms.update({l['contract']['contract_id']:l['contract'] for l in body['selection']['legs']})
        security_assessment=None;permission_assessment=None;candidate_greek_assessment=None
        if book.environment!='demo':
            if stage['action']=='OPEN':
                from .greek_evidence import assess_candidate
                candidate_greek_assessment=assess_candidate(book,parent['candidate'],risk['knowledge_cutoff'])
                if any(item['status']!='QUALIFIED' for item in candidate_greek_assessment.values()):
                    raise QuantError('GREEK_QUALIFICATION_REQUIRED','Beta目标候选的逐腿Delta尚无合格供应商凭据')
            from .securities import assess
            parent_request=parent['request'];versions={**parent_request['security_versions'],**parent_request.get('tool_security_versions',{})}
            mapping={**parent_request['security_ids'],**parent_request.get('tool_security_ids',{})}
            required_securities=set(current['positions'])|{c['underlying'] for c in terms.values()}|({l['symbol'] for l in stage['lines']} if stage['plan_kind']=='stock' else set())
            if not required_securities<=set(versions):
                raise QuantError('SECURITY_BINDING_REQUIRED','阶段全部持仓及交易工具须有明确证券身份，不借用保护范围身份')
            security_assessment=assess(book,account_id,dict(security_versions=versions,security_ids=mapping,
                as_of=risk['as_of'],knowledge_cutoff=risk['knowledge_cutoff'],valuation_snapshot_id=risk['valuation_snapshot_id'],ledger_seq=risk['ledger_seq']))
            if security_assessment['status']!='QUALIFIED':
                raise QuantError('SECURITY_QUALIFICATION_REQUIRED',','.join(security_assessment['checks']))
            if stage['plan_kind']=='option':
                from ..options.permissions import assess as assess_permissions
                count=sum(int(D(q)) for q in state['remaining'].values())
                physical=sum((D(terms[l['symbol']]['exercise_cash'])*D(state['remaining'][str((l['symbol'],l['contract_version'],l['side']))])
                    for l in stage['lines'] if (terms[l['symbol']]['right']=='CALL' and l['side']=='BUY')
                        or (terms[l['symbol']]['right']=='PUT' and l['side']=='SELL')),D(0)) if stage['action']=='OPEN' else D(0)
                permission_assessment=assess_permissions(book,account_id,body['selection']['template_id'],stage['action'],
                    risk['knowledge_cutoff'],contract_count=count,physical_cash=physical,exit_days=body['selection']['exit_days_before_expiry'])
                if permission_assessment['status']!='QUALIFIED':
                    raise QuantError('ACCOUNT_OPTION_PERMISSIONS_REQUIRED',','.join(permission_assessment['checks']))
        quotes={};assessment=None;checks=[]
        required=set(risk['account'].get('option_positions',{}))|({l['symbol'] for l in stage['lines']} if stage['plan_kind']=='option' else set())
        if required:
            from ..data.store import DataStore
            _,_,calendar=DataStore(book.path.parent/'data').load(risk['valuation_snapshot_id'])
            contracts,records,metadata,_=OptionDataStore(book.path.parent/'options/chains').load(request['option_snapshot_id'])
            assessment=assess_source(book,metadata,[OptionContract.from_dict(terms[s]) for s in required],risk['knowledge_cutoff'])
            checks.extend(assessment['checks']);limits=request['quote_limits']
            for symbol in required:
                c=OptionContract.from_dict(terms[symbol])
                if symbol not in contracts or contracts[symbol].version_hash!=c.version_hash:raise QuantError('OPTION_UNIT_CONFLICT','当前条款版本不匹配')
                rows=[r for r in records if r['contract_id']==symbol and utc(r['exchange_timestamp'])<=utc(risk['as_of']) and all(utc(r[k])<=utc(risk['knowledge_cutoff']) for k in ('exchange_timestamp','available_at','received_at'))]
                if not rows:raise QuantError('MISSING_CURRENT_QUOTE','阶段每腿需当时已可用报价')
                q=max(rows,key=lambda r:utc(r['exchange_timestamp']));quotes[symbol]=q
                checks.extend(quality(q,c,risk['as_of'],max_age_seconds=float(limits['max_age_seconds']),
                    max_underlying_skew_seconds=float(limits['max_underlying_skew_seconds']),max_spread_fraction=limits['max_spread_fraction'],knowledge_cutoff=max(utc(risk['knowledge_cutoff']),utc(risk['as_of']))))
                raw=risk['valuation']['prices'].get(c.underlying)
                if raw is None or abs(D(q['underlying_price'])/D(raw)-1)>D(limits['max_underlying_price_fraction']):checks.append('HEDGE_UNDERLYING_PRICE_MISMATCH')
                session=risk['valuation']['quotes'].get(c.underlying,{}).get('session')
                if session is None or abs((utc(q['underlying_timestamp'])-utc(calendar.close(session))).total_seconds())>float(risk['request']['max_mark_skew_seconds']):
                    checks.append('HEDGE_UNDERLYING_TIME_MISMATCH')
            if len(quotes)>1 and (max(utc(q['exchange_timestamp']) for q in quotes.values())-min(utc(q['exchange_timestamp']) for q in quotes.values())).total_seconds()>float(limits['max_leg_skew_seconds']):checks.append('CURRENT_LEG_TIME_MISMATCH')
        if checks:raise QuantError('UNQUALIFIED_STAGE_QUOTES',','.join(sorted(set(checks))))
        projected=deepcopy(risk)
        # Reuse this stage's own native reservation, without releasing it or borrowing another plan's resources.
        own_cash=D(row['reserved_cash']);own_shares={}
        if stage['plan_kind']=='option':
            from ..options.lifecycle import review
            active=review(book,stage['plan_id'],risk['as_of']).get('active_reservation',{})
            own_cash=D(active.get('reserved_cash',0));own_shares=active.get('reserved_positions',{})
        else:
            import json
            own_shares=json.loads(row['reserved_positions'])
        projected['account']['available_cash']=str(D(current['available_cash'])+own_cash)
        projected['account']['reserved_positions']={s:str(max(D(0),D(q)-D(own_shares.get(s,0))))
            for s,q in current.get('reserved_positions',{}).items()}
        result=evaluate(projected,stage,state['remaining'],terms,quotes,request['stress'])
        from ..strategies.archive import source_fingerprint
        result.update(stage_request=request,source_fingerprint=source_fingerprint(),knowledge_cutoff=risk['knowledge_cutoff'],
                      remaining_quantities=state['remaining'],account_id=account_id,environment=book.environment,group_id=group['group_id'],group_record_hash=group['record_hash'],resource_hash=request['expected_resource_hash'],
                      source_assessment=assessment,security_assessment=security_assessment,permission_assessment=permission_assessment,
                      candidate_greek_assessment=candidate_greek_assessment,option_snapshot_id=request['option_snapshot_id'],
                      own_native_cash_reservation=str(own_cash),own_native_share_reservation=own_shares,execution_qualification='NOT_GRANTED')
        result['assessment_id']=digest({k:v for k,v in result.items() if k!='assessment_id'})
        return result
