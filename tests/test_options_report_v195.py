from native_tools import native_engine_root,native_dotnet
import pytest
from test_options_monthly_replay_v19 import monthly_signals,ROOT
from test_options_monthly_natural_v19 import natural_path
from personal_quant.options.monthly_report import monthly_compare,load_monthly_report


@pytest.mark.parametrize('name,lifecycle,expected,fees',[
    ('bull_put_credit_spread',None,-56,16),
    ('long_straddle','natural_expiry_with_delivery_exit',746,14)])
def test_extended_report_loads_and_matches_fair_controls_and_independent_costs(tmp_path,name,lifecycle,expected,fees):
    signals=monthly_signals(tmp_path,name)
    path=natural_path(signals,90) if lifecycle else None
    directory=tmp_path/'compare'
    report=monthly_compare(native_engine_root(),native_dotnet(),directory,signals,
        initial_cash=100000,fee_per_contract=2,stock_commission_bps=0,
        execution_path=path,final_lifecycle=lifecycle)
    assert load_monthly_report(directory)==report
    assert set(report['metrics'])=={name,'stock','cash'}
    assert report['metrics'][name]['net_trading_pnl']==pytest.approx(expected)
    assert report['metrics'][name]['commission']==fees
    assert report['metrics']['cash']['net_trading_pnl']==0
    assert report['metrics']['cash']['total_return']==0 and not report['executable']
    if lifecycle:assert any('显式交割政策' in text for text in report['assumptions'])
    else:assert report['metrics'][name]['cost']==pytest.approx(56)
