from native_tools import native_engine_root,native_dotnet
import json
from pathlib import Path
import pandas as pd
import pytest
from personal_quant.common import QuantError,digest,write_json
from personal_quant.options.monthly_report import monthly_compare,load_monthly_report,metrics_for
from test_options_monthly_replay_v19 import monthly_signals,ROOT


def test_report_keeps_initial_cost_and_cash_baseline_without_external_flows():
    curve=pd.Series([1000,990,990],index=pd.to_datetime(['2024-01-01','2024-01-02','2024-01-03']))
    m=metrics_for(curve,[],[])
    assert m['total_return']==pytest.approx(-.01) and m['max_drawdown']==pytest.approx(-.01)
    flat=metrics_for(curve*0+1000,[],[])
    assert flat['total_return']==0 and flat['cost']==0 and flat['turnover']==0


def test_old_report_schema_is_rejected_even_with_valid_envelope_hash(tmp_path):
    old={'schema_version':1,'executable':False}
    write_json(tmp_path/'report.json',old)
    manifest={'report_hash':digest(old),'files':{}};manifest['content_hash']=digest(manifest)
    write_json(tmp_path/'manifest.json',manifest)
    with pytest.raises(QuantError,match='旧报告缺少逐日'):
        load_monthly_report(tmp_path)

def test_variable_spread_uses_execution_day_and_does_not_deduct_twice():
    signals=[{'selection':{'legs':[{'contract':{'expiry':'2024-12-18','right':'PUT','strike':95,'contract_id':'put'},
        'reference_quote':{'bid':1,'ask':1.1}}]}}]
    events=[dict(quantity=2,price=1.5,right='PUT',expiry='2024-12-18',strike=95,fee=4,
        utc_time='2024-11-01T20:00:00Z',tag='OPEN',pre_trade_equity=1000),
        dict(quantity=-2,price=1.8,right='PUT',expiry='2024-12-18',strike=95,fee=4,
        utc_time='2024-11-04T21:00:00Z',tag='CLOSE',pre_trade_equity=1056)]
    path={'options':{'put':{'2024-11-01':{'bid':1,'ask':1.5},'2024-11-04':{'bid':1.8,'ask':2.4}}}}
    curve=pd.Series([1000,1052],index=pd.to_datetime(['2024-10-31','2024-11-04']))
    m=metrics_for(curve,events,signals,execution_path=path)
    assert m['bid_ask_cost']==pytest.approx(110) and m['commission']==8
    assert m['option_trading_pnl']==pytest.approx(60) and m['net_trading_pnl']==pytest.approx(52)

def test_variable_path_three_controls_share_data_and_capital(tmp_path):
    from test_options_monthly_path_v19 import execution
    signals=monthly_signals(tmp_path,'protective_put');path,*_=execution(signals)
    directory=tmp_path/'variable-compare'
    report=monthly_compare(native_engine_root(),native_dotnet(),directory,signals,
        initial_cash=100000,fee_per_contract=2,stock_commission_bps=2,
        packages=[2,3],stock_basket={'IEF':50},execution_path=path)
    assert load_monthly_report(directory)==report
    m=report['metrics'];assert set(m)=={'protective_put','stock','cash'}
    assert m['protective_put']['net_trading_pnl']==pytest.approx(642.7416)
    assert m['cash']['total_return']==0 and m['cash']['cost']==0
    assert m['protective_put']['bid_ask_cost']==pytest.approx(50)
    assert report['comparison']['strategy_vs_stock_pnl']==pytest.approx(m['protective_put']['option_trading_pnl']-20)
    assert report['data_type']=='synthetic_variable_path' and report['packages']==[2,3]
    assert report['stock_basket']=={'IEF':50} and report['execution_path_hash']
    curves=pd.read_csv(directory/'equity.csv');assert curves['stock'].nunique()>10


def test_proxy_put_control_keeps_original_basket_without_adding_proxy_shares(tmp_path):
    from personal_quant.common import decimal as D
    from test_options_monthly_path_v19 import execution
    signals=monthly_signals(tmp_path,'long_put',underlying='GLD');path,days,*_=execution(signals)
    path['stocks']['GLD']={str(day.date()):str(D(100)+D(i)*D('.1')) for i,day in enumerate(days)}
    directory=tmp_path/'proxy-basket-compare'
    report=monthly_compare(native_engine_root(),native_dotnet(),directory,signals,
        initial_cash=100000,fee_per_contract=2,stock_commission_bps=2,
        packages=[2,3],stock_basket={'SPY':60,'IEF':50},execution_path=path)
    assert load_monthly_report(directory)==report
    control=json.loads((directory/'stock/verification.json').read_text())
    expected=D(100000);hedge_pnl=D(0)
    for i,cycle in enumerate(control['cycles']):
        assert cycle['stock_positions']=={'SPY':60,'IEF':50} and cycle['underlying_shares']==0
        first=cycle['entry_submit_at'][:10];last=cycle['exit_submit_at'][:10]
        for symbol,quantity in [('SPY',60),('IEF',50)]:
            p1=D(path['stocks'][symbol][first]);p2=D(path['stocks'][symbol][last])
            expected+=quantity*(p2-p1)-quantity*(p1+p2)*D('.0002')
        identity=signals[i]['selection']['legs'][0]['contract']['contract_id'];n=[2,3][i]
        hedge_pnl+=100*n*(D(path['options'][identity][last]['bid'])-D(path['options'][identity][first]['ask']))-4*n
    assert abs(D(control['actual_equity'])-expected)<=D('.01')
    assert report['metrics']['stock']['net_trading_pnl']==pytest.approx(float(expected-D(100000)))
    assert report['comparison']['strategy_vs_stock_pnl']==pytest.approx(float(hedge_pnl))
    events=json.loads((directory/'stock/engine-events.json').read_text())
    assert {e['symbol'] for e in events}=={'SPY','IEF'}


def test_same_engine_monthly_controls_and_report_files(tmp_path,monkeypatch):
    if not (native_dotnet()).is_file():pytest.skip('隔离引擎未安装')
    signals=monthly_signals(tmp_path);directory=tmp_path/'compare'
    report=monthly_compare(native_engine_root(),native_dotnet(),directory,signals,
        initial_cash=100000,fee_per_contract=2,stock_commission_bps=2)
    assert load_monthly_report(directory)==report
    m=report['metrics']
    assert m['collar']['total_return']==pytest.approx(-.00064)
    assert m['stock']['total_return']==pytest.approx(-.00008) and m['cash']['total_return']==0
    assert m['collar']['commission']==24 and m['collar']['bid_ask_cost']==pytest.approx(40)
    assert m['collar']['cost']==pytest.approx(64) and m['stock']['cost']==8 and m['cash']['cost']==0
    curves=pd.read_csv(directory/'equity.csv')
    assert not curves.isna().any().any() and curves.iloc[0]['collar']==100000 and curves.iloc[-1]['collar']==99936
    assert curves.iloc[1]['collar']==99984 and curves.iloc[1]['stock']==99998 and curves.iloc[1]['cash']==100000
    assert report['data_type']=='synthetic_monthly_mechanical' and report['executable'] is False
    import shutil
    from test_backup import scenario
    from personal_quant.portfolio.backup import create_bundle,restore_bundle,verify_bundle
    root,config,_,_=scenario(tmp_path,monkeypatch)
    shutil.copytree(tmp_path/'chains',root/'options/chains')
    shutil.copytree(directory,root/'options/monthly-research/comparison')
    create_bundle(root,config,tmp_path/'bundle')
    references=verify_bundle(tmp_path/'bundle','demo')['references']
    assert references['monthly_option_research_refs']==report['snapshot_ids']
    restore_bundle(tmp_path/'bundle',tmp_path/'restored','demo')
    assert load_monthly_report(tmp_path/'restored'/root/'options/monthly-research/comparison')==report
    from streamlit.testing.v1 import AppTest
    script=tmp_path/'view.py'
    script.write_text('''from pathlib import Path
from personal_quant.config import Config
from personal_quant.portfolio.ledger import Ledger
from personal_quant.ui.v19 import controls
config_path=Path(__CONFIG_PATH__)
book=Ledger('runtime/demo/account.sqlite','demo')
try: controls(book,Config.load(config_path),config_path,'策略研究','2024-07-31T21:00:00Z')
finally: book.close()
'''.replace('__CONFIG_PATH__',repr(str(Path(__file__).resolve().parents[1]/'configs/demo.toml'))))
    app=AppTest.from_file(str(script)).run(timeout=30)
    assert not app.exception and any('合成行情 / 历史重建' in caption.value for caption in app.caption)
    assert len(app.dataframe)>=2
    (directory/'equity.csv').write_text('changed')
    with pytest.raises(QuantError,match='文件缺失或改变'):load_monthly_report(directory)


def test_physical_delivery_cash_is_not_a_market_trade_or_double_premium():
    curve=pd.Series([1000,1050],index=pd.to_datetime(['2024-01-01','2024-01-02']))
    events=[dict(order_type='OptionExercise',right='PUT',quantity=-1,price=0,fee=0),
            dict(order_type='OptionExercise',right=None,quantity=-100,price=95,fee=0)]
    result=metrics_for(curve,events,[])
    assert result['physical_delivery_cash_flow']==9500
    assert result['physical_delivery_notional']==9500
    assert result['turnover']==0 and result['bid_ask_cost']==0
    assert result['option_trading_pnl']==0 and result['stock_trading_pnl']==0


def test_natural_expiry_three_controls_hold_to_same_horizon(tmp_path):
    from test_options_monthly_natural_v19 import natural_path
    signals=monthly_signals(tmp_path,'protective_put')
    directory=tmp_path/'natural-compare'
    report=monthly_compare(native_engine_root(),native_dotnet(),directory,signals,
        initial_cash=100000,fee_per_contract=2,stock_commission_bps=2,
        packages=[1,2],execution_path=natural_path(signals,90),final_lifecycle='natural_expiry')
    assert load_monthly_report(directory)==report
    m=report['metrics']
    # First stock round trip fees4; last buy200@100 fee4, delivery200@95.
    # Total option premium/fees238; delivery incurs no exit commission.
    assert m['protective_put']['net_trading_pnl']==pytest.approx(-1246)
    assert m['protective_put']['physical_delivery_cash_flow']==19000
    assert m['stock']['net_trading_pnl']==pytest.approx(-2011.6)
    assert m['cash']['total_return']==0 and m['cash']['cost']==0
    assert report['comparison']['strategy_vs_stock_pnl']==pytest.approx(765.6)
    proofs=[json.loads((directory/member/'verification.json').read_text()) for member in m]
    assert len({p['evaluation_end'] for p in proofs})==1
    assert all(p['final_lifecycle']=='natural_expiry' for p in proofs)
    stock_events=json.loads((directory/'stock/engine-events.json').read_text())
    assert not any(e['order_type']=='OptionExercise' for e in stock_events)
    assert stock_events[-1]['quantity']==-200
    assert pd.Timestamp(stock_events[-1]['utc_time']).tz_convert('America/New_York').date()==pd.Timestamp(report['as_of']).date()
