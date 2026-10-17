"""Independent physical-delivery bridge for official natural expiry events."""
from ..common import QuantError,decimal as D
from .monthly_path import expected_equity

def expected_retained_natural(initial,cycles,stock_price,option_price,fee,bps,underlying):
    """Cash bridge: carried stock is already paid for, delivery exchanges strike cash."""
    cash=expected_equity(initial,cycles[:-1],stock_price,option_price,fee,bps)
    cycle=cycles[-1];entry=cycle['entry_submit_at'][:10];recovery=cycle.get('stock_exit_submit_at',cycle['exit_submit_at'])[:10]
    holdings={s:D(q) for s,q in cycle['stock_positions'].items()}
    for s in cycle['stock_entry']:
        cash-=holdings[s]*stock_price(s,cycle.get('stock_entry_submit_at',cycle['entry_submit_at'])[:10])*(1+D(bps)/10000)
    for leg in cycle['legs']:
        q=D(leg['quantity']);strike=D(leg['strike']);symbol=leg.get('underlying',underlying)
        spot=stock_price(symbol,leg['expiry'])
        itm=spot>strike if leg['right']=='CALL' else spot<strike
        cash-=q*100*option_price(leg['contract_id'],entry,'ask' if q>0 else 'bid')+abs(q)*D(fee)
        if not itm:continue
        call_cover=sum((max(D(other['quantity']),D(0))*100 for other in cycle['legs']
                        if other['right']=='CALL' and other.get('underlying',underlying)==symbol and D(other['strike'])<spot),D(0))
        forced=(cycle.get('delivery_exit_submit_at') and
                ((leg['right']=='PUT' and q>0 and D(cycle['stock_positions'].get(symbol,0))<q*100) or
                 (leg['right']=='CALL' and q<0 and D(cycle['stock_positions'].get(symbol,0))+call_cover<-q*100)))
        if forced:
            cash+=q*100*option_price(leg['contract_id'],leg['expiry'],'bid' if q>0 else 'ask')-abs(q)*D(fee)
        else:
            delivered=q*100*(1 if leg['right']=='CALL' else -1)
            cash-=delivered*strike
            holdings[symbol]=holdings.get(symbol,D(0))+delivered
    if any(q<0 for q in holdings.values()):
        raise QuantError('UNSUPPORTED_NATURAL_DELIVERY','滚动自然交割产生净股票空头，不能虚构清理')
    return cash+sum((q*stock_price(s,recovery)*(1-D(bps)/10000) for s,q in holdings.items()),D(0))

def expected_natural(initial,cycles,stock_price,option_price,fee,bps,underlying):
    value=expected_equity(initial,cycles[:-1],stock_price,option_price,fee,bps)
    cycle=cycles[-1];entry=cycle['entry_submit_at'][:10];recovery=cycle['exit_submit_at'][:10]
    stocks={s:D(q) for s,q in cycle['stock_positions'].items()};remaining=dict(stocks)
    for leg in cycle['legs']:
        expiry=leg['expiry'];q=D(leg['quantity']);strike=D(leg['strike']);symbol=leg.get('underlying',underlying);spot=stock_price(symbol,expiry)
        intrinsic=max(spot-strike,D(0)) if leg['right']=='CALL' else max(strike-spot,D(0))
        premium=option_price(leg['contract_id'],entry,'ask' if q>0 else 'bid')
        forced_put=(cycle.get('delivery_exit_submit_at') and leg['right']=='PUT' and q>0 and intrinsic>0
                    and stocks.get(symbol,D(0))<q*100)
        call_delivery=sum((max(D(other['quantity']),D(0))*100 for other in cycle['legs']
                           if other['right']=='CALL' and other.get('underlying',underlying)==symbol and D(other['strike'])<spot),D(0))
        forced_call=(cycle.get('delivery_exit_submit_at') and leg['right']=='CALL' and q<0 and intrinsic>0
                     and stocks.get(symbol,D(0))+call_delivery<-q*100)
        if forced_put or forced_call:
            value+=q*100*(option_price(leg['contract_id'],expiry,'bid' if q>0 else 'ask')-premium)-2*abs(q)*D(fee)
            continue
        value+=q*100*(intrinsic-premium)-abs(q)*D(fee)
        if intrinsic:
            delivery=q*100*(1 if leg['right']=='CALL' else -1)
            remaining[symbol]=remaining.get(symbol,D(0))+delivery
            value+=delivery*(stock_price(symbol,recovery)-spot)
    if any(q<0 for q in remaining.values()):
        raise QuantError('UNSUPPORTED_NATURAL_DELIVERY','净交割股票空头需独立恢复路径，不能假装只做多清理')
    for s,q in stocks.items():
        buy=stock_price(s,entry);sell=stock_price(s,recovery)
        value+=q*(sell-buy)-abs(q)*buy*D(bps)/10000
    value-=sum((abs(q)*stock_price(s,recovery)*D(bps)/10000 for s,q in remaining.items()),D(0))
    return value

def _contract(event,contracts):
    from .monthly_portfolio import event_contract
    return event_contract(event,contracts)

def validate_events(events,cycles,contracts):
    cycle=cycles[-1];expected={leg['contract_id']:D(leg['quantity']) for leg in cycle['legs']};seen={}
    for e in events:
        if e['order_type']!='MarketOnClose' or e['tag']!=cycle['signal_id']+'|CLOSE_DELIVERY_RISK':continue
        c=_contract(e,contracts)
        quantity=expected.get(c.contract_id,D(0))
        if (not cycle.get('delivery_exit_submit_at') or not (c.right=='PUT' and quantity>0 or c.right=='CALL' and quantity<0)
                or D(e['quantity'])!=-expected[c.contract_id]):
            raise QuantError('LEAN_LIFECYCLE_FAILED','交割风险事前退出数量/政策不一致')
        del expected[c.contract_id]
    for e in events:
        if e['order_type']!='OptionExercise' or e['symbol']!=e['order_symbol']:continue
        c=_contract(e,contracts)
        if c.contract_id not in expected or c.contract_id in seen or D(e['quantity'])!=-expected[c.contract_id] or D(e['fee'])!=0:
            raise QuantError('LEAN_LIFECYCLE_FAILED','自然生命周期重复/数量/费用不符合独立假设')
        if (type(e['in_the_money']) is not bool or type(e['assignment']) is not bool
                or e['assignment']!=(e['in_the_money'] and expected[c.contract_id]<0)):
            raise QuantError('LEAN_LIFECYCLE_FAILED','行权/指派方向与实际多空合约不一致')
        seen[c.contract_id]=e
    if set(seen)!=set(expected):raise QuantError('LEAN_LIFECYCLE_FAILED','末期合约缺少自然生命周期凭据')
    if any(e['order_type']=='MarketOnClose' and e['right'] and e['tag']==cycle['signal_id']+'|CLOSE' for e in events):
        raise QuantError('LEAN_LIFECYCLE_FAILED','自然末期不能用普通平仓替代到期')

def lifecycle_fact(event,contracts,cycles):
    c=_contract(event,contracts);leg=next(l for cycle in cycles for l in cycle['legs'] if l['contract_id']==c.contract_id)
    return dict(kind='OPTION_EXPIRY' if not event['in_the_money'] else
        'OPTION_ASSIGNMENT' if event['assignment'] else 'OPTION_EXERCISE',
        contract_version=c.version_hash,position_side='LONG' if D(leg['quantity'])>0 else 'SHORT')

def receipt_view(row,point,sequence):
    checks=list(point['anomalies'])
    if any(D(q)<0 for q in point['positions'].values()):checks.append('UNSUPPORTED_STOCK_SHORT_AFTER_DELIVERY')
    return {'event_id':row['event_id'],'kind':row['kind'],
        'check_status':'BLOCKED' if checks or point['equity'] is None else 'CHECKED',
        'checks':checks,'ledger_seq':sequence,'snapshot':point,
        'meaning':'该条原生凭据后的账户前缀；后续相抵不抹掉中间风险'}

