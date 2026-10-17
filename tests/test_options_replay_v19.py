from native_tools import native_engine_root,native_dotnet
from pathlib import Path
import json
import pandas as pd
import pytest
from personal_quant.common import QuantError
from personal_quant.options.data import OptionDataStore
from personal_quant.options.replay import fixture_replay,upstream_config

ROOT=Path(__file__).resolve().parents[1]


def test_lean_close_orders_use_close_quote_not_submission_quote(tmp_path):
    if not (native_dotnet()).is_file():pytest.skip('隔离LEAN/SDK尚未安装')
    examples=ROOT/'examples/options';store=OptionDataStore(tmp_path/'chains')
    identity=store.save(json.loads((examples/'contracts-engine-fixture.json').read_text()),
        pd.read_csv(examples/'quotes-engine-fixture.csv'),json.loads((examples/'metadata.json').read_text()))['snapshot_id']
    result=fixture_replay(native_engine_root(),native_dotnet(),tmp_path/'engine',store,identity,
        json.loads((examples/'selection-engine-fixture.json').read_text()),fee_per_contract=2,market_on_close=True)
    events=json.loads((tmp_path/'engine/long_call/engine-events.json').read_text())
    assert len(result['cases'])==10 and len(events)==2
    assert float(events[0]['price'])==2.3 and float(events[1]['price'])==2.2
    assert events[0]['utc_time'].startswith('2024-10-10T20:00:00')
    assert float(result['cases']['long_call']['actual_equity'])==99986


def test_official_json_comments_preserve_urls_and_quoted_comment_text(tmp_path):
    path=tmp_path/'config.json';path.write_text('{/*comment*/"url":"https://example.test/a",//line\n"text":"/* literal */",}')
    assert upstream_config(path)=={'url':'https://example.test/a','text':'/* literal */'}


def test_lean_a8_standard_fixture_round_trips_match_hand_cash_bridge(tmp_path):
    if not (native_dotnet()).is_file():pytest.skip('隔离LEAN/SDK尚未安装，不能声称引擎验收')
    examples=ROOT/'examples/options';store=OptionDataStore(tmp_path/'chains')
    identity=store.save(json.loads((examples/'contracts-engine-fixture.json').read_text()),
        pd.read_csv(examples/'quotes-engine-fixture.csv'),json.loads((examples/'metadata.json').read_text()))['snapshot_id']
    result=fixture_replay(native_engine_root(),native_dotnet(),tmp_path/'engine',store,identity,
        json.loads((examples/'selection-engine-fixture.json').read_text()),initial_cash=100000,fee_per_contract=2,exercise_case=True)
    assert result['status']=='PASSED' and result['no_user_account_writes']
    for key in ['long_call','long_put','protective_put','covered_call','cash_secured_put']:
        assert float(result['cases'][key]['actual_equity'])==99986
    for key in ['collar','bull_call_debit_spread','bear_put_debit_spread']:
        assert float(result['cases'][key]['actual_equity'])==99972
    for key in ['benchmark_stock','benchmark_cash']:
        assert float(result['cases'][key]['actual_equity'])==100000
    assert float(result['cases']['protective_put_exercise']['actual_equity'])==99388
    bridge=result['cases']['protective_put_exercise']['ledger_bridge']
    assert bridge['positions']=={} and bridge['option_positions']=={} and float(bridge['investment_pnl'])==-612
    assignment=result['cases']['covered_call_assignment']['ledger_bridge']
    assert float(assignment['equity'])==100598 and assignment['positions']=={} and assignment['option_positions']=={}
    put=result['cases']['cash_put_assignment']['ledger_bridge']
    assert float(put['settled_cash'])==90598 and put['positions']=={'SPY':'100'}
    assert float(put['equity'])==99098 and put['option_positions']=={}
    expiry=result['cases']['long_put_worthless_expiry']['ledger_bridge']
    assert float(expiry['equity'])==99788 and expiry['option_positions']=={} and expiry['positions']=={}
    short_expiry=result['cases']['cash_put_worthless_expiry']['ledger_bridge']
    assert float(short_expiry['equity'])==100098 and short_expiry['option_positions']=={} and short_expiry['positions']=={}
    assert short_expiry['option_cash_collateral']=='0' and float(short_expiry['investment_pnl'])==98
    events=json.loads((tmp_path/'engine/cash_put_worthless_expiry/engine-events.json').read_text())
    assert len(events)==2 and events[-1]['order_type']=='OptionExercise' and events[-1]['in_the_money'] is False
    spread=result['cases']['bull_call_partial_assignment']['ledger_bridge']
    assert float(spread['equity'])==100386 and spread['positions']=={} and spread['option_positions']=={}
    path=result['cases']['bull_call_partial_assignment']['ledger_lifecycle_path']
    assert path[0]['snapshot']['positions']=={'SPY':'-100'}
    assert path[0]['snapshot']['anomalies'] and path[0]['snapshot']['equity'] is None
    assert float(path[0]['snapshot']['settled_cash'])==110386
    assert path[1]['snapshot']['positions']=={} and path[1]['snapshot']['anomalies']==[]
    assert path[0]['snapshot']['as_of'][:10] < path[1]['snapshot']['as_of'][:10]
    import zipfile,hashlib
    for name,case in result['cases'].items():
        directory=tmp_path/'engine'/name
        manifest=json.loads((directory/'data-files.json').read_text())
        for relative,identity in manifest.items():
            assert hashlib.sha256((Path(case['data_root'])/relative).read_bytes()).hexdigest()==identity
    # Later lifecycle shocks must not revise the ordinary strategy execution data.
    day=result['exit_session'].replace('-','')
    with zipfile.ZipFile(Path(result['cases']['covered_call']['data_root'])/'equity/usa/minute/spy'/(day+'_trade.zip')) as stream:
        row=stream.read(stream.namelist()[0]).decode().split(',')
        assert int(row[4])==1000000
    from personal_quant.options.qualification import assess_engine
    csp=assess_engine(tmp_path/'engine/verification.json','cash_secured_put')
    assert csp['status']=='PASSED' and not csp['executable'] and not csp['source_qualified']
    covered=assess_engine(tmp_path/'engine/verification.json','covered_call')
    assert covered['status']=='PASSED' and not covered['executable']
    assert assess_engine(tmp_path/'engine/verification.json','protective_put')['status']=='PASSED'
    assert assess_engine(tmp_path/'engine/verification.json','long_call')['status']=='PASSED'
    assert len(result['cases'])==27
    assert assess_engine(tmp_path/'engine/verification.json','long_put')['status']=='PASSED'
    assert assess_engine(tmp_path/'engine/verification.json','bull_call_debit_spread')['status']=='PASSED'
    for template in ['bear_put_debit_spread','collar']:
        assert assess_engine(tmp_path/'engine/verification.json',template)['status']=='PASSED'
    for name,equity in [('bear_put_partial_assignment',100386),('collar_call_assignment',100486),('collar_put_exercise',99482)]:
        state=result['cases'][name]['ledger_bridge']
        assert float(state['equity'])==equity and float(state['settled_cash'])==equity
        assert state['positions']=={} and state['option_positions']=={} and state['option_covered_shares']=={}
    bear=result['cases']['bear_put_partial_assignment']['ledger_lifecycle_path']
    assert bear[0]['snapshot']['positions']=={'SPY':'100'} and float(bear[0]['snapshot']['settled_cash'])==90386
    assert bear[0]['snapshot']['equity'] is None and bear[1]['snapshot']['positions']=={}
    for name,equity in [('bull_call_worthless_expiry',99886),('bear_put_worthless_expiry',99886),('long_put_itm_exit',100786)]:
        state=result['cases'][name]['ledger_bridge']
        assert float(state['equity'])==equity and float(state['settled_cash'])==equity
        assert state['positions']=={} and state['option_positions']=={} and state['option_covered_shares']=={}
        assert float(state['option_cash_collateral'])==0
    collar=result['cases']['collar_worthless_expiry']['ledger_bridge']
    assert float(collar['equity'])==99986 and float(collar['settled_cash'])==89986
    assert collar['positions']=={'SPY':'100'} and collar['option_positions']=={} and collar['option_covered_shares']=={}
    for name,equity,cash in [('covered_call_worthless_expiry',99598,90098),
        ('protective_put_worthless_expiry',100388,89888),('long_call_exercise',100788,89788)]:
        state=result['cases'][name]['ledger_bridge']
        assert float(state['equity'])==equity and float(state['settled_cash'])==cash
        assert state['positions']=={'SPY':'100'} and state['option_positions']=={}
        assert float(state['option_cash_collateral'])==0
    long_expiry=result['cases']['long_call_worthless_expiry']['ledger_bridge']
    assert float(long_expiry['equity'])==99788 and long_expiry['positions']=={} and long_expiry['option_positions']=={}
    path=tmp_path/'engine/cash_put_worthless_expiry/ledger-bridge.json'
    original=path.read_text();body=json.loads(original);body['settled_cash']='200000';path.write_text(json.dumps(body))
    try:assert assess_engine(tmp_path/'engine/verification.json','cash_secured_put')['status']=='BLOCKED'
    finally:path.write_text(original)
