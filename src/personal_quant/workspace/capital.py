"""Read-only strategy capital and share claims against a single ledger view."""
from ..common import QuantError,decimal as D,digest,utc
from ..portfolio import Ledger
from .service import read_workspace

COMPONENTS={'premium','collateral','fees','buffer'}


def _basis(book,account_id,as_of,prices):
    state=book.snapshot(account_id,as_of,prices)
    plans={}
    for table in ('plans','option_plans'):
        if book.connection.execute('SELECT 1 FROM sqlite_master WHERE name=?',(table,)).fetchone():
            plans[table]=[dict(r) for r in book.connection.execute('SELECT * FROM '+table+' WHERE account_id=?',(account_id,))]
    reconciliations=[dict(r) for r in book.connection.execute('SELECT * FROM reconciliations WHERE account_id=?',(account_id,))]
    return state,digest({'state':state,'plans':plans,'reconciliations':reconciliations})


def preview(directory,request):
    fields={'schema_version','account_id','as_of','prices','allocations'}
    if not isinstance(request,dict) or set(request)!=fields or type(request['schema_version']) is not int or request['schema_version']!=1:
        raise QuantError('INVALID_CAPITAL_PREVIEW','需要schema1、账户、同一估值时点、价格与策略分配')
    root,identity,config,_=read_workspace(directory)
    if request['account_id']!=identity['account_id']:raise QuantError('WORKSPACE_ACCOUNT_MISMATCH','预演账户必须是工作区账户')
    utc(request['as_of'])
    if not isinstance(request['prices'],dict) or any(not isinstance(k,str) or not k or D(v)<=0 for k,v in request['prices'].items()):
        raise QuantError('INVALID_CAPITAL_PREVIEW','价格映射需明确标的及正值，不将缺价记成零')
    allocations=request['allocations']
    if not isinstance(allocations,list) or not 1<=len(allocations)<=20:
        raise QuantError('INVALID_CAPITAL_PREVIEW','需1至20项显式策略预算，不自动分配资金')
    rows=[];seen=set();cash=D(0);shares={}
    for row in allocations:
        if (not isinstance(row,dict) or set(row)!={'strategy_id','cash_budget','requirements','coverage_shares'}
                or not isinstance(row['strategy_id'],str) or not row['strategy_id'] or row['strategy_id'] in seen
                or not isinstance(row['requirements'],dict) or set(row['requirements'])!=COMPONENTS
                or not isinstance(row['coverage_shares'],dict)):
            raise QuantError('INVALID_CAPITAL_PREVIEW','策略ID需唯一，预算分解和覆盖数量必须完整')
        seen.add(row['strategy_id']);budget=D(row['cash_budget']);required={k:D(v) for k,v in row['requirements'].items()}
        claimed={k:D(v) for k,v in row['coverage_shares'].items()}
        if budget<0 or any(v<0 for v in [*required.values(),*claimed.values()]) or any(not isinstance(k,str) or not k for k in claimed):
            raise QuantError('INVALID_CAPITAL_PREVIEW','预算、费用、担保和股份数量不能为负或非有限')
        issues=[]
        if sum(required.values())>budget:issues.append('STRATEGY_REQUIREMENT_EXCEEDS_BUDGET')
        cash+=budget
        for key,value in claimed.items():shares[key]=shares.get(key,D(0))+value
        rows.append({**row,'requirements':{k:str(v) for k,v in required.items()},'cash_budget':str(budget),
                     'coverage_shares':{k:str(v) for k,v in claimed.items()},'checks':issues})
    book=Ledger.read_only(root/config.runtime_dir/'account.sqlite','demo')
    try:
        state,basis=_basis(book,request['account_id'],request['as_of'],request['prices'])
        checks=list(state['anomalies']);available=D(state['available_cash'])
        if state['equity'] is None:checks.append('INCOMPLETE_VALUATION')
        if cash>available:checks.append('SHARED_CASH_EXCEEDED')
        free_shares={key:max(D(0),D(value)-D(state['reserved_positions'].get(key,0))) for key,value in state['positions'].items()}
        for key,value in shares.items():
            if value>free_shares.get(key,D(0)):checks.append('SHARED_COVERAGE_EXCEEDED:'+key)
        checks.extend(code for row in rows for code in row['checks'])
        unresolved=book.connection.execute('SELECT status FROM reconciliations WHERE account_id=? ORDER BY id DESC LIMIT 1',(request['account_id'],)).fetchone()
        if unresolved and unresolved[0]=='DIFFERENCES':checks.append('UNRESOLVED_RECONCILIATION')
        body={'schema_version':1,'status':'PREVIEW_ONLY','check_status':'BLOCKED' if checks else 'PASSED',
              'account_id':request['account_id'],'as_of':request['as_of'],'currency':config.currency,'request_hash':digest(request),
              'basis_hash':basis,'ledger_seq':state['ledger_seq'],'allocations':rows,'checks':checks,
              'available_cash':str(available),'allocated_cash':str(cash),'unallocated_cash':str(available-cash),
              'available_shares':{k:str(v) for k,v in free_shares.items()},'claimed_shares':{k:str(v) for k,v in shares.items()},
              'financial_events_added':0,'creates_reservations':False,'executable':False,
              'meaning':'显式假设的预算/覆盖预演，不验证策略收益或授予执行资格；状态改变后需重新预演'}
        body['preview_id']=digest(body);return body
    finally:book.close()


def validate(directory,request,result):
    # A new read view catches cash, positions AND reservation changes without a fill.
    current=preview(directory,request)
    return {'status':'CURRENT' if current['basis_hash']==result.get('basis_hash') and current['request_hash']==result.get('request_hash') else 'STALE',
            'executable':False,'financial_events_added':0,'current_preview':current}
