"""Explicit current hedge-stage activation using the shared native stock ledger."""
import json
from ..common import QuantError, canonical, digest, decimal as D, now_utc, utc
from ..config import Config
from ..locks import publication_lock
from ..portfolio.reconciliation import ReconciliationRules
from .allocation_store import resources
from .archive import load
from .stage_gate import require_for_plan, validate_record
from .stock_plans import validate_references as validate_stock_drafts

PREFIX='hedge-stock-activation:'
FIELDS={'schema_version','request_id','plan_id','as_of','expected_resource_hash','hedge_stage_check'}


def save(book, account_id, request, *, commit=False):
    if (not isinstance(request,dict) or set(request)!=FIELDS
            or type(request['schema_version']) is not int or request['schema_version']!=1
            or not isinstance(request['hedge_stage_check'],dict)
            or any(not isinstance(request[k],str) or not request[k].strip() for k in FIELDS-{'schema_version','hedge_stage_check'})):
        raise QuantError('INVALID_HEDGE_STOCK_ACTIVATION','需草案、当前时点/资源及本次完整阶段检查')
    with publication_lock(book.path.parent),book.transaction():
        validate_stock_drafts(book)
        key=PREFIX+digest(dict(account_id=account_id,request_id=request['request_id']))
        previous=book.connection.execute('SELECT details FROM tasks WHERE task_id=?',(key,)).fetchone()
        if previous:
            audit=json.loads(previous[0])
            if audit['request_hash']!=digest(request):raise QuantError('HEDGE_STOCK_ACTIVATION_CONFLICT','同激活请求不能换条件')
            validate_audit(book,audit)
            return audit
        row=book.connection.execute('SELECT * FROM plans WHERE plan_id=? AND account_id=?',(request['plan_id'],account_id)).fetchone()
        if row is None:raise QuantError('UNKNOWN_PLAN','草案不属于该账户')
        body=json.loads(row['payload'])
        if body.get('purpose')!='hedge_stage' or row['execution_status']!='DRAFT' or row['manual_pending']:
            raise QuantError('NON_DRAFT_HEDGE_STOCK_PLAN','只能显式激活尚未使用的独立股票对冲草案')
        if resources(book,account_id)!=request['expected_resource_hash']:raise QuantError('STALE_HEDGE_RESOURCES','激活资源已变化')
        clock=utc(request['as_of'])
        if clock>utc(now_utc()) or clock<utc(body['as_of']) or clock>=utc(body['execution_deadline']):
            raise QuantError('LOOKAHEAD_EXECUTION','草案须在原假设成交时点前激活，不能补建过去计划')
        if book.environment!='demo' and clock<utc(body['created_at']):
            raise QuantError('LOOKAHEAD_EXECUTION','前向激活不能早于实际草案生成时间')
        config=Config.from_dict(body['execution_config']);config.validate();config.require_execution()
        action=body['hedge_context'].get('action','OPEN')
        stage=require_for_plan(book,account_id,'stock',request['plan_id'],action,request['as_of'],request['hedge_stage_check'])
        if stage['status']!='CHECKED':raise QuantError('HEDGE_STAGE_CHECK_REQUIRED','独立对冲草案必须先绑定执行组')
        from .monitor import require_planning,require_projected_coverage
        require_planning(book,account_id,request['as_of'],stage_check=stage)
        limits=request['hedge_stage_check']['stress']['limits']
        if (D(limits['stock_cost_bps'])!=D(config.commission_bps)+D(config.slippage_bps)
                or D(limits['adverse_slippage_fraction'])!=0 or D(config.fixed_fee)!=0):
            raise QuantError('HEDGE_COST_ASSUMPTION_MISMATCH','阶段股票成本须与冻结配置一致；当前端点不支持固定逐笔费')
        book.check_reconciliation(account_id,request['as_of'],config.reconciliation_max_days,
                                  rules_hash=ReconciliationRules.from_config(config).hash)
        risk=load(book.path.parent/'hedging/exposures',stage['exposure_id']);snapshot=risk['account']
        if action=='CLOSE':
            from .groups import history
            group=next(g for g in history(book,account_id) if g['group_id']==stage['group_id'])
            node=next(s for s in group['stages'] if s['stage_id']==stage['group_stage_id'])
            allowed_openings={s['plan_id'] for s in group['stages'] if s['stage_id'] in node['depends_on'] and s['plan_kind']=='stock' and s['action']=='OPEN'}
            changes=[e for e in book.active_events(account_id,request['as_of']) if e['seq']>body['snapshot']['ledger_seq']]
            if any(e['kind'] not in {'FEE','DIVIDEND_ACCRUAL','DIVIDEND_PAYMENT'}
                    and (e['plan_id'] not in allowed_openings or e['kind'] not in {'BUY','SELL'}) for e in changes):
                raise QuantError('ACCOUNT_CHANGED','退出冻结后只有原OPEN财务推进可以沿用，其他变更须明确重规划')
        elif snapshot['ledger_seq']!=body['snapshot']['ledger_seq']:
            raise QuantError('ACCOUNT_CHANGED','草案后财务改变，须明确修订，不能直接激活旧数量')
        positions={s:D(q) for s,q in snapshot['positions'].items()};reserve=D(0);fees=D(0);shares={}
        for line in body['sizing']['lines']:
            s=line['symbol'];q=D(line['quantity']);p=D(line['price']);fee=D(line['estimated_fee']);fees+=fee
            if D(risk['valuation']['prices'].get(s,0))!=p:raise QuantError('HEDGE_PRICE_BASIS_CHANGED','激活原价已变，须明确修订')
            if line['side']=='BUY':reserve+=q*p+fee;positions[s]=positions.get(s,D(0))+q
            else:
                if q>positions.get(s,D(0))-D(snapshot.get('reserved_positions',{}).get(s,0)):
                    raise QuantError('INSUFFICIENT_POSITION','不能重复占用其他计划预留股份')
                shares[s]=str(q);positions[s]=positions.get(s,D(0))-q
        equity=D(snapshot['equity'])-fees
        budget=max(D(0),D(snapshot['available_cash'])-D(snapshot['equity'])*D(config.cash_buffer))
        if reserve>budget:
            raise QuantError('INSUFFICIENT_CASH','激活不能使用尚未到账卖出款')
        if equity<=0 or any(q*D(snapshot['prices'][s])/equity>D(config.max_weight) for s,q in positions.items()):
            raise QuantError('PROJECTED_WEIGHT_LIMIT','冻结股票数量超出显式预计仓位上限')
        projection=require_projected_coverage(book,account_id,request['as_of'],{s:str(q) for s,q in positions.items()},stage_check=stage)
        result=dict(schema_version=1,status='READY' if commit else 'PREVIEW',account_id=account_id,
                    plan_id=request['plan_id'],request=request,request_hash=digest(request),stage_assessment=stage,
                    reserved_cash=str(reserve),reserved_positions=shares,projection=projection,
                    executable=commit,recorded_at=now_utc())
        if not commit:return result
        body['checks']=[dict(code='PASSED',message='当前阶段、资金、股份及冻结数量检查通过')]
        body['intent_status']='OPEN';body['hedge_activation_task']=key
        body['execution_basis_sequence']=snapshot['ledger_seq']
        book.connection.execute("UPDATE plans SET execution_status='READY',check_status='PASSED',payload=?,reserved_cash=?,reserved_positions=? WHERE plan_id=?",
            (canonical(body),str(reserve),canonical(shares),request['plan_id']))
        result['record_hash']=digest(result);book.record_task(key,'READY',result)
        return result


def validate_audit(book,audit):
    if audit['record_hash']!=digest({k:v for k,v in audit.items() if k!='record_hash'}) or audit['request_hash']!=digest(audit['request']):
        raise QuantError('CORRUPT_HEDGE_STOCK_ACTIVATION','原激活审计改变')
    row=book.connection.execute('SELECT payload,account_id FROM plans WHERE plan_id=?',(audit['plan_id'],)).fetchone()
    if row is None or row['account_id']!=audit['account_id']:
        raise QuantError('CORRUPT_HEDGE_STOCK_ACTIVATION','原激活计划归属丢失')
    body=json.loads(row['payload']);reserve=D(0);shares={}
    action=body['hedge_context'].get('action','OPEN')
    validate_record(book,audit['account_id'],audit['plan_id'],action,audit['request']['hedge_stage_check'],audit['stage_assessment'])
    if body.get('execution_basis_sequence',body['snapshot']['ledger_seq'])!=audit['stage_assessment']['ledger_seq']:
        raise QuantError('CORRUPT_HEDGE_STOCK_ACTIVATION','原激活执行前缀改变')
    for line in body['sizing']['lines']:
        if line['side']=='BUY':reserve+=D(line['quantity'])*D(line['price'])+D(line['estimated_fee'])
        else:shares[line['symbol']]=str(D(line['quantity']))
    if (D(audit['reserved_cash'])!=reserve or audit['reserved_positions']!=shares or audit['status']!='READY'
            or body.get('hedge_activation_task')!=PREFIX+digest(dict(account_id=audit['account_id'],request_id=audit['request']['request_id']))):
        raise QuantError('CORRUPT_HEDGE_STOCK_ACTIVATION','原激活预留与冻结数量不一致')


def validate_references(book):
    for row in book.connection.execute('SELECT task_id,details FROM tasks WHERE task_id LIKE ?',(PREFIX+'%',)):
        audit=json.loads(row['details'])
        if row['task_id']!=PREFIX+digest(dict(account_id=audit['account_id'],request_id=audit['request']['request_id'])):
            raise QuantError('CORRUPT_HEDGE_STOCK_ACTIVATION','原激活身份改变')
        validate_audit(book,audit)
