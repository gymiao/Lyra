"""Monthly Wheel decisions derive phases from recorded account facts only."""
import json
from ..common import QuantError,decimal as D,digest,utc
from .contracts import OptionContract

VERSION='wheel-account-state/1.0.0'


def decision(book,account_id,as_of,parameters):
    if not isinstance(parameters,dict) or set(parameters)!={'underlying','packages','cash_buffer'}:
        raise QuantError('INVALID_WHEEL_PARAMETERS','Wheel需显式标的、目标包数及现金缓冲')
    symbol=parameters['underlying'];packages=parameters['packages'];buffer=D(parameters['cash_buffer'])
    if not isinstance(symbol,str) or not symbol or type(packages) is not int or not 1<=packages<=100 or buffer<0:
        raise QuantError('INVALID_WHEEL_PARAMETERS','标的、整包数量或现金缓冲无效')
    state=book.snapshot(account_id,as_of);issues=list(state['anomalies']);options=[]
    for identity,quantity in state.get('option_positions',{}).items():
        events=[event for event in book.active_events(account_id,as_of) if event.get('symbol')==identity and event.get('contract_version')]
        body=book.connection.execute('SELECT payload FROM option_contracts WHERE version_hash=?',(events[-1]['contract_version'],)).fetchone()
        contract=OptionContract.from_dict(json.loads(body[0]))
        if contract.underlying!=symbol:issues.append('UNRELATED_OPTION_POSITION')
        if D(quantity)>0:issues.append('UNEXPECTED_LONG_OPTION')
        options.append((contract.right,D(quantity)))
    positions={s:D(q) for s,q in state['positions'].items() if D(q)}
    if set(positions)-{symbol}:issues.append('UNRELATED_STOCK_POSITION')
    shares=positions.get(symbol,D(0));target=packages*100
    if shares<0 or shares%100:issues.append('NONSTANDARD_WHEEL_SHARES')
    phase='CASH';template=None;status='NO_ACTION'
    if options:
        rights={right for right,_ in options}
        if len(options)!=1 or len(rights)!=1:issues.append('MIXED_WHEEL_OBLIGATIONS')
        phase='PUT_OPEN' if rights=={'PUT'} else 'CALL_OPEN'
    elif D(state['receivables']) or D(state['payables']):phase='SETTLEMENT_PENDING'
    elif shares:
        phase='STOCK'
        if shares<target:issues.append('INSUFFICIENT_COVERED_SHARES')
        else:template='covered_call';status='READY_FOR_SELECTION'
    else:
        if D(state['available_cash'])<=buffer:issues.append('INSUFFICIENT_AVAILABLE_CASH')
        else:template='cash_secured_put';status='READY_FOR_SELECTION'
    if issues:status='BLOCKED';template=None
    result={'strategy_version':VERSION,'account_id':account_id,'as_of':utc(as_of).isoformat(),'ledger_seq':state['ledger_seq'],
            'parameters':parameters,'phase':phase,'status':status,'template_id':template,'packages':packages,
            'checks':sorted(set(issues)),'executable':False,'data_type':'simulated_account' if book.environment=='demo' else 'recorded_account',
            'reason':'阶段仅依据实际持仓/应收应付；选约、全额履约资金、数据、权限、风险和计划仍须另行通过'}
    result['decision_id']=digest(result)
    return result
