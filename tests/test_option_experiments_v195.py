from native_tools import native_engine_root,native_dotnet
"""Independent native accounts with matched inputs and predeclared variants."""
import json
import os
from pathlib import Path
import shutil
import sqlite3
import pytest
from personal_quant.common import QuantError,write_json
from personal_quant.config import Config
from personal_quant.portfolio import Ledger
from personal_quant.workspace.service import create,worker
from personal_quant.workspace.experiments import compare,curve
from test_stock_preparation_v195 import prepared_inputs

ROOT=Path(__file__).resolve().parents[1]


def build_experiments(tmp_path_factory):
    existing=os.environ.get('LYRAX_TEST_OPTION_EXPERIMENTS')
    if existing:
        saved=json.loads(Path(existing).read_text())
        return {name:{key:value for key,value in entry.items() if key in {'name','workspace','run_id'}} for name,entry in saved.items()}
    base=tmp_path_factory.mktemp('independent-option-experiments')
    signals,path=prepared_inputs(base/'inputs','protective_put')
    engine=Path(os.environ.get('LYRAX_TEST_ENGINE_ROOT',str(native_engine_root())))
    dotnet=Path(os.environ.get('LYRAX_TEST_DOTNET',str(native_dotnet())))
    assert (engine/'Launcher/bin/Release/QuantConnect.Lean.Launcher.dll').is_file() and dotnet.is_file()
    result={}
    # Fixed before observing outcomes: size1, size2, and the same size1 at fee3.
    for name,packages,fee,equity in [('size1',1,2,100068.02),('size2',2,2,100136.04),('fee3',1,3,100064.02)]:
        workspace=base/name;request=base/(name+'.json')
        write_json(request,{'signals':signals,'packages':[packages,packages],'stock_basket':{},'execution_path':path,
            'retain_stock':True,'prepare_stock':True,'rolling_end_session':'2025-01-13'})
        create(workspace,{'schema_version':1,'account_id':'demo-account','initial_cash':'100000','kind':'options'},Config.load(ROOT/'configs/demo.toml'))
        started=worker(workspace,'start',input_file=request,engine_root=engine,dotnet=dotnet,fee_per_contract=fee)
        worker(workspace,'resume',started['run_id'],'2025-01-13')
        done=worker(workspace,'resume',started['run_id'],'2025-01-14')
        assert done['status']=='COMPLETED' and done['events']==7 and float(done['details']['equity'])==equity
        result[name]={'name':name,'workspace':str(workspace),'run_id':started['run_id']}
    return result


@pytest.fixture(scope='module')
def experiments(option_experiment_cases):
    return option_experiment_cases


def test_native_size_variants_compare_same_capital_without_double_counting_spread(experiments):
    request=[experiments[name] for name in ['size1','size2']]
    result=compare(request)
    assert result['read_only'] and result['status']=='PASSED' and result['policy']['engine']=='LEAN'
    assert result['metrics']['size1']['total_return']==pytest.approx(.0006802)
    assert result['metrics']['size2']['total_return']==pytest.approx(.0013604)
    first=result['execution']['size1'];second=result['execution']['size2']
    assert first['commission']==pytest.approx(11.98) and second['commission']==pytest.approx(23.96)
    assert first['bid_ask_cost']==pytest.approx(20) and second['bid_ask_cost']==pytest.approx(40)
    assert first['net_trading_pnl']==pytest.approx(68.02) and second['net_trading_pnl']==pytest.approx(136.04)
    # Net PnL already includes the $20 paid across bid/ask. Subtracting it again
    # would incorrectly claim $48.02 rather than the independently known $68.02.
    assert list(result['curves']['size1'].values())[0]==100000
    assert list(result['curves']['size1'].values())[-1]==100068.02
    assert result['metrics']['size1']['short_sample_annualization'] is True


def test_different_actual_fee_policy_and_duplicate_account_are_rejected(experiments):
    with pytest.raises(QuantError) as caught:compare([experiments['size1'],experiments['fee3']])
    assert caught.value.code=='INCOMPARABLE_EXPERIMENT' and 'option_fee_per_contract' in str(caught.value)
    with pytest.raises(QuantError) as caught:compare([experiments['size1'],{**experiments['size1'],'name':'same-account-again'}])
    assert caught.value.code=='DUPLICATE_EXPERIMENT'


def test_late_fee_invalidates_old_curve_and_missing_proof_is_not_silently_accepted(experiments,tmp_path):
    original=experiments['size1'];root=tmp_path/'late-fee';shutil.copytree(original['workspace'],root)
    book=Ledger(root/'runtime/demo/account.sqlite','demo')
    book.import_events('demo-account',[{'event_id':'late-fee','kind':'FEE','amount':'3','effective_at':'2024-11-04T21:00:00Z',
        'source':'independent_test_statement','evidence_type':'test'}]);book.close()
    with pytest.raises(QuantError) as caught:curve(root,original['run_id'])
    assert caught.value.code=='STALE_EXPERIMENT'
    clean=tmp_path/'missing-proof';shutil.copytree(original['workspace'],clean)
    archive=clean/'runtime/demo/simulation/options'/original['run_id']/'tool-manifest.json'
    archive.unlink()
    with pytest.raises((QuantError,OSError)):curve(clean,original['run_id'])


def test_readonly_projector_refuses_writes_and_keeps_account_facts(experiments):
    entry=experiments['size1'];book=Ledger.read_only(Path(entry['workspace'])/'runtime/demo/account.sqlite','demo')
    assert book.sequence('demo-account')==7
    with pytest.raises(sqlite3.OperationalError):book.connection.execute("DELETE FROM events")
    assert book.sequence('demo-account')==7;book.close()


def test_changed_raw_fee_receipt_is_rejected_against_exact_bridge_fact(experiments,tmp_path):
    entry=experiments['size1'];root=tmp_path/'changed-native';shutil.copytree(entry['workspace'],root)
    directory=root/'runtime/demo/simulation/options'/entry['run_id']
    con=sqlite3.connect(root/'runtime/demo/account.sqlite')
    details=[json.loads(r[0]) for r in con.execute('SELECT details FROM simulation_checkpoints ORDER BY session DESC')];con.close()
    reference=next(d['native_proof'] for d in details if 'native_proof' in d)
    file=root/'runtime/demo'/reference/'engine-events.json';events=json.loads(file.read_text())
    events[0]['price']=float(events[0]['price'])+1
    file.write_text(json.dumps(events))
    with pytest.raises(QuantError) as caught:curve(root,entry['run_id'])
    assert caught.value.code=='CORRUPT_EXPERIMENT' and '桥接事实不同' in str(caught.value)
