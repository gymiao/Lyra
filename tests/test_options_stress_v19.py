from decimal import Decimal
import pytest
from personal_quant.common import QuantError
from personal_quant.options.stress import evaluate


def request():
    return {'valuation_date':'2026-10-09','horizon_date':'2026-11-20','underlying_prices':[90,100,110],
        'volatility_multipliers':[.8,1,1.2],
        'legs':[{'kind':'CALL','quantity':-1,'strike':100,'entry_price':2,'multiplier':100,'expiry':'2026-11-20'},
                {'kind':'CALL','quantity':1,'strike':100,'entry_price':4,'multiplier':100,'expiry':'2026-12-18'}],
        'models':{str(i):{'style':'EUROPEAN','volatility':.2,'rate':0,'dividend_yield':0} for i in range(2)}}


def test_calendar_far_leg_keeps_time_value_at_near_expiry():
    result=evaluate(request())
    at_money=next(row for row in result['points'] if row['underlying_price']=='100' and row['volatility_multiplier']=='1')
    assert Decimal(at_money['leg_values'][0]['value'])==0
    assert Decimal(at_money['leg_values'][1]['value'])>0
    assert at_money['leg_values'][1]['basis']=='QuantLib_remaining_time_value'
    assert not at_money['greeks_complete'] and result['maximum_loss']=='NOT_INFERRED_FROM_FINITE_GRID'


def test_missing_iv_and_unobserved_prior_expiry_path_are_blocked():
    body=request();body['models'].pop('1')
    with pytest.raises(QuantError,match='每条'):evaluate(body)
    body=request();body['horizon_date']='2026-11-21'
    with pytest.raises(QuantError,match='此前到期'):evaluate(body)
