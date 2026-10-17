"""Explicit synthetic daily execution paths; no filling missing sessions."""
import re
from ..common import QuantError,decimal as D

def validate_path(path,sessions,symbols,contracts,quotes):
    if not isinstance(path,dict) or set(path)!={'schema_version','data_type','stocks','options'} or path['schema_version']!=1 or path['data_type']!='synthetic':
        raise QuantError('INVALID_LEAN_PATH','执行路径需schema1/明确synthetic及股票/期权逐日价格')
    dates={str(day.date()) for day in sessions}
    if not isinstance(path['stocks'],dict) or set(path['stocks'])!=set(symbols) or not isinstance(path['options'],dict) or set(path['options'])!=set(contracts):
        raise QuantError('INVALID_LEAN_PATH','路径须逐项匹配篮子/标的及冻结合约')
    for symbol,rows in path['stocks'].items():
        if not re.fullmatch(r'[A-Z][A-Z0-9.-]{0,15}',symbol) or not isinstance(rows,dict) or set(rows)!=dates:
            raise QuantError('INCOMPLETE_LEAN_PATH','股票路径缺少或多出交易日')
        if any(D(p)<=0 or D(p)*10000!=(D(p)*10000).to_integral_value() for p in rows.values()):
            raise QuantError('INVALID_LEAN_PATH','原价须为正且可精确表示为LEAN万分单位')
    for identity,c in contracts.items():
        rows=path['options'][identity]
        needed={day for day in dates if c.listed_at[:10]<=day<=c.expiry and quotes[identity]['received_at'][:10]<=day}
        if not isinstance(rows,dict) or set(rows)!=needed:raise QuantError('INCOMPLETE_LEAN_PATH','期权路径缺少或多出合约已知交易日')
        for row in rows.values():
            if (not isinstance(row,dict) or set(row)!={'bid','ask'} or D(row['bid'])<=0 or D(row['ask'])<D(row['bid'])
                    or any(D(row[k])*10000!=(D(row[k])*10000).to_integral_value() for k in row)):
                raise QuantError('INVALID_LEAN_PATH','期权执行路径需完整正bid/ask与精确单位')
    return path


def expected_equity(initial_cash,cycles,stock_price,option_price,fee,stock_bps):
    total=D(initial_cash)
    for cycle in cycles:
        entry=cycle['entry_submit_at'][:10];exit=cycle['exit_submit_at'][:10]
        for symbol,quantity in cycle['stock_positions'].items():
            if 'stock_entry' in cycle:
                if symbol in cycle['stock_entry']:total-=D(quantity)*stock_price(symbol,cycle.get('stock_entry_submit_at',cycle['entry_submit_at'])[:10])*(1+D(stock_bps)/10000)
                if symbol in cycle['stock_exit']:total+=D(quantity)*stock_price(symbol,cycle.get('stock_exit_submit_at',cycle['exit_submit_at'])[:10])*(1-D(stock_bps)/10000)
                continue
            q=D(quantity);buy=stock_price(symbol,entry);sell=stock_price(symbol,exit)
            total+=q*(sell-buy)-abs(q)*(buy+sell)*D(stock_bps)/10000
        for leg in cycle['legs']:
            q=D(leg['quantity']);identity=leg['contract_id']
            buy=option_price(identity,entry,'ask' if q>0 else 'bid')
            sell=option_price(identity,exit,'bid' if q>0 else 'ask')
            total+=q*100*(sell-buy)-2*abs(q)*D(fee)
    return total

