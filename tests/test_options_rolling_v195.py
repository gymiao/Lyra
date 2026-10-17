from native_tools import native_engine_root,native_dotnet
import json
import pytest
from test_options_monthly_replay_v19 import monthly_signals,ROOT
from test_options_monthly_natural_v19 import natural_path
from personal_quant.options.monthly_replay import monthly_replay


@pytest.mark.parametrize('name,expected',[('protective_put',99968),('covered_call',99968),('collar',99940)])
def test_rolling_retains_stock_between_cycles_and_only_charges_stock_round_trip_once(tmp_path,name,expected):
    signals=monthly_signals(tmp_path,name);path=natural_path(signals,100)
    path={**path,'stocks':{s:{d:p for d,p in values.items() if d<='2025-01-10'} for s,values in path['stocks'].items()},
          'options':{s:{d:p for d,p in values.items() if d<='2025-01-10'} for s,values in path['options'].items()}}
    proof=monthly_replay(native_engine_root(),native_dotnet(),tmp_path/'engine',signals,
        initial_cash=100000,fee_per_contract=2,stock_commission_bps=2,execution_path=path,retain_stock=True)
    assert float(proof['actual_equity'])==expected and float(proof['ledger_bridge']['equity'])==expected
    events=json.loads((tmp_path/'engine/engine-events.json').read_text())
    stocks=[e for e in events if e['right'] is None]
    assert len(stocks)==2 and [e['quantity'] for e in stocks]==[100,-100]
    assert sum(float(e['fee']) for e in stocks)==4
    assert proof['ledger_bridge']['positions']=={} and proof['duplicate_events_added']==0
    assert any(point['as_of'].startswith('2024-12-02') and float(point['positions'].get('SPY',0))==100 for point in proof['ledger_path'])


def test_rolling_prefix_freezes_end_date_and_preserves_stock_during_option_cash_wait(tmp_path):
    signals=monthly_signals(tmp_path,'collar');path=natural_path(signals,100)
    cutoff='2024-12-02'
    path={**path,'stocks':{s:{d:p for d,p in values.items() if d<=cutoff} for s,values in path['stocks'].items()},
          'options':{s:{d:p for d,p in values.items() if d<=cutoff} for s,values in path['options'].items()}}
    proof=monthly_replay(native_engine_root(),native_dotnet(),tmp_path/'prefix',signals,
        initial_cash=100000,fee_per_contract=2,stock_commission_bps=2,execution_path=path,
        retain_stock=True,rolling_end_session='2025-01-10',through=cutoff)
    assert float(proof['ledger_bridge']['positions']['SPY'])==100 and not proof['ledger_bridge']['option_positions']
    assert float(proof['ledger_bridge']['equity'])==99970
    assert proof['rolling_end_session']=='2025-01-10'


def test_first_known_rolling_signal_needs_no_future_option_prices_or_future_signal(tmp_path):
    signals=monthly_signals(tmp_path,'protective_put')[:1];path=natural_path(signals,100)
    cutoff='2024-11-04'
    path={**path,'stocks':{s:{d:p for d,p in values.items() if d<=cutoff} for s,values in path['stocks'].items()},
          'options':{s:{d:p for d,p in values.items() if d<=cutoff} for s,values in path['options'].items()}}
    proof=monthly_replay(native_engine_root(),native_dotnet(),tmp_path/'first',signals,
        initial_cash=100000,fee_per_contract=2,stock_commission_bps=2,execution_path=path,
        retain_stock=True,rolling_end_session='2025-01-10',through=cutoff)
    assert float(proof['ledger_bridge']['positions']['SPY'])==100
    assert len(proof['ledger_bridge']['option_positions'])==1
    assert float(proof['ledger_bridge']['equity'])==99991


def test_rolling_comparison_preserves_fair_hold_policy_and_decomposes_cost(tmp_path):
    from personal_quant.options.monthly_report import monthly_compare,load_monthly_report
    signals=monthly_signals(tmp_path,'collar');path=natural_path(signals,100)
    path={**path,'stocks':{s:{d:p for d,p in values.items() if d<='2025-01-10'} for s,values in path['stocks'].items()},
          'options':{s:{d:p for d,p in values.items() if d<='2025-01-10'} for s,values in path['options'].items()}}
    output=tmp_path/'compare'
    report=monthly_compare(native_engine_root(),native_dotnet(),output,signals,
        initial_cash=100000,fee_per_contract=2,stock_commission_bps=2,execution_path=path,retain_stock=True)
    assert load_monthly_report(output)==report
    assert report['policy']['retain_stock'] is True
    assert report['metrics']['collar']['net_trading_pnl']==pytest.approx(-60)
    assert report['metrics']['stock']['net_trading_pnl']==pytest.approx(-4)
    assert report['metrics']['cash']['net_trading_pnl']==0
    assert report['comparison']['strategy_vs_stock_pnl']==pytest.approx(-56)
