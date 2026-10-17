from copy import deepcopy
import pytest
from personal_quant.common import QuantError,decimal as D
from personal_quant.hedging.stage_stress import evaluate
from test_hedging_stress_v19 import fixture_risk,request
from test_hedging_option_sizing_v19 import selected


def inputs(selected,template='collar',quantity=1):
    selection=selected[template];risk=fixture_risk();risk['account']['available_cash']='1000'
    terms={l['contract']['contract_id']:l['contract'] for l in selection['legs']}
    quotes={l['contract']['contract_id']:l['reference_quote'] for l in selection['legs']}
    stage=dict(stage_id='open',plan_kind='option',action='OPEN',lines=[dict(symbol=l['contract']['contract_id'],
        contract_version=l['contract_version'],side='BUY' if D(l['quantity_per_package'])>0 else 'SELL',quantity=str(quantity)) for l in selection['legs']])
    remaining={str((l['symbol'],l['contract_version'],l['side'])):l['quantity'] for l in stage['lines']}
    req=request(selection);req['limits']=dict(stock_cost_bps=0,option_fee_per_contract=2,adverse_slippage_fraction=0,
        cash_buffer=0,minimum_sample_equity=0,maximum_sample_loss=10000)
    return risk,stage,remaining,terms,quotes,req


def test_collar_each_leg_vertex_costs_and_receivables(selected):
    args=inputs(selected);before=deepcopy(args)
    out=evaluate(*args)
    assert args==before and len(out['vertices'])==4 and out['status']=='CHECKED'
    zero,call,put,both=out['vertices']
    assert D(zero['friction'])==0 and D(zero['required_settled_cash'])==0
    assert D(call['required_settled_cash'])==0
    assert D(call['sale_proceeds_not_available'])==98
    assert D(put['required_settled_cash'])==112
    assert D(both['required_settled_cash'])==112
    assert D(both['friction'])==14
    assert not out['executable'] and not out['creates_reservations']


def test_unsettled_call_premium_cannot_fund_long_put(selected):
    args=list(inputs(selected));args[0]['account']['available_cash']='50'
    out=evaluate(*args)
    assert out['status']=='BLOCKED'
    assert out['vertices'][1]['status']=='CHECKED'
    assert out['vertices'][2]['status']=='BLOCKED' and out['vertices'][3]['status']=='BLOCKED'
    assert 'INSUFFICIENT_SETTLED_CASH_AT_VERTEX' in out['checks']


def test_uncovered_partial_short_leg_blocks_even_when_full_package_has_put(selected):
    args=list(inputs(selected,quantity=3));args[0]['account']['available_cash']='10000'
    out=evaluate(*args)
    assert 'UNCOVERED_CALL_AT_VERTEX:SPY' in out['checks']
    assert out['vertices'][1]['status']=='BLOCKED'


def test_other_plan_reserved_shares_cannot_be_reused_for_call(selected):
    args=list(inputs(selected,quantity=2));args[0]['account']['reserved_positions']={'SPY':'100'}
    out=evaluate(*args)
    assert 'UNCOVERED_CALL_AT_VERTEX:SPY' in out['checks']


def test_quote_size_is_checked_per_individual_fill_vertex(selected):
    args=list(inputs(selected));symbol=args[1]['lines'][0]['symbol'];args[4][symbol]['ask_size']=0
    out=evaluate(*args)
    assert 'INSUFFICIENT_QUOTED_SIZE:'+symbol in out['checks']
    assert out['vertices'][1]['status']=='CHECKED' and out['vertices'][2]['status']=='BLOCKED'


def test_pressure_threshold_applies_to_unprotected_partial_state(selected):
    args=list(inputs(selected));args[-1]['limits']['maximum_sample_loss']=4900
    out=evaluate(*args)
    # 250 SPY shares fall from 100 to 80: no leg filled loses exactly 5000.
    assert D(out['vertices'][0]['worst_sample_loss'])==5000
    assert 'MAXIMUM_SAMPLE_LOSS_BREACHED' in out['vertices'][0]['checks']


def test_existing_option_close_cannot_turn_into_reverse_open(selected):
    args=list(inputs(selected,'protective_put',quantity=2));symbol=args[1]['lines'][0]['symbol']
    args[0]['account']['option_positions']={symbol:'1'};args[1]['action']='CLOSE';args[1]['lines'][0]['side']='SELL'
    args[2]={str((symbol,args[1]['lines'][0]['contract_version'],'SELL')):'2'}
    out=evaluate(*args)
    assert 'CLOSE_EXCEEDS_ACTUAL_POSITION:'+symbol in out['checks']
    assert out['status']=='BLOCKED'


def test_no_grid_truncation_and_no_missing_models(selected):
    args=list(inputs(selected));args[-1]['models']={}
    with pytest.raises(QuantError,match='全部确切合约模型'):evaluate(*args)
    args=list(inputs(selected));args[1]['lines']=args[1]['lines']*5
    with pytest.raises(QuantError) as exc:evaluate(*args)
    assert exc.value.code=='STAGE_GRID_TOO_LARGE'
