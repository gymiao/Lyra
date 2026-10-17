from native_tools import native_engine_root,native_dotnet
import json
import os
from pathlib import Path
import sqlite3
import pandas as pd
import pytest
from personal_quant.options.data import OptionDataStore
from personal_quant.options.replay import fixture_replay
from personal_quant.common import write_json
from personal_quant.config import Config
from personal_quant.workspace.service import create,worker
from test_options_plans_v19 import RISK
from test_options_monthly_replay_v19 import ROOT
from test_stock_preparation_v195 import prepared_inputs


@pytest.fixture(scope='module')
def covered_evidence(tmp_path_factory):
    existing=os.environ.get('LYRAX_TEST_COVERED_POLICY_EVIDENCE')
    templates=['protective_put','covered_call','collar']
    if existing:
        from personal_quant.options.qualification import assess_engine
        assert all(assess_engine(existing,t)['status']=='PASSED' for t in templates)
        return Path(existing)
    root=tmp_path_factory.mktemp('covered-policy-evidence');examples=ROOT/'examples/options';store=OptionDataStore(root/'chains')
    identity=store.save(json.loads((examples/'contracts-engine-fixture.json').read_text()),pd.read_csv(examples/'quotes-engine-fixture.csv'),json.loads((examples/'metadata.json').read_text()))['snapshot_id']
    fixture_replay(native_engine_root(),native_dotnet(),root/'engine',store,identity,
        json.loads((examples/'selection-engine-fixture.json').read_text()),exercise_case=True,templates=templates)
    return root/'engine/verification.json'


@pytest.mark.parametrize('template,equity',[('protective_put',100091.02),('covered_call',100091.02),('collar',100084.02)])
def test_actual_stock_fill_precedes_covered_plan_activation_and_resume(tmp_path,covered_evidence,template,equity):
    signals,path=prepared_inputs(tmp_path/'inputs',template)
    request=tmp_path/'request.json'
    write_json(request,{'signals':signals,'packages':[1,1],'stock_basket':{},'execution_path':path,
        'retain_stock':True,'rolling_end_session':'2025-01-13','prepare_stock':True,
        'plan_policy':{'schema_version':1,'chain_root':str(tmp_path/'inputs/chains'),
            'engine_evidence_files':{template:str(covered_evidence)},
            'risk':{**RISK,'maximum_loss_budget':30000,'maximum_notional':30000},
            'reconciliation_max_days':1,'execution_window_sessions':5}})
    root=tmp_path/'workspace'
    create(root,{'schema_version':1,'account_id':'demo-account','initial_cash':'100000','kind':'options'},Config.load(ROOT/'configs/demo.toml'))
    run=worker(root,'start',input_file=request,engine_root=native_engine_root(),dotnet=native_dotnet(),fee_per_contract=2)
    prepared=worker(root,'step',run['run_id'],'2024-11-01')
    assert prepared['status']=='PAUSED' and prepared['events']==2
    assert float(prepared['details']['equity'])==99998.02
    db=root/'runtime/demo/account.sqlite'
    con=sqlite3.connect(db.as_uri()+'?mode=ro',uri=True)
    assert con.execute('SELECT count(*) FROM option_plans').fetchone()[0]==0
    con.close()
    opened=worker(root,'resume',run['run_id'],'2024-11-04')
    assert opened['status']=='PAUSED' and float(opened['details']['equity'])==equity
    repeat=worker(root,'resume',run['run_id'],'2024-11-04')
    assert repeat['repeated'] and repeat['events']==opened['events']
    con=sqlite3.connect(db.as_uri()+'?mode=ro',uri=True)
    body=json.loads(con.execute('SELECT payload FROM option_plans').fetchone()[0])
    assert body['status']=='FILLED' and body['account_basis']['positions']=={'SPY':'100'}
    assert float(body['account_basis']['equity'])==100098.02
    assert con.execute("SELECT count(*) FROM events WHERE json_extract(payload,'$.kind')='BUY'").fetchone()[0]==1
    assert con.execute("SELECT count(*) FROM tasks WHERE task_id LIKE 'option-activation:%'").fetchone()[0]==1
    con.close()
    closed=worker(root,'resume',run['run_id'],'2025-01-13')
    completed=worker(root,'resume',run['run_id'],'2025-01-14')
    assert completed['status']=='COMPLETED'
    expected=100040.02 if template=='collar' else 100068.02
    assert float(completed['details']['equity'])==expected
    repeated=worker(root,'resume',run['run_id'],'2025-01-14')
    assert repeated['repeated'] and repeated['events']==completed['events']
    con=sqlite3.connect(db.as_uri()+'?mode=ro',uri=True)
    assert con.execute("SELECT count(*) FROM plans WHERE execution_status='FILLED'").fetchone()[0]==2
    assert con.execute("SELECT count(*) FROM events WHERE json_extract(payload,'$.kind') IN ('BUY','SELL') AND json_extract(payload,'$.plan_id')<>''").fetchone()[0]==2
    assert con.execute("SELECT count(*) FROM tasks WHERE task_id LIKE 'option-exit-freeze:%'").fetchone()[0]==2
    exits=[json.loads(r[0]) for r in con.execute("SELECT details FROM tasks WHERE task_id LIKE 'option-exit-simulation:%'")]
    assert len(exits)==2 and all(not e['account']['pending_option_exits'] for e in exits)
    con.close()
