"""Common-period monthly engine comparison; performance math is delegated to ffn."""
import hashlib
import json
import math
from pathlib import Path
import ffn
import pandas as pd
from ..common import QuantError,digest,now_utc,write_json
from ..data.calendar import Calendar
from .monthly_replay import monthly_replay
from .catalog import MONTHLY_RESEARCH
from ..strategies.archive import source_fingerprint


def engine_curve(directory,proof):
    result=json.loads((directory/'LyraX.LyraXMonthly.json').read_text())
    values=result['charts']['Strategy Equity']['series']['Equity']['values']
    points={}
    for point in sorted(values,key=lambda p:p[0]):
        clock=pd.Timestamp(point[0],unit='s',tz='UTC').tz_convert('America/New_York')
        # LEAN daily OHLC points end at the next local midnight. Their close belongs
        # to the preceding session; treating them as next-day prices hides entry costs.
        date=(clock-pd.Timedelta(days=1)).date() if clock.hour==clock.minute==clock.second==0 else clock.date()
        points[date]=float(point[4])
    calendar=Calendar.market(proof['evaluation_start'],proof['evaluation_end'])
    prices=[]
    for session,close in calendar.schedule.close_time.items():
        if session.date() not in points:raise QuantError('INCOMPLETE_OPTION_REPORT','引擎缺少该交易日净值记录')
        prices.append(points[session.date()])
    dates=[pd.Timestamp(proof['evaluation_start'])-pd.Timedelta(days=1),*calendar.sessions]
    curve=pd.Series([float(proof['initial_cash']),*prices],index=dates,name=proof['member'])
    if abs(curve.iloc[-1]-float(proof['actual_equity']))>.01:raise QuantError('INCOMPLETE_OPTION_REPORT','净值终值与引擎不一致')
    ledger=pd.read_csv(directory/'daily-equity.csv',index_col='date')
    independent=ledger.equity.reindex([str(day.date()) for day in calendar.sessions])
    if independent.isna().any() or any(abs(float(a)-float(b))>.01 for a,b in zip(prices,independent)):
        raise QuantError('INCOMPLETE_OPTION_REPORT','引擎收盘净值与逐日独立账本不一致')
    return curve


def metrics_for(curve,events,signals,annual_factor=252,execution_path=None):
    stats=ffn.calc_stats(curve,annualization_factor=annual_factor)
    numeric=lambda value:float(value) if value is not None and math.isfinite(float(value)) else None
    commissions=sum(float(e['fee']) for e in events);spread_cost=0.;turnover=0.;buy=0.;sell=0.
    from .monthly_portfolio import event_identity
    contracts={leg['contract']['contract_id']:leg['contract'] for signal in signals for leg in signal['selection']['legs']}
    quotes={leg['contract']['contract_id']:leg['reference_quote'] for signal in signals for leg in signal['selection']['legs']}
    stock_pnl=0.;option_pnl=0.;delivery_cash=0.;delivery_notional=0.;groups={}
    for e in events:
        if e.get('order_type')=='OptionExercise':
            # Contract retirement and physical stock delivery are not market trades.
            if not e['right']:
                cash=-float(e['quantity'])*float(e['price'])
                delivery_cash+=cash;delivery_notional+=abs(cash)
            continue
        notional=abs(float(e['quantity'])*float(e['price']))*(100 if e['right'] else 1)
        if e['quantity']>0:buy+=notional
        else:sell+=notional
        if e['right']:
            option_pnl-=float(e['quantity'])*float(e['price'])*100
            identity=event_identity(e,contracts)
            day=str(pd.Timestamp(e['utc_time']).tz_convert('America/New_York').date())
            q=execution_path['options'][identity][day] if execution_path is not None else quotes[identity]
            spread_cost+=abs(float(e['quantity']))*100*(float(q['ask'])-float(q['bid']))/2
        else:stock_pnl-=float(e['quantity'])*float(e['price'])
        key=(e['utc_time'],e['tag']);group=groups.setdefault(key,{'equity':float(e['pre_trade_equity']),'notional':0.})
        if group['equity']<=0 or group['equity']!=float(e['pre_trade_equity']):raise QuantError('INCOMPLETE_OPTION_REPORT','换手缺少共同批次的有效调仓前权益')
        group['notional']+=notional
    turnover=sum(g['notional']/(2*g['equity']) for g in groups.values())
    days=int((curve.index[-1]-curve.index[0]).days)
    return {'total_return':numeric(stats.total_return),'annual_return':numeric(stats.cagr),'max_drawdown':numeric(stats.max_drawdown),
        'annual_volatility':numeric(stats.daily_vol),'commission':commissions,'bid_ask_cost':spread_cost,
        'cost':commissions+spread_cost,'stock_trading_pnl':stock_pnl,'option_trading_pnl':option_pnl,
        'physical_delivery_cash_flow':delivery_cash,'physical_delivery_notional':delivery_notional,
        'net_trading_pnl':stock_pnl+option_pnl+delivery_cash-commissions,'turnover':turnover,'buy_notional':buy,'sell_notional':sell,
        'calendar_days':days,'observations':len(curve)-1,'short_sample_annualization':days<365,'annual_factor':annual_factor}


def monthly_compare(engine_root,dotnet,destination,signals,*,initial_cash,fee_per_contract,stock_commission_bps,packages=None,stock_basket=None,execution_path=None,final_lifecycle=None,retain_stock=False,prepare_stock=False):
    if not isinstance(signals,list) or len(signals)<2:raise QuantError('INVALID_MONTHLY_REPLAY','需要至少两个冻结月度信号')
    from .monthly_portfolio import normalize,flat
    batches,counts,multi=normalize(signals,packages)
    flat_signals=flat(batches)
    template=flat_signals[0]['selection']['template_id']
    if template not in MONTHLY_RESEARCH:raise QuantError('INVALID_MONTHLY_REPLAY','仅已实现月度研究模板可比较')
    destination=Path(destination).absolute()
    if destination.exists():raise QuantError('NONEMPTY_DESTINATION','月度比较需新报告目录')
    destination.mkdir(parents=True)
    proofs={};curves={};metrics={};transactions=[]
    for member,control in [(template,None),('stock','stock'),('cash','cash')]:
        directory=destination/member
        proof=monthly_replay(engine_root,dotnet,directory,signals,initial_cash=initial_cash,fee_per_contract=fee_per_contract,
            stock_commission_bps=stock_commission_bps,control=control,packages=packages,stock_basket=stock_basket,execution_path=execution_path,final_lifecycle=final_lifecycle,retain_stock=retain_stock,prepare_stock=prepare_stock)
        proofs[member]=proof;curve=engine_curve(directory,proof);curves[member]=curve
        events=json.loads((directory/'engine-events.json').read_text());metrics[member]=metrics_for(curve,events,flat_signals,execution_path=execution_path)
        transactions.extend({**e,'member':member} for e in events)
    policy_keys=['initial_cash','option_fee_per_contract','stock_commission_bps','evaluation_start','evaluation_end','calendar_hash','final_lifecycle','retain_stock','prepare_stock','engine_commit','adapter_source','data_manifest_hash']
    policies=[{key:p[key] for key in policy_keys} for p in proofs.values()]
    if any(policy!=policies[0] for policy in policies[1:]):raise QuantError('INCOMPARABLE_OPTION_RESEARCH','月度引擎、数据、资金、费用或区间不一致')
    frame=pd.DataFrame(curves)
    if frame.isna().any().any():raise QuantError('INCOMPARABLE_OPTION_RESEARCH','策略与控制组曲线没有共同完整区间')
    frame.to_csv(destination/'equity.csv',index_label='date')
    frame.apply(ffn.to_drawdown_series).to_csv(destination/'drawdowns.csv',index_label='date')
    pd.DataFrame(transactions).to_csv(destination/'transactions.csv',index=False)
    write_json(destination/'metrics.json',metrics)
    report={'schema_version':2,'status':'PASSED','data_type':'synthetic_variable_path' if execution_path is not None else 'synthetic_monthly_mechanical','executable':False,
        'source_fingerprint':source_fingerprint(),'execution_path_hash':digest(execution_path) if execution_path is not None else None,
        'final_lifecycle':final_lifecycle,'packages':packages if packages is not None else counts if multi else [1]*len(signals),'stock_basket':stock_basket or {},
        'generated_at':now_utc(),'as_of':policies[0]['evaluation_end'],'policy':policies[0],'metrics':metrics,
        'signal_ids':[s['monthly_signal_id'] for s in flat_signals],
        'monthly_batches':[[s['monthly_signal_id'] for s in batch] for batch in batches],
        'option_underlyings':sorted({s['selection']['underlying'] for s in flat_signals}),
        'snapshot_ids':sorted({s['input']['snapshot_id'] for s in flat_signals}),
        'assumptions':['历史重建合成机械验证；不是实际期权历史收益或真实账户',
            '每月先平仓再按工程T+1进入新组合；控制组使用同一窗口及收盘时点',
            '股票控制组使用相同每期股份/股票篮子，其余现金；不是全仓股票基准',
            '期权买ask/卖bid，价差成本只作解释，不重复扣减；股票手续费按显式bps',
            '换手分母采用提交批次权益；显式每交易日两采样点同价假设下与成交前权益一致',
            '初始资金基线为首交易日前一自然日，仅用于指标，无外部资金流；现金利息0',
            '不足一年年化仅是短样本换算；不证明策略有效性或来源资格']}
    if final_lifecycle:
        report['assumptions'].extend([
            '末期保留期权至自然到期；股票控制组持有至相同终止日',
            '下一交易日收盘统一清理股票，以现金终值核对；这是工程假设，不是券商安排',
            '实物交割现金单列，不计为市场交易/价差成本或外部入出金；市场换手不含交割',
            '自然路径日终净值截止下一本地午夜，包含该时点到期事实；按前一交易日标记，与LEAN日OHLC一致，不冒充收盘前行权'])
        if final_lifecycle=='natural_expiry_with_delivery_exit':
            report['assumptions'].append('显式交割政策：到期前20分钟取得实值保护Call行权交股，或MOC退出无法覆盖的实值长Put/短Call；其余自然到期。行权/交割费用假设0，市场费用照常计入')
            report['assumptions'][report['assumptions'].index('末期保留期权至自然到期；股票控制组持有至相同终止日')]='末期按显式交割处置政策退出或自然到期；股票控制组持有至相同终止日'
    if retain_stock:report['assumptions'].append('滚动期权时保留相同股份；每周期只平旧期权，等待结算后开新。股票仅初次买入和最终清理，各控制组采用相同持续持股政策')
    report['comparison']={'strategy_vs_stock_pnl':metrics[template]['net_trading_pnl']-metrics['stock']['net_trading_pnl'],
        'strategy_vs_cash_pnl':metrics[template]['net_trading_pnl']-metrics['cash']['net_trading_pnl'],
        'meaning':'同资本终值差额，含实物交割现金；价差已在交易盈亏内，不再扣除'}
    for member,curve in curves.items():
        if abs((curve.iloc[-1]-curve.iloc[0])-metrics[member]['net_trading_pnl'])>.01:
            raise QuantError('INCOMPLETE_OPTION_REPORT','交易/费用分解与同资本净值终值不一致')
    write_json(destination/'report.json',report)
    lines=['# LyraX 月度期权机械比较','',*report['assumptions'],'',
        f"区间：{report['policy']['evaluation_start']} 至 {report['as_of']}；展示时区Asia/Shanghai。",
        '期权标的：'+', '.join(report['option_underlyings'])+'；各月共享同一现金账户，原冻结信号分别保留。','',
        '| 组合 | 累计收益 | 年化收益（短样本） | 最大回撤 | 波动率 | 费用及价差成本 | 换手 |',
        '|---|---:|---:|---:|---:|---:|---:|']
    percent=lambda value:'无有效值' if value is None else f'{value:.4%}'
    for member,m in metrics.items():lines.append('| '+member+' | '+' | '.join(percent(m[k]) for k in ['total_return','annual_return','max_drawdown','annual_volatility'])+f" | {m['cost']:.2f} USD | {percent(m['turnover'])} |")
    (destination/'report.md').write_text('\n'.join(lines)+'\n')
    files={str(p.relative_to(destination)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(destination.rglob('*')) if p.is_file()}
    manifest={'report_hash':digest(report),'files':files};manifest['content_hash']=digest(manifest)
    write_json(destination/'manifest.json',manifest);return report


def load_monthly_report(directory):
    directory=Path(directory);manifest=json.loads((directory/'manifest.json').read_text())
    if digest({k:v for k,v in manifest.items() if k!='content_hash'})!=manifest['content_hash']:raise QuantError('CORRUPT_OPTION_REPORT','月度报告清单哈希改变')
    for name,expected in manifest['files'].items():
        relative=Path(name)
        if relative.is_absolute() or '..' in relative.parts:raise QuantError('CORRUPT_OPTION_REPORT','报告引用不能跨出目录')
        file=directory/relative
        if not file.is_file() or file.is_symlink() or hashlib.sha256(file.read_bytes()).hexdigest()!=expected:raise QuantError('CORRUPT_OPTION_REPORT','月度报告文件缺失或改变')
    body=json.loads((directory/'report.json').read_text())
    if digest(body)!=manifest['report_hash']:raise QuantError('CORRUPT_OPTION_REPORT','报告内容哈希不一致')
    if body.get('schema_version')!=2 or body.get('executable') is not False:
        raise QuantError('UNVERIFIED_OPTION_REPORT','旧报告缺少逐日净值交叉核验；请重新生成')
    if any(member not in MONTHLY_RESEARCH|{'stock','cash'} for member in body['metrics']):raise QuantError('CORRUPT_OPTION_REPORT','报告成员代码非法')
    published=pd.read_csv(directory/'equity.csv',index_col='date')
    for member in body['metrics']:
        proof=json.loads((directory/member/'verification.json').read_text())
        independent=engine_curve(directory/member,proof)
        values=published[member].reindex([str(date.date()) for date in independent.index])
        if values.isna().any() or any(abs(float(a)-float(b))>.01 for a,b in zip(values,independent)):
            raise QuantError('CORRUPT_OPTION_REPORT','发布净值与引擎/账本核验结果不一致')
    return body
