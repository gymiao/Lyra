"""Exact expiry payoff for standard legs. This is not a historical backtest."""
from decimal import Decimal
from ..common import QuantError, decimal
from .contracts import Leg


def pnl(legs, underlying_price):
    spot = decimal(underlying_price)
    if spot < 0: raise QuantError('INVALID_SCENARIO','标的价格不能为负')
    total = Decimal(0)
    for leg in legs:
        value = spot if leg.kind == 'STOCK' else max(spot-leg.strike,Decimal(0)) if leg.kind == 'CALL' else max(leg.strike-spot,Decimal(0))
        total += leg.quantity*leg.multiplier*(value-leg.entry_price)-leg.fee
    return total


def analyze(legs, *, prices=None):
    legs = [Leg.from_dict(leg) if isinstance(leg,dict) else Leg.from_dict(leg.content()) for leg in legs]
    if not legs: raise QuantError('INVALID_SCENARIO','至少需要一条腿')
    expiries = {leg.expiry for leg in legs if leg.kind != 'STOCK'}
    if len(expiries) > 1:
        raise QuantError('MULTI_EXPIRY_REQUIRES_MODEL','日历/对角腿不能全部按同一天的内在价值计算；远月腿须理论重估')
    breakpoints = sorted({Decimal(0)} | {leg.strike for leg in legs if leg.kind != 'STOCK'})
    values = [pnl(legs,price) for price in breakpoints]
    tail = sum((leg.quantity*leg.multiplier for leg in legs if leg.kind in {'CALL','STOCK'}),Decimal(0))
    maximum, minimum = max(values), min(values)
    roots, intervals = set(), []
    for left,right,a,b in zip(breakpoints[:-1],breakpoints[1:],values[:-1],values[1:]):
        if a == 0: roots.add(left)
        if b == 0: roots.add(right)
        if a == b == 0: intervals.append([str(left),str(right)])
        elif (a < 0 < b) or (b < 0 < a): roots.add(left-a*(right-left)/(b-a))
    if values[-1] == 0: roots.add(breakpoints[-1])
    if tail:
        root = breakpoints[-1]-values[-1]/tail
        if root >= breakpoints[-1]: roots.add(root)
    elif values[-1] == 0: intervals.append([str(breakpoints[-1]),'unbounded'])
    if prices is None:
        high = max(breakpoints[-1]*Decimal('1.5'),Decimal(1))
        prices = [high*index/100 for index in range(101)]
    return {'data_type':'scenario_only','valuation':'standard_same_expiry_intrinsic','expiry':next(iter(expiries),None),
            'legs':[leg.content() for leg in legs], 'maximum_profit': None if tail>0 else str(maximum),
            'maximum_loss': None if tail<0 else str(max(-minimum,Decimal(0))),
            'profit_unbounded':tail>0,'loss_unbounded':tail<0,'right_tail_slope':str(tail),
            'break_even_prices':[str(value) for value in sorted(roots)], 'break_even_intervals':intervals,
            'points':[{'underlying_price':str(decimal(price)),'pnl':str(pnl(legs,price))} for price in prices],
            'limitations':['仅到期标准腿情景，非市场成交价或历史收益；不包含提前指派和执行路径；费用按输入逐腿计入']}
