from native_tools import native_engine_root,native_dotnet
import importlib.util
import json
from pathlib import Path
from personal_quant.options.monthly_replay import monthly_replay

ROOT=Path(__file__).resolve().parents[1]


def test_native_prefix_keeps_open_positions_and_matches_independent_cash(tmp_path):
    spec=importlib.util.spec_from_file_location('monthly_test',ROOT/'tests/test_options_monthly_replay_v19.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    signal=module.monthly_signals(tmp_path)[0]
    proof=monthly_replay(native_engine_root(),native_dotnet(),tmp_path/'native',
        [signal],initial_cash=100000,fee_per_contract=2,through='2024-11-04')
    state=proof['ledger_bridge']
    assert state['positions']=={'SPY':'100.0'} or float(state['positions']['SPY'])==100
    assert len(state['option_positions'])==2
    assert abs(float(state['equity'])-99986)<.01
    assert proof['duplicate_events_added']==0
    events=json.loads((tmp_path/'native/engine-events.json').read_text())
    assert len(events)==3 and all(e['tag'].endswith('|OPEN') for e in events)


def test_variable_prefix_does_not_need_future_execution_prices(tmp_path):
    request=json.loads((ROOT/'examples/options/monthly-variable-path.json').read_text())
    first=request['signals'][0];cutoff='2024-11-04'
    ids={leg['contract']['contract_id'] for leg in first['selection']['legs']}
    path=request['execution_path']
    clipped={**path,'stocks':{s:{d:p for d,p in rows.items() if d<=cutoff} for s,rows in path['stocks'].items()},
             'options':{s:{d:p for d,p in rows.items() if d<=cutoff} for s,rows in path['options'].items() if s in ids}}
    proof=monthly_replay(native_engine_root(),native_dotnet(),tmp_path/'variable',
        [first],initial_cash=100000,fee_per_contract=2,stock_commission_bps=2,
        packages=[2],stock_basket=request['stock_basket'],execution_path=clipped,through=cutoff)
    assert abs(float(proof['ledger_bridge']['equity'])-99994.5)<.01
    assert float(proof['ledger_bridge']['positions']['SPY'])==200
    assert proof['evaluation_end']==cutoff
