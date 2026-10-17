from native_tools import native_engine_root,native_dotnet
import json
import os
import time
from pathlib import Path
import pytest
from personal_quant.common import decimal as D
from personal_quant.config import Config
from personal_quant.portfolio import Ledger
from personal_quant.portfolio.backup import create_bundle,restore_bundle
from personal_quant.workspace.service import create,worker
from personal_quant.workspace.option_setup import prepare
from personal_quant.workspace.jobs import launch,list_jobs
from test_stock_preparation_workspace_v195 import covered_evidence
from test_options_plans_v19 import RISK

ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('public,exit_days',[(False,7),(True,6)])
def test_frozen_ui_recipe_runs_and_public_recipe_restores_relative_sources(tmp_path,monkeypatch,public,exit_days,covered_evidence):
    root=tmp_path/'workspace'
    create(root,{'schema_version':1,'kind':'options','account_id':'demo-account','initial_cash':'100000'},Config.load(ROOT/'configs/demo.toml'))
    spec=json.loads((ROOT/'configs/v195-option-setup.json').read_text());spec['selection_parameters']['exit_days_before_expiry']=exit_days
    if public:spec['plan_policy']={'risk':{**RISK,'maximum_notional':30000,'maximum_loss_budget':30000},
        'engine_evidence_file':str(covered_evidence),'reconciliation_max_days':1,'execution_window_sessions':5}
    prepared=prepare(root,spec)
    if public:
        # No run exists yet. Restoration must retain the chain/evidence paths
        # without relying on the source workspace or issuing another deposit.
        monkeypatch.chdir(root);create_bundle(root/'runtime/demo',root/'config.json',tmp_path/'bundle')
        recovered=tmp_path/'recovered';restore_bundle(tmp_path/'bundle',recovered,'demo')
        directory=recovered/'runtime/demo/simulation/setups'/prepared['setup_id']
        request=json.loads((directory/'request.json').read_text())
        assert not Path(request['plan_policy']['chain_root']).is_absolute()
        assert all(not Path(v).is_absolute() for v in request['plan_policy']['engine_evidence_files'].values())
        root=recovered;prepared['request_file']=str(directory/'request.json')
    engine=Path(os.environ.get('LYRAX_TEST_ENGINE_ROOT',str(native_engine_root())))
    dotnet=Path(os.environ.get('LYRAX_TEST_DOTNET',str(native_dotnet())))
    if public:run=worker(root,'start',input_file=prepared['request_file'],engine_root=engine,dotnet=dotnet,fee_per_contract=2)
    else:
        ids=[]
        for _ in range(2):
            job=launch(root,'start',input_file=prepared['request_file'],engine_root=engine,dotnet=dotnet,fee_per_contract=2)
            deadline=time.monotonic()+120
            while time.monotonic()<deadline:
                observed=next(row for row in list_jobs(root) if row['job_id']==job['job_id'])
                if observed['status']!='RUNNING':break
                time.sleep(.1)
            assert observed['status']=='SUCCESS',observed
            run=observed['result'];ids.append(run['run_id'])
        assert ids[0]==ids[1]
    first=worker(root,'step',run['run_id'],'2024-11-01');assert first['events']==2
    worker(root,'resume',run['run_id'],prepared['last_market_session'])
    final=worker(root,'resume',run['run_id'],prepared['last_settlement_session'])
    # Stock is unchanged, two option round trips lose $5 spread + $4 fees
    # each; stock commissions cost $4. $100000 - 2*9 - 4 = $99978.
    assert final['status']=='COMPLETED' and final['events']==7 and D(final['details']['equity'])==D('99978')
    assert worker(root,'resume',run['run_id'],prepared['last_settlement_session'])['repeated']
    book=Ledger.read_only(root/'runtime/demo/account.sqlite','demo')
    assert book.connection.execute('SELECT count(*) FROM option_plans').fetchone()[0]==(2 if public else 0)
    assert book.connection.execute("SELECT count(*) FROM events WHERE json_extract(payload,'$.kind')='DEPOSIT'").fetchone()[0]==1
    book.close()
