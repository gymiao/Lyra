"""Current hedge monitoring shared by daily jobs, plan gates and the dashboard."""
from ..common import QuantError, digest, now_utc, utc
from ..locks import publication_lock
from .intents import records
from .intent_actions import history as closures
from .groups import history as groups, progress
from .allocation_store import latest
from .coverage_service import account_coverage


def monitor(book,account_id,as_of):
    with publication_lock(book.path.parent),book.transaction():
        book._require_account(account_id)
        clock=utc(as_of);checks=[]
        if clock>utc(now_utc()):raise QuantError('FUTURE_HEDGE_MONITOR','不能报告未来对冲状态')
        try:
            from .stock_plans import validate_references as validate_stock_drafts
            from .stock_activation import validate_references as validate_stock_activations
            from .stock_simulation_audit import validate_references as validate_stock_simulations
            validate_stock_drafts(book);validate_stock_activations(book);validate_stock_simulations(book)
            from ..options.incidents import status as incident_status
            incidents=incident_status(book,account_id,clock)
            for item in incidents['incidents']:
                if item['status']=='OPEN':
                    checks.append({'code':'OPTION_INCIDENT_REVIEW_REQUIRED','message':'中间期权凭据异常尚未核实：'+item['incident_id']})
            from .intents import validate_references
            validate_references(book.path.parent,book)
            originals=records(book,account_id);closed=closures(book,account_id)
            from .group_revisions import heads as group_heads
            group_archive=groups(book,account_id)
            definitions=group_heads(group_archive,clock,book.sequence(account_id));allocation=latest(book,account_id)
            heads={}
            for r in originals:
                if r['hedge_id'] not in heads or r['revision']>heads[r['hedge_id']]['revision']:heads[r['hedge_id']]=r
            views=[progress(book,account_id,g,clock) for g in definitions]
            for view in views:
                if view['status']=='BLOCKED':
                    checks.append({'code':'HEDGE_GROUP_BLOCKED','group_id':view['group_id'],
                        'message':'执行组存在原计划变化、时序违规或未解决成交差异'})
                if any(s['manual_pending'] for s in view['stages']):
                    checks.append({'code':'HEDGE_MANUAL_PENDING','group_id':view['group_id'],
                        'message':'人工在途尚未结束，保留原占用并暂停新增基础计划'})
            closed_ids={r['hedge_id'] for r in closed}
            parent_views=[]
            for r in heads.values():
                selected=r['hedge_id'] not in closed_ids and utc(r['decision_at'])<=clock<utc(r['valid_until'])
                attached=[v for g,v in zip(definitions,views) if g['parent_version']==r['version_hash']]
                if selected and r['timing']=='forward':
                    if not attached or any(v['status']!='COMPLETE' for v in attached):
                        checks.append({'code':'HEDGE_FORWARD_INTENT_PENDING','hedge_id':r['hedge_id'],
                            'message':'有效前向父决定尚未完成分阶段复核/执行；暂停独立基础调仓'})
                parent_views.append({'hedge_id':r['hedge_id'],'parent_version':r['version_hash'],
                    'timing':r['timing'],'decision_at':r['decision_at'],'valid_until':r['valid_until'],
                    'generated_at':r['generated_at'],'scope':r['scope'],'exposure_id':r['exposure_id'],
                    'status':'CLOSED' if r['hedge_id'] in closed_ids else 'CURRENT_RESEARCH' if selected else 'ARCHIVED_RESEARCH',
                    'executable':False})
            current=None
            if allocation:
                query={**allocation['coverage_request'],'as_of':clock.isoformat(),
                    'knowledge_cutoff':now_utc() if book.environment=='demo' else clock.isoformat(),
                    'ledger_seq':book.sequence(account_id),'allocations':allocation['allocations']}
                try:current=account_coverage(book,account_id,query)
                except QuantError as exc:
                    checks.append({'code':exc.code,'message':'当前保护覆盖无法核实：'+str(exc)})
            state=book.snapshot(account_id,clock)
            for issue in state['anomalies']:
                checks.append({'code':'HEDGE_ACCOUNT_ANOMALY','message':issue})
            events=book.active_events(account_id,clock)
            terms={e['symbol']:e['contract'] for e in events if e['kind'].startswith('OPTION_')}
            for symbol,q in state.get('option_positions',{}).items():
                if symbol in terms and utc(terms[symbol]['exercise_cutoff_at'])<clock:
                    checks.append({'code':'HEDGE_EXPIRED_POSITION_UNRESOLVED','symbol':symbol,
                        'message':'到期后仍有期权头寸，需导入实际生命周期凭据，不能按零价值清除'})
            body={'artifact_type':'hedge_monitor','account_id':account_id,'environment':book.environment,
                  'as_of':clock.isoformat(),'ledger_seq':book.sequence(account_id),
                  'data_type':'synthetic_or_reconstructed_research' if book.environment=='demo' else 'account_record_monitor',
                  'status':'BLOCKED' if checks else 'SUCCESS' if originals or definitions or allocation else 'NO_ACTION',
                  'parents':parent_views,'closures':closed,'groups':definitions,'group_archive':group_archive,'progress':views,'option_incidents':incidents,
                  'allocation_archive':allocation,'current_coverage':current,'checks':checks,
                  'executable':False,'creates_reservations':False,
                  'meaning':'原研究决定与当前财务事实分开展示；不替代报价、Greek、来源或逐阶段压力资格'}
        except (QuantError,OSError,ValueError,KeyError,TypeError) as exc:
            body={'artifact_type':'hedge_monitor','account_id':account_id,'environment':book.environment,
                  'as_of':clock.isoformat(),'ledger_seq':book.sequence(account_id),'status':'BLOCKED',
                  'parents':[],'closures':[],'groups':[],'group_archive':[],'progress':[],'allocation_archive':None,'current_coverage':None,
                  'checks':[{'code':exc.code if isinstance(exc,QuantError) else 'HEDGE_REFERENCES_UNAVAILABLE','message':str(exc)}],
                  'executable':False,'creates_reservations':False,
                  'meaning':'原对冲引用损坏或不可读；保留事实，暂停新计划'}
        body['monitor_id']=digest(body)
        return body


def require_planning(book,account_id,as_of,*,stage_check=None):
    result=monitor(book,account_id,as_of)
    checks=result['checks']
    if stage_check and stage_check.get('status')=='CHECKED' and stage_check.get('account_id')==account_id and (
            stage_check.get('ledger_seq')==book.sequence(account_id) and (utc(stage_check['as_of'])==utc(as_of) or (stage_check.get('processing_as_of')==utc(as_of).isoformat() and utc(stage_check['as_of'])<=utc(as_of)))
            and stage_check.get('assessment_id')==digest({k:v for k,v in stage_check.items() if k!='assessment_id'})):
        own=[g for g in result['groups'] if g['group_id']==stage_check.get('group_id')
             and g['record_hash']==stage_check.get('group_record_hash')]
        if len(own)==1:
            checks=[c for c in checks if not (c['code']=='HEDGE_FORWARD_INTENT_PENDING' and c.get('hedge_id')==own[0]['hedge_id'])]
    if checks:
        raise QuantError('HEDGE_MONITOR_BLOCKED','；'.join(c['code']+':'+c['message'] for c in checks))
    return result


def require_projected_coverage(book,account_id,as_of,positions,*,stage_check=None):
    """Do not turn still-active share slices into uncovered references by trading stock."""
    from ..common import decimal as D
    with publication_lock(book.path.parent),book.transaction():
        current=require_planning(book,account_id,as_of,stage_check=stage_check)
        existing=book.snapshot(account_id,as_of)['positions']
        if (not isinstance(positions,dict) or not set(existing)<=set(positions)
                or any(not isinstance(k,str) or not k for k in positions)):
            raise QuantError('INVALID_PROJECTED_POSITIONS','预测持仓须完整包含所有现有股票，清仓须显式数量0')
        projected={k:D(v) for k,v in positions.items()}
        if any(q<0 for q in projected.values()):
            raise QuantError('UNSUPPORTED_PROJECTED_SHORT','预测股票持仓不能为负')
        coverage=current['current_coverage'];archive=current['allocation_archive']
        required={};checks=[]
        if coverage and archive:
            active=set(coverage['active_allocations'])
            mapping=coverage['security_ids']
            symbols={identity:symbol for symbol,identity in mapping.items()}
            for row in archive['allocations']:
                if row['allocation_id'] not in active:continue
                symbol=symbols[row['security_id']]
                required[symbol]=max(required.get(symbol,D(0)),D(row['share_end']))
                if projected.get(symbol,D(0))<D(row['share_end']):
                    checks.append({'allocation_id':row['allocation_id'],'symbol':symbol,
                        'required_shares':str(row['share_end']),'projected_shares':str(projected.get(symbol,D(0)))})
        if checks:
            raise QuantError('HEDGE_PROJECTED_COVERAGE','预测股份不足以保留已分配保护/覆盖；先核对期权退出及显式引用修订：'+str(checks))
        return {'status':'CHECKED','account_id':account_id,'as_of':utc(as_of).isoformat(),
                'ledger_seq':book.sequence(account_id),'required_shares':{k:str(v) for k,v in required.items()},
                'projected_positions':{k:str(v) for k,v in projected.items()},'creates_reservations':False,
                'meaning':'仅核对当前有效股数切片的预测覆盖，不替代完整报价/现金/压力资格'}


