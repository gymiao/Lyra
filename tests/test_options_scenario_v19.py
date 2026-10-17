from decimal import Decimal
import pytest
from personal_quant.common import QuantError
from personal_quant.options.payoff import analyze
from personal_quant.options.catalog import template, catalog
from personal_quant.options.pricing import price


def test_protective_put_has_700_loss_and_covered_call_has_700_profit():
    put=analyze(template('protective_put'),prices=[80])
    assert Decimal(put['points'][0]['pnl']) == -700
    assert Decimal(put['maximum_loss']) == 700
    assert put['profit_unbounded'] and put['maximum_profit'] is None
    call=analyze(template('covered_call'),prices=[110])
    assert Decimal(call['points'][0]['pnl']) == 700
    assert Decimal(call['maximum_profit']) == 700
    assert Decimal(call['maximum_loss']) == 9800


def test_vertical_uses_net_premium_and_whole_contract_multiplier():
    legs=template('bull_call_debit_spread',premium=3,second_premium=1)
    result=analyze(legs,prices=[90,110])
    assert [Decimal(p['pnl']) for p in result['points']] == [-200,300]
    assert result['break_even_prices'] == ['102']
    assert Decimal(result['maximum_profit']) == 300
    assert not result['loss_unbounded']


def test_unbounded_tail_detected_even_when_plot_has_only_small_prices():
    result=analyze([{'kind':'CALL','quantity':-1,'entry_price':2,'strike':100,'multiplier':100,'expiry':'2026-12-18'}],prices=[0,50,100])
    assert result['loss_unbounded'] and result['maximum_loss'] is None
    with pytest.raises(QuantError,match='远月腿'):
        analyze([*template('long_call'),*template('long_put',expiry='2027-01-15')])


def test_all_eight_templates_are_scenarios_not_historical_capabilities():
    rows=[s for family in catalog() for s in family['strategies'] if s['priority']=='A']
    assert len(catalog()) == 14 and len(rows) == 8
    for row in rows:
        assert analyze(template(row['template_id']))['data_type'] == 'scenario_only'
        assert row['historical'] == 'NOT_VALIDATED'


def test_quantlib_matches_independent_bsm_example_and_restores_global_date():
    import QuantLib as q
    previous=q.Settings.instance().evaluationDate
    result=price(right='CALL',style='EUROPEAN',spot=100,strike=100,valuation_date='2026-01-01',
        expiry='2027-01-01',volatility=.2,rate=.05,dividend_yield=0,multiplier=100,contracts=1,market_price=10.450583572185565)
    # Standard published BSM value: S=K=100, T=1, r=.05, sigma=.2.
    assert result['unit_price'] == pytest.approx(10.450583572185565,abs=1e-8)
    assert result['greeks']['delta'] == pytest.approx(63.68306511756,abs=1e-8)
    assert result['implied_volatility'] == pytest.approx(.2,abs=1e-6)
    assert q.Settings.instance().evaluationDate == previous
    invalid=price(right='CALL',style='EUROPEAN',spot=100,strike=100,valuation_date='2026-01-01',
        expiry='2027-01-01',volatility=.2,market_price=1000)
    assert invalid['implied_volatility'] is None and invalid['iv_missing_reason']


def test_american_put_is_at_least_european_and_negative_position_greeks_reverse():
    args=dict(right='PUT',spot=100,strike=100,valuation_date='2026-01-01',expiry='2027-01-01',volatility=.2,rate=.05)
    euro=price(style='EUROPEAN',**args);american=price(style='AMERICAN',**args)
    short=price(style='AMERICAN',contracts=-1,**args)
    assert american['unit_price'] >= euro['unit_price']
    assert short['greeks']['delta'] == -american['greeks']['delta']
