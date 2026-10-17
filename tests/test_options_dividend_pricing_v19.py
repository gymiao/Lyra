import math
import pytest
from personal_quant.common import QuantError
from personal_quant.options.pricing import price

ARGS={'spot':100,'strike':100,'valuation_date':'2025-01-01','expiry':'2026-01-01',
      'volatility':.2,'rate':.05,'dividend_yield':0,'multiplier':1,'contracts':1}
DIVIDENDS=[{'ex_date':'2025-07-01','amount_per_share':5}]


def test_discrete_dividend_european_put_call_parity_and_no_duplicate_yield():
    call=price(**ARGS,right='CALL',style='EUROPEAN',discrete_dividends=DIVIDENDS)
    put=price(**ARGS,right='PUT',style='EUROPEAN',discrete_dividends=DIVIDENDS)
    expected=100-5*math.exp(-.05*181/365)-100*math.exp(-.05)
    assert abs(call['unit_price']-put['unit_price']-expected)<.01
    no_dividend=price(**ARGS,right='CALL',style='EUROPEAN')
    assert call['unit_price']<no_dividend['unit_price']
    with pytest.raises(QuantError,match='重复'):
        price(**{**ARGS,'dividend_yield':.01},right='CALL',style='EUROPEAN',discrete_dividends=DIVIDENDS)


def test_american_cash_dividend_model_and_iv_unknown_are_explicit():
    american=price(**{**ARGS,'strike':90},right='CALL',style='AMERICAN',discrete_dividends=DIVIDENDS,market_price=12)
    european=price(**{**ARGS,'strike':90},right='CALL',style='EUROPEAN',discrete_dividends=DIVIDENDS)
    assert american['unit_price']>=european['unit_price']
    assert american['implied_volatility'] is None and '尚未验证' in american['iv_missing_reason']


def test_small_positive_volatility_does_not_bump_to_negative_volatility():
    result=price(**{**ARGS,'volatility':.00005,'rate':0},right='CALL',style='EUROPEAN')
    assert result['unit_price']>0 and all(math.isfinite(v) for v in result['greeks'].values())
