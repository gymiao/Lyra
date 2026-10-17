from native_tools import native_engine_root,native_dotnet
import json
import pytest
from personal_quant.options.monthly_replay import monthly_replay
from test_options_monthly_replay_v19 import monthly_signals,ROOT
from test_options_monthly_natural_v19 import natural_path


def prepared_inputs(tmp_path,template='protective_put'):
    signals=monthly_signals(tmp_path,template);path=natural_path(signals,100)
    path={**path,'stocks':{s:{d:('99' if d=='2024-11-01' else p) for d,p in values.items() if d<='2025-01-13'} for s,values in path['stocks'].items()},
          'options':{s:{d:p for d,p in values.items() if d<='2025-01-13'} for s,values in path['options'].items()}}
    return signals,path


@pytest.mark.parametrize('template,expected',[('protective_put',100068.02),('covered_call',100068.02),('collar',100040.02)])
def test_native_prepares_stock_before_options_and_uses_actual_stock_purchase_day(tmp_path,template,expected):
    signals,path=prepared_inputs(tmp_path,template)
    proof=monthly_replay(native_engine_root(),native_dotnet(),tmp_path/'engine',signals,
        initial_cash=100000,fee_per_contract=2,stock_commission_bps=2,execution_path=path,
        retain_stock=True,prepare_stock=True)
    # Buy 100 at 99, sell at 100: $100 profit less $3.98 stock fees;
    # two option round trips cost $28 per option leg.
    assert float(proof['actual_equity'])==expected and float(proof['expected_equity'])==expected
    assert float(proof['ledger_bridge']['equity'])==expected
    events=json.loads((tmp_path/'engine/engine-events.json').read_text())
    stock_buys=[e for e in events if e['right'] is None and e['quantity']>0]
    assert len(stock_buys)==1 and stock_buys[0]['utc_time'].startswith('2024-11-01')
    options=[e for e in events if e['right'] is not None and e['tag'].endswith('|OPEN')]
    assert options[0]['utc_time'].startswith('2024-11-04')
    assert next(e for e in events if e['right'] is None and e['quantity']<0)['utc_time'].startswith('2025-01-13')
    assert proof['duplicate_events_added']==0 and proof['ledger_bridge']['positions']=={}


def test_preparation_prefix_contains_only_stock_before_option_entry(tmp_path):
    signals,path=prepared_inputs(tmp_path);signals=signals[:1]
    contracts={leg['contract']['contract_id'] for s in signals for leg in s['selection']['legs']}
    path={**path,'stocks':{s:{d:p for d,p in vs.items() if d=='2024-11-01'} for s,vs in path['stocks'].items()},
          'options':{s:{d:p for d,p in vs.items() if d=='2024-11-01'} for s,vs in path['options'].items() if s in contracts}}
    proof=monthly_replay(native_engine_root(),native_dotnet(),tmp_path/'engine',signals,
        initial_cash=100000,fee_per_contract=2,stock_commission_bps=2,execution_path=path,
        retain_stock=True,prepare_stock=True,rolling_end_session='2025-01-13',through='2024-11-01')
    assert float(proof['ledger_bridge']['positions']['SPY'])==100
    assert proof['ledger_bridge']['option_positions']=={}
    assert float(proof['ledger_bridge']['equity'])==99998.02
    events=json.loads((tmp_path/'engine/engine-events.json').read_text())
    assert len(events)==1 and events[0]['tag'].endswith('|PREPARE_STOCK')


def test_preparation_comparison_uses_same_actual_stock_entry_for_all_controls(tmp_path):
    from personal_quant.options.monthly_report import monthly_compare,load_monthly_report
    signals,path=prepared_inputs(tmp_path,'collar');destination=tmp_path/'compare'
    report=monthly_compare(native_engine_root(),native_dotnet(),destination,signals,
        initial_cash=100000,fee_per_contract=2,stock_commission_bps=2,execution_path=path,
        retain_stock=True,prepare_stock=True)
    assert load_monthly_report(destination)==report
    assert report['policy']['prepare_stock'] is True
    assert report['metrics']['collar']['net_trading_pnl']==pytest.approx(40.02)
    assert report['metrics']['stock']['net_trading_pnl']==pytest.approx(96.02)
    assert report['metrics']['cash']['net_trading_pnl']==0
    assert report['comparison']['strategy_vs_stock_pnl']==pytest.approx(-56)
