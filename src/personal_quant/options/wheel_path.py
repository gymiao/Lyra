"""Independent cash/delivery arithmetic for frozen monthly Wheel scenarios."""
from ..common import QuantError,decimal as D


def expected_wheel(initial,cycles,stock_price,option_price,fee,bps,underlying):
    cash=D(initial);shares=D(0)
    for cycle in cycles:
        leg=cycle['legs'][0];quantity=-D(leg['quantity']);entry=cycle['entry_submit_at'][:10]
        if (leg['right']=='PUT' and shares) or (leg['right']=='CALL' and shares!=quantity*100):
            raise QuantError('WHEEL_STAGE_MISMATCH','冻结候选阶段不符合此前实际交割结果')
        strike=D(leg['strike']);spot=stock_price(underlying,leg['expiry'])
        if leg['right']=='PUT' and cash<quantity*(strike*100+D(fee)):
            raise QuantError('INSUFFICIENT_WHEEL_CASH','Wheel不以尚未收到的权利金代替履约资金')
        cash+=quantity*100*option_price(leg['contract_id'],entry,'bid')-quantity*D(fee)
        itm=spot<strike if leg['right']=='PUT' else spot>strike
        if itm:
            direction=1 if leg['right']=='PUT' else -1
            shares+=direction*quantity*100;cash-=direction*quantity*strike*100
    if shares:
        cash+=shares*stock_price(underlying,cycles[-1]['exit_submit_at'][:10])*(1-D(bps)/10000)
    return cash


def validate_wheel_events(events,cycles,contracts):
    from .monthly_natural import validate_events
    for cycle in cycles:
        identities={leg['contract_id'] for leg in cycle['legs']}
        native=[event for event in events if event.get('right') is not None and
                any(c.contract_id in identities and c.expiry==event['expiry'] and c.right==event['right'] and c.strike==D(event['strike']) for c in contracts.values())]
        validate_events(native,[cycle],contracts)
