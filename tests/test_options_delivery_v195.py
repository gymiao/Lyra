from native_tools import native_engine_root,native_dotnet
import json
import pytest
from test_options_monthly_replay_v19 import monthly_signals,ROOT
from test_options_monthly_natural_v19 import natural_path
from personal_quant.options.monthly_replay import monthly_replay


@pytest.mark.parametrize('name,spot,expected,forced',[
    ('long_straddle',100,99748,False),
    ('long_straddle',110,100748,False),
    ('long_straddle',90,100746,True),
    ('long_strangle',100,99748,False),
    ('long_strangle',90,100246,True),
    ('bull_put_credit_spread',100,100058,False),
    ('bull_put_credit_spread',80,99556,True),
    ('bear_call_credit_spread',100,100058,False),
    ('bear_call_credit_spread',120,99558,False),
    ('bear_call_credit_spread',107,99846,True)])
def test_native_expiry_or_explicit_delivery_risk_exit_matches_independent_cash(tmp_path,name,spot,expected,forced):
    signals=monthly_signals(tmp_path,name)
    proof=monthly_replay(native_engine_root(),native_dotnet(),tmp_path/'engine',signals,
        initial_cash=100000,fee_per_contract=2,execution_path=natural_path(signals,spot),
        final_lifecycle='natural_expiry_with_delivery_exit')
    assert float(proof['actual_equity'])==expected and float(proof['ledger_bridge']['equity'])==expected
    assert proof['ledger_bridge']['positions']=={} and proof['ledger_bridge']['option_positions']=={}
    assert proof['duplicate_events_added']==0 and not proof['ledger_bridge']['anomalies']
    events=json.loads((tmp_path/'engine/engine-events.json').read_text())
    exits=[event for event in events if (event['tag'] or '').endswith('|CLOSE_DELIVERY_RISK')]
    assert bool(exits)==forced
    assert all(event['order_type']=='MarketOnClose' for event in exits)
    # Closing a risky leg must not also produce its exercise/assignment receipt.
    closed={event['order_symbol'] for event in exits}
    assert not any(event['order_type']=='OptionExercise' and event['order_symbol'] in closed for event in events)
