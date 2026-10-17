import pytest
from personal_quant.common import QuantError,decimal as D
from personal_quant.hedging.stage_assessment import analyze
from personal_quant.hedging.groups import save
from personal_quant.hedging.allocation_store import resources
from personal_quant.hedging.archive import publish
from test_hedging_groups_v19 import request as group_request,native_stock
from test_hedging_archive_v19 import frozen_risk
from test_hedging_exposure_v19 import risk_market


def setup(fixture):
    book,config,store,query,_=fixture
    _,req=group_request(fixture);group=save(book,'sample',req,commit=True)
    risk=publish(book,config,store,'sample',query)
    body=dict(group_id=group['group_id'],expected_group_hash=group['record_hash'],
        expected_resource_hash=resources(book,'sample'),stage_id='sale',exposure_id=risk['exposure_id'],
        option_snapshot_id=None,quote_limits=dict(max_age_seconds=3600,max_underlying_skew_seconds=120,
        max_spread_fraction=.2,max_leg_skew_seconds=10,max_underlying_price_fraction=.01),
        stress=dict(scenarios=[dict(name='down',horizon_date='2025-01-15',benchmark_return=-.2,
            beta_multiplier=1,residual_returns={'SPY':0},volatility_multiplier=1)],models={},
            limits=dict(stock_cost_bps=10,option_fee_per_contract=2,adverse_slippage_fraction=0,
                cash_buffer=0,minimum_sample_equity=0,maximum_sample_loss=10000)))
    return book,body


def test_stage_uses_current_group_account_and_does_not_write(frozen_risk):
    book,body=setup(frozen_risk);before=resources(book,'sample')
    first=analyze(book,'sample',body)
    assert first==analyze(book,'sample',body)
    assert resources(book,'sample')==before and book.sequence('sample')==2
    assert first['status']=='CHECKED' and len(first['vertices'])==2
    assert D(first['vertices'][1]['friction'])==4
    assert D(first['vertices'][1]['sale_proceeds_not_available'])==3996
    assert first['execution_qualification']=='NOT_GRANTED'


@pytest.mark.parametrize('field,value,code',[
    ('expected_group_hash','bad','STALE_HEDGE_GROUP'),
    ('expected_resource_hash','bad','STALE_HEDGE_RESOURCES'),
    ('stage_id','bad','INVALID_HEDGE_STAGE')])
def test_stale_stage_inputs_rejected(frozen_risk,field,value,code):
    book,body=setup(frozen_risk)
    with pytest.raises(QuantError) as exc:analyze(book,'sample',{**body,field:value})
    assert exc.value.code==code


def test_changed_other_plan_reservation_requires_new_risk(frozen_risk):
    book,body=setup(frozen_risk);native_stock(book,'other',quantity=1)
    book.connection.execute("UPDATE plans SET reserved_cash='100' WHERE plan_id='other'")
    body['expected_resource_hash']=resources(book,'sample')
    with pytest.raises(QuantError) as exc:analyze(book,'sample',body)
    assert exc.value.code=='STALE_STAGE_ACCOUNT'

from test_hedging_group_option_revisions_v19 import option_partial
from personal_quant.hedging.groups import history
from personal_quant.options.data import OptionDataStore
import pandas as pd


def option_stage_request(frozen_risk,option_partial):
    book,c,old,clock,_,_=option_partial
    _,config,store,query,_=frozen_risk
    query={**query,'ledger_seq':book.sequence('sample')}
    risk=publish(book,config,store,'sample',query);group=history(book,'sample')[0]
    from personal_quant.hedging.intents import records
    parent=records(book,'sample')[0]
    request=dict(group_id=group['group_id'],expected_group_hash=group['record_hash'],
        expected_resource_hash=resources(book,'sample'),stage_id='open',exposure_id=risk['exposure_id'],
        option_snapshot_id=parent['candidate']['option_snapshot_id'],quote_limits=dict(max_age_seconds=3600,
        max_underlying_skew_seconds=120,max_spread_fraction=.25,max_leg_skew_seconds=10,max_underlying_price_fraction=.01),
        stress=dict(scenarios=[dict(name='decline',horizon_date=c.expiry,benchmark_return=-.2,beta_multiplier=1,
        residual_returns={'SPY':0},volatility_multiplier=1)],models={c.version_hash:dict(volatility=.2,rate=0,dividend_yield=0)},
        limits=dict(stock_cost_bps=10,option_fee_per_contract=2,adverse_slippage_fraction=0,
        cash_buffer=0,minimum_sample_equity=0,maximum_sample_loss=10000)))
    return book,c,clock,request


def test_stage_current_option_quotes_and_future_quote_gate(frozen_risk,option_partial):
    book,c,clock,request=option_stage_request(frozen_risk,option_partial)
    out=analyze(book,'sample',request)
    assert out['status']=='CHECKED' and out['source_assessment']['status']=='SYNTHETIC_DEMO'
    assert len(out['vertices'])==2 and not out['executable']
    store=OptionDataStore(book.path.parent/'options/chains');terms,rows,meta,_=store.load(request['option_snapshot_id'])
    for row in rows:
        row['available_at']='2025-01-16T21:00:00Z';row['received_at']='2025-01-16T21:00:00Z'
    future=store.save(list(terms.values()),pd.DataFrame(rows),meta)['snapshot_id']
    with pytest.raises(QuantError) as exc:analyze(book,'sample',{**request,'option_snapshot_id':future})
    assert exc.value.code=='MISSING_CURRENT_QUOTE'
