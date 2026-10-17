"""Cash-free research P&L bridge and common complete rolling observations."""
import numpy as np
import pandas as pd
import ffn
from ..common import QuantError


def contribution_bridge(prices, positions, nav, trades, initial_capital, *, tolerance=1e-6):
    """Positions are end-of-session bt holdings; execution is at that close."""
    if not prices.index.equals(nav.index) or not positions.index.equals(nav.index):
        raise QuantError('INCOMPLETE_ATTRIBUTION','价格、期末持仓与净值日期须完全一致')
    positions=positions.reindex(columns=prices.columns,fill_value=0.)
    if prices.isna().any().any() or positions.isna().any().any() or nav.isna().any():
        raise QuantError('INCOMPLETE_ATTRIBUTION','归因不填充缺失价格、持仓或净值')
    gains=positions.shift(1,fill_value=0.)*prices.diff().fillna(0.)
    # Initial holdings are zero; the first day's price move earns no asset P&L.
    costs=pd.DataFrame(0.,index=nav.index,columns=['commission','slippage_cost'])
    if not trades.empty:
        dates=pd.to_datetime(trades.iloc[:,0])
        for key in costs.columns:
            grouped=trades.assign(_date=dates).groupby('_date')[key].sum()
            costs[key]=grouped.reindex(nav.index,fill_value=0.)
    change=nav.diff();change.iloc[0]=nav.iloc[0]-initial_capital
    residual=change-gains.sum(axis=1)+costs.sum(axis=1)
    daily=gains.rename(columns=lambda s:'asset:'+s)
    daily['cash_interest']=0.;daily['commission']=-costs.commission;daily['slippage_cost']=-costs.slippage_cost
    daily['residual']=residual;daily['equity_change']=change
    return daily,{'mode':'research_no_external_flows','initial_capital':initial_capital,
        'status':'PASSED' if residual.abs().max()<=tolerance else 'WARNING',
        'tolerance':tolerance,'maximum_absolute_residual':float(residual.abs().max()),
        'amounts':{key:float(daily[key].sum()) for key in daily.columns},
        'contribution_over_initial_capital':{key:float(daily[key].sum()/initial_capital) for key in daily.columns if key!='equity_change'},
        'assumptions':'前一交易日期末持仓获得当日价格变动；收盘成交成本当日扣除；复权价格不再加分红；现金利息为0'}


def rolling_comparison(nav, benchmark, windows=(63,126,252), annual_factor=252):
    if benchmark not in nav or nav.index.has_duplicates or not nav.index.is_monotonic_increasing:
        raise QuantError('INVALID_ROLLING_INPUT','共同净值或基准无效')
    if not np.isfinite(nav.to_numpy()).all() or (nav<=0).any().any():
        raise QuantError('INVALID_ROLLING_INPUT','净值须为完整正数；不填补缺值')
    rows=[]
    for length in windows:
        if type(length) is not int or length<2:raise QuantError('INVALID_ROLLING_WINDOW','窗口需为至少2个收益观察值')
        if len(nav)<length+1:
            rows.append({'window':length,'status':'INSUFFICIENT_DATA','required_nav_points':length+1,'available_nav_points':len(nav)})
            continue
        for position in range(length,len(nav)):
            sample=nav.iloc[position-length:position+1]
            ref=sample[benchmark].iloc[-1]/sample[benchmark].iloc[0]-1
            for member in nav:
                curve=sample[member]/sample[member].iloc[0]
                returns=curve.pct_change(fill_method=None).iloc[1:]
                total=float(curve.iloc[-1]-1)
                rows.append({'window':length,'status':'PASSED','member':member,'start':str(sample.index[0].date()),
                    'end':str(sample.index[-1].date()),'return':total,'benchmark_return':float(ref),'return_difference':total-float(ref),
                    'annual_volatility':float(returns.std(ddof=1)*np.sqrt(annual_factor)),
                    'max_drawdown':float(ffn.to_drawdown_series(curve).min()),
                    'short_sample_annualization':(sample.index[-1]-sample.index[0]).days<365,
                    'observations':length})
    return rows
