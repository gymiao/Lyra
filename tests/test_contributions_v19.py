import pandas as pd
import pytest
from personal_quant.common import QuantError
from personal_quant.research.contributions import contribution_bridge, rolling_comparison
from personal_quant.strategies.spec import StrategySpec
from personal_quant.strategies.templates import evaluate
from pathlib import Path


def test_previous_holdings_get_price_gain_before_close_trade_and_cost():
    dates=pd.date_range('2026-01-01',periods=3)
    prices=pd.DataFrame({'SPY':[100.,110.,110.]},index=dates)
    positions=pd.DataFrame({'SPY':[5.,0.,0.]},index=dates)
    nav=pd.Series([999.,1047.,1047.],index=dates)
    trades=pd.DataFrame({'Date':[dates[0],dates[1]],'commission':[1.,1.],'slippage_cost':[0.,1.]})
    daily,summary=contribution_bridge(prices,positions,nav,trades,1000.)
    assert daily['asset:SPY'].tolist()==[0.,50.,0.]
    assert daily.equity_change.tolist()==[-1.,48.,0.]
    assert summary['status']=='PASSED' and summary['maximum_absolute_residual']==0
    assert summary['amounts']['commission']==-2.
    assert summary['contribution_over_initial_capital']['asset:SPY']==.05


def test_rolling_requires_extra_endpoint_and_common_complete_dates():
    dates=pd.bdate_range('2026-01-01',periods=64)
    nav=pd.DataFrame({'base':100.,'candidate':range(100,164)},index=dates)
    results=rolling_comparison(nav,'base',windows=(63,126))
    candidate=next(r for r in results if r.get('member')=='candidate')
    assert candidate['observations']==63 and candidate['return']==pytest.approx(.63)
    assert candidate['return_difference']==pytest.approx(.63)
    assert results[-1]['status']=='INSUFFICIENT_DATA'
    nav.iloc[20,0]=float('nan')
    with pytest.raises(QuantError):rolling_comparison(nav,'base')


def test_dual_momentum_preset_filters_zero_ties_by_id_and_leaves_cap_remainder_cash():
    spec=StrategySpec.load(Path(__file__).resolve().parents[1]/'configs/strategies/dual_momentum.json')
    prices=pd.DataFrame({'GLD':[100.]*126+[110.],'IEF':[100.]*127,'SPY':[100.]*126+[110.]})
    weights,_,_=evaluate(prices,spec)
    assert spec.required_prices==127
    assert weights=={'GLD':.6,'IEF':0.,'SPY':0.}
    prices.iloc[-1]=100
    assert evaluate(prices,spec)[0]=={'GLD':0.,'IEF':0.,'SPY':0.}
