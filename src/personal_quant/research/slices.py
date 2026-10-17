"""Calendar-year slices of continuous bt equity, retaining original positions."""
import math
import pandas as pd
import ffn


def continuous_slices(nav, trades, initial_capital, annual_factor=252):
    rows=[]
    for year,window in nav.groupby(nav.index.year):
        earlier=nav.loc[nav.index<window.index[0]]
        baseline=earlier.iloc[-1] if not earlier.empty else pd.Series(initial_capital,index=nav.columns)
        baseline_date=earlier.index[-1] if not earlier.empty else window.index[0]-pd.Timedelta(days=1)
        for member in nav.columns:
            curve=pd.concat([pd.Series([baseline[member]],index=[baseline_date]),window[member]])/baseline[member]
            stats=ffn.calc_stats(curve,annualization_factor=annual_factor)
            matching=trades.loc[(trades.strategy==member)&(pd.to_datetime(trades.iloc[:,0])>=window.index[0])&(pd.to_datetime(trades.iloc[:,0])<=window.index[-1])]
            def numeric(v):return float(v) if v is not None and math.isfinite(float(v)) else None
            rows.append({'year':int(year),'member':member,'mode':'continuous_positions_slice','start':str(window.index[0].date()),
                'end':str(window.index[-1].date()),'baseline_as_of':str(baseline_date.date()),'observations':len(window),
                'total_return':numeric(curve.iloc[-1]-1),'annual_return':numeric(stats.cagr),'max_drawdown':numeric(stats.max_drawdown),
                'annual_volatility':numeric(stats.daily_vol),'cost':float(matching.total_cost.sum()),
                'short_sample_annualization':(window.index[-1]-baseline_date).days<365})
    return rows
