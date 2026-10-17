from native_tools import native_engine_root,native_dotnet
import json
import pytest
from test_options_monthly_replay_v19 import monthly_signals,ROOT
from test_options_monthly_natural_v19 import natural_path
from personal_quant.options.monthly_replay import monthly_replay


def wheel_inputs(tmp_path,assigned=True):
    settings={'expiry_specs':[('2024-11-20','2024-10-31','2024-10-01'),('2024-12-18','2024-11-29','2024-11-01')],
              'selection_parameters':{'target_dte':21,'minimum_dte':14,'maximum_dte':35},'scope':'synthetic-wheel'}
    first=monthly_signals(tmp_path/'put','cash_secured_put',**settings)[0]
    second=monthly_signals(tmp_path/'next','covered_call' if assigned else 'cash_secured_put',**settings)[1]
    signals=[first,second];path=natural_path(signals,110 if assigned else 100)
    if assigned:
        for day in path['stocks']['SPY']:
            if '2024-11-20'<=day<'2024-11-29':path['stocks']['SPY'][day]='90'
        identity=first['selection']['legs'][0]['contract']['contract_id']
        path['options'][identity]['2024-11-20']={'bid':'5','ask':'5.1'}
    return signals,path


@pytest.mark.parametrize('assigned,expected',[ (True,101196),(False,100196)])
def test_native_wheel_two_months_delivers_shares_and_cash_without_fake_stock_purchase(tmp_path,assigned,expected):
    signals,path=wheel_inputs(tmp_path,assigned)
    proof=monthly_replay(native_engine_root(),native_dotnet(),tmp_path/'engine',signals,
        initial_cash=100000,fee_per_contract=2,stock_commission_bps=2,execution_path=path,wheel=True)
    assert float(proof['actual_equity'])==expected and float(proof['ledger_bridge']['equity'])==expected
    assert proof['ledger_bridge']['positions']=={} and proof['ledger_bridge']['option_positions']=={}
    assert proof['duplicate_events_added']==0
    events=json.loads((tmp_path/'engine/engine-events.json').read_text())
    assert not any(e['right'] is None and e['order_type']=='MarketOnClose' for e in events)
    receipts=proof['lifecycle_receipts']
    assert [r['kind'] for r in receipts]==(['OPTION_ASSIGNMENT','OPTION_ASSIGNMENT'] if assigned else ['OPTION_EXPIRY','OPTION_EXPIRY'])
    if assigned:assert float(receipts[0]['snapshot']['positions']['SPY'])==100


def test_wheel_prefix_keeps_assigned_stock_until_later_monthly_decision_without_future_signal(tmp_path):
    signals,path=wheel_inputs(tmp_path,True);signals=signals[:1];cutoff='2024-11-25'
    contracts={leg['contract']['contract_id'] for s in signals for leg in s['selection']['legs']}
    path={**path,'stocks':{s:{d:p for d,p in values.items() if d<=cutoff} for s,values in path['stocks'].items()},
          'options':{s:{d:p for d,p in values.items() if d<=cutoff} for s,values in path['options'].items() if s in contracts}}
    proof=monthly_replay(native_engine_root(),native_dotnet(),tmp_path/'prefix',signals,
        initial_cash=100000,fee_per_contract=2,execution_path=path,wheel=True,
        through=cutoff,wheel_end_session='2024-12-19')
    assert float(proof['ledger_bridge']['positions']['SPY'])==100
    assert not proof['ledger_bridge']['option_positions']
    assert float(proof['ledger_bridge']['equity'])==99598
    events=json.loads((tmp_path/'prefix/engine-events.json').read_text())
    assert not any(e['order_type']=='MarketOnClose' and e['right'] is None for e in events)


def test_wheel_wrong_call_candidate_after_unassigned_put_is_not_funded_by_fake_stock(tmp_path):
    from personal_quant.common import QuantError
    signals,path=wheel_inputs(tmp_path,True)
    for day in path['stocks']['SPY']:
        if day<'2024-12-18':path['stocks']['SPY'][day]='100'
    with pytest.raises(QuantError) as error:
        monthly_replay(native_engine_root(),native_dotnet(),tmp_path/'bad',signals,
            initial_cash=100000,fee_per_contract=2,execution_path=path,wheel=True)
    assert error.value.code=='LEAN_REPLAY_FAILED'


def test_native_wheel_insufficient_cash_never_opens_unfunded_put(tmp_path):
    from personal_quant.common import QuantError
    signals,path=wheel_inputs(tmp_path,False)
    with pytest.raises(QuantError) as error:
        monthly_replay(native_engine_root(),native_dotnet(),tmp_path/'cash',signals,
            initial_cash=9000,fee_per_contract=2,execution_path=path,wheel=True)
    assert error.value.code=='LEAN_REPLAY_FAILED'
