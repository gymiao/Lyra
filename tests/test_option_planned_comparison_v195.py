from native_tools import native_engine_root,native_dotnet
import json
import os
from pathlib import Path
import pytest
from personal_quant.common import write_json
from personal_quant.config import Config
from personal_quant.portfolio import Ledger
from personal_quant.workspace.service import create,worker
from personal_quant.workspace.experiments import compare
from test_stock_preparation_v195 import prepared_inputs
from test_stock_preparation_workspace_v195 import covered_evidence
from test_options_plans_v19 import RISK

ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('incremental',[False,True])
def test_public_plan_and_schedule_accounts_share_verified_curve_without_mutating_resources(tmp_path,covered_evidence,incremental):
    signals,path=prepared_inputs(tmp_path/'inputs','protective_put')
    engine=Path(os.environ.get('LYRAX_TEST_ENGINE_ROOT',str(native_engine_root())))
    dotnet=Path(os.environ.get('LYRAX_TEST_DOTNET',str(native_dotnet())))
    request=[]
    for name,planned in [('public-plans',True),('research-schedule',False)]:
        body={'signals':signals,'packages':[1,1],'stock_basket':{},'execution_path':path,
            'retain_stock':True,'rolling_end_session':'2025-01-13','prepare_stock':True}
        if planned:
            body['plan_policy']={'schema_version':1,'chain_root':str(tmp_path/'inputs/chains'),
                'engine_evidence_files':{'protective_put':str(covered_evidence)},
                'risk':{**RISK,'maximum_loss_budget':30000,'maximum_notional':30000},
                'reconciliation_max_days':1,'execution_window_sessions':5}
        file=tmp_path/(name+'.json');write_json(file,body);root=tmp_path/name
        create(root,{'schema_version':1,'kind':'options','account_id':'demo-account','initial_cash':'100000'},Config.load(ROOT/'configs/demo.toml'))
        start=worker(root,'start',input_file=file,engine_root=engine,dotnet=dotnet,fee_per_contract=2)
        if incremental and planned:
            assert worker(root,'step',start['run_id'],'2024-11-01')['events']==2
            assert worker(root,'resume',start['run_id'],'2024-11-04')['events']==3
        worker(root,'resume',start['run_id'],'2025-01-13');done=worker(root,'resume',start['run_id'],'2025-01-14')
        assert done['status']=='COMPLETED' and done['events']==7 and float(done['details']['equity'])==100068.02
        request.append({'name':name,'workspace':str(root),'run_id':start['run_id']})
    result=compare(request)
    assert result['metrics']['public-plans']==result['metrics']['research-schedule']
    assert result['curves']['public-plans']==result['curves']['research-schedule']
    book=Ledger.read_only(tmp_path/'public-plans/runtime/demo/account.sqlite','demo')
    assert book.sequence('demo-account')==7
    assert book.connection.execute('SELECT count(*) FROM option_plans').fetchone()[0]==2
    assert book.connection.execute("SELECT count(*) FROM tasks WHERE task_id LIKE 'option-exit-simulation:%'").fetchone()[0]==2
    assert book.snapshot('demo-account','2025-01-14T22:00:00Z',{})['reserved_cash']=='0'
    book.close()
