"""Fixed share stages from frozen option cycles, using shared stock plan state."""
import json
import pandas as pd
from ..common import QuantError,decimal as D,digest,canonical,now_utc,utc
from ..data.calendar import Calendar


def identity(run_id,cycle,side,day):
    return digest({'run_id':run_id,'cycle_id':cycle['signal_id'],'side':side,'session':day,'purpose':'simulation_stock'})


def match(event,cycles):
    day=pd.Timestamp(event['effective_at']).tz_convert('America/New_York').strftime('%Y-%m-%d')
    field='stock_entry' if event['kind']=='BUY' else 'stock_exit'
    time='stock_entry_submit_at' if event['kind']=='BUY' else 'stock_exit_submit_at'
    fallback='entry_submit_at' if event['kind']=='BUY' else 'exit_submit_at'
    found=[c for c in cycles if event['symbol'] in c.get(field,c['stock_positions']) and c.get(time,c[fallback])[:10]==day]
    if len(found)!=1:raise QuantError('SIMULATION_STOCK_ASSOCIATION','股票事实不能唯一关联冻结股数和执行日')
    return found[0],day


def prepare(book,config,account_id,run_id,cycle,side,day,path):
    if book.environment!='demo' or config.environment!='demo':raise QuantError('DEMO_ONLY','股票阶段只用于合成模拟')
    config.require_execution()
    plan_id=identity(run_id,cycle,side,day)
    old=book.connection.execute('SELECT plan_id FROM plans WHERE plan_id=?',(plan_id,)).fetchone()
    if old:return plan_id
    close=Calendar.market(day,day).close(day)
    clock=close-pd.Timedelta(minutes=20)
    prices={s:values[day] for s,values in path['stocks'].items()}
    prices.update({s:str((D(values[day]['bid'])+D(values[day]['ask']))/2) for s,values in path['options'].items() if day in values})
    snapshot=book.snapshot(account_id,clock,prices)
    if snapshot['equity'] is None or snapshot['anomalies'] or snapshot.get('pending_option_exits'):
        raise QuantError('SIMULATION_STOCK_ACCOUNT_BLOCKED','股票计划前账户不完整、存在差异或退出占用')
    equity=D(snapshot['equity']);lines=[];reserve=D(0);fees=D(0);positions={s:D(q) for s,q in snapshot['positions'].items()}
    declared=cycle.get('stock_entry' if side=='BUY' else 'stock_exit',cycle['stock_positions'])
    for symbol,value in declared.items():
        if symbol not in config.symbols:raise QuantError('UNCONFIGURED_HEDGE_SYMBOL','股票准备标的须在配置中明确列出')
        price=D(prices[symbol]);quantity=D(value)
        if side=='SELL':quantity=min(quantity,positions.get(symbol,D(0)))
        if not quantity:continue
        if price<=0 or quantity<=0 or quantity%D(config.lot_size):
            raise QuantError('INVALID_SIMULATION_STOCK_QUANTITY','股票阶段数量/原价/交易单位不合法')
        if side=='SELL' and quantity>positions.get(symbol,D(0))-D(snapshot['reserved_positions'].get(symbol,0)):
            raise QuantError('INSUFFICIENT_POSITION','股票仍被期权覆盖或其他计划占用')
        fee=quantity*price*(D(config.commission_bps)+D(config.slippage_bps))/10000+D(config.fixed_fee)
        fees+=fee
        if side=='BUY':reserve+=quantity*price+fee
        positions[symbol]=positions.get(symbol,D(0))+quantity*(1 if side=='BUY' else -1)
        lines.append(dict(symbol=symbol,side=side,quantity=str(quantity),price=str(price),estimated_fee=str(fee)))
    if not lines:raise QuantError('NO_ACTION','股票阶段没有可执行数量')
    if reserve>max(D(0),D(snapshot['available_cash'])-equity*D(config.cash_buffer)):
        raise QuantError('INSUFFICIENT_SETTLED_CASH','股票准备资金不足或侵占现金缓冲')
    if equity<=fees or any(q<0 or q*D(prices[s])>(equity-fees)*D(config.max_weight) for s,q in positions.items()):
        raise QuantError('WEIGHT_LIMIT','股票阶段预计持仓超过明确配置的仓位上限')
    context=dict(schema_version=1,run_id=run_id,cycle_id=cycle['signal_id'],eligible_session=day,
        valid_through_session=day,reason='冻结期权周期的股票准备/退出，不产生股票alpha信号')
    body=dict(purpose='simulation_stock',simulation_context=context,as_of=clock.isoformat(),
        environment='demo',data_type='synthetic',plan_id=plan_id,intent_id=plan_id,revision=1,
        reference_session=day,execution_session=day,execution_deadline=close.isoformat(),execution_basis_sequence=book.sequence(account_id),
        execution_config=config.content(),execution_config_hash=config.hash,snapshot=snapshot,
        reference_quote={'as_of':(clock-pd.Timedelta(minutes=1)).isoformat(),'data_type':'synthetic','prices':prices},
        sizing={'lines':lines,'reserve':str(reserve),'estimated_fee':str(fees),
            'projected_weights':{s:str(q*D(prices[s])/(equity-fees)) for s,q in positions.items()}},checks=[],
        created_at=now_utc(),executable=False,meaning='历史合成预先计划；不向券商提交订单')
    shares={line['symbol']:line['quantity'] for line in lines} if side=='SELL' else {}
    book.connection.execute('INSERT INTO plans VALUES(?,?,?,?,?,?,?,?,?,?)',
        (plan_id,plan_id,1,account_id,'READY','PASSED',canonical(body),str(reserve),canonical(shares),0))
    return plan_id
