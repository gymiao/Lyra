from native_tools import native_engine_root,native_dotnet
import json
import pytest
from personal_quant.common import decimal as D
from personal_quant.options.monthly_replay import monthly_replay
from test_options_monthly_replay_v19 import monthly_signals, ROOT
from test_options_monthly_natural_v19 import natural_path


@pytest.mark.parametrize('template,spot,expected,kind', [
    ('protective_put',90,99372,'OPTION_EXERCISE'),
    ('covered_call',110,100582,'OPTION_ASSIGNMENT'),
    ('collar',90,99456,'OPTION_EXERCISE'),
    ('collar',110,100456,'OPTION_ASSIGNMENT'),
    ('collar',100,99954,'OPTION_EXPIRY'),
])
def test_retained_stock_natural_delivery_cash_and_shares(tmp_path,template,spot,expected,kind):
    # One $10,000 stock purchase + $2 fee. First cycle costs $14 per option
    # leg; last cycle pays put $112 / receives call $98. ITM delivery receives
    # strike cash $9,500 or $10,500, otherwise stock sale receives $9,998.
    signals=monthly_signals(tmp_path,template)
    out=tmp_path/'engine'
    proof=monthly_replay(native_engine_root(),native_dotnet(),out,signals,
        initial_cash=100000,fee_per_contract=2,stock_commission_bps=2,
        execution_path=natural_path(signals,spot),retain_stock=True,
        final_lifecycle='natural_expiry')
    assert D(proof['expected_equity'])==expected
    assert D(proof['actual_equity'])==expected
    assert D(proof['ledger_bridge']['equity'])==expected
    assert proof['ledger_bridge']['positions']=={}
    assert proof['ledger_bridge']['option_positions']=={}
    assert proof['ledger_bridge']['anomalies']==[]
    assert proof['duplicate_events_added']==0
    native=json.loads((out/'engine-events.json').read_text())
    stock_orders=[e for e in native if e['right'] is None and e['order_type']=='MarketOnClose']
    assert [e['quantity'] for e in stock_orders]==([100,-100] if spot==100 else [100])
    assert any(r['kind']==kind for r in proof['lifecycle_receipts'])
    assert all(r['check_status']=='CHECKED' for r in proof['lifecycle_receipts'])


def test_retained_natural_workspace_restart_settles_once(tmp_path):
    from personal_quant.common import write_json
    from personal_quant.config import Config
    from personal_quant.workspace.service import create,worker,status
    signals=monthly_signals(tmp_path/'signals','collar')
    path=natural_path(signals,90)
    request=tmp_path/'request.json'
    write_json(request,{'signals':signals,'packages':[1,1],'stock_basket':{},
        'execution_path':path,'retain_stock':True,'rolling_end_session':'2025-01-21',
        'final_lifecycle':'natural_expiry'})
    root=tmp_path/'workspace'
    create(root,{'schema_version':1,'account_id':'demo-account','initial_cash':'100000','kind':'options'},Config.load(ROOT/'configs/demo.toml'))
    started=worker(root,'start',input_file=request,engine_root=native_engine_root(),dotnet=native_dotnet(),fee_per_contract=2)
    first=worker(root,'step',started['run_id'],'2024-11-04')
    assert first['status']=='PAUSED'
    expired=worker(root,'resume',started['run_id'],'2025-01-17')
    assert expired['details']['lifecycle_receipts']
    assert expired['status']=='PAUSED'  # Delivery proceeds are not settled cash.
    done=worker(root,'resume',started['run_id'],'2025-01-21')
    assert done['status']=='COMPLETED'
    assert D(done['details']['equity'])==99456
    repeated=worker(root,'resume',started['run_id'],'2025-01-21')
    assert repeated['repeated'] and repeated['events']==done['events']
    assert status(root)['events']==done['events']


def test_natural_rolling_comparison_uses_same_stock_holding_and_terminal_date(tmp_path):
    from personal_quant.options.monthly_report import monthly_compare,load_monthly_report
    signals=monthly_signals(tmp_path,'covered_call')
    root=tmp_path/'comparison'
    report=monthly_compare(native_engine_root(),native_dotnet(),root,signals,
        initial_cash=100000,fee_per_contract=2,stock_commission_bps=2,
        execution_path=natural_path(signals,110),retain_stock=True,final_lifecycle='natural_expiry')
    assert load_monthly_report(root)==report
    assert report['policy']['retain_stock'] is True
    assert report['policy']['final_lifecycle']=='natural_expiry'
    assert report['metrics']['covered_call']['net_trading_pnl']==pytest.approx(582)
    # $1,000 stock appreciation less buy $2 / sale $2.20 fees.
    assert report['metrics']['stock']['net_trading_pnl']==pytest.approx(995.8)
    assert report['metrics']['cash']['net_trading_pnl']==0
    assert report['comparison']['strategy_vs_stock_pnl']==pytest.approx(-413.8)
