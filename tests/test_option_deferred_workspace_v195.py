from native_tools import native_engine_root,native_dotnet
import json
import sqlite3
from test_option_workspace_plans_v195 import put_evidence
from test_options_monthly_replay_v19 import monthly_signals,ROOT
from test_options_monthly_natural_v19 import natural_path
from test_options_plans_v19 import RISK
from personal_quant.common import write_json
from personal_quant.config import Config
from personal_quant.workspace.service import create,worker


def test_monthly_cash_wait_uses_explicit_deferred_plan_window_and_keeps_signal(tmp_path,put_evidence):
    signals=monthly_signals(tmp_path/'inputs','cash_secured_put');path=natural_path(signals,100)
    path={**path,'stocks':{s:{d:p for d,p in values.items() if d<='2025-01-10'} for s,values in path['stocks'].items()},
          'options':{s:{d:p for d,p in values.items() if d<='2025-01-10'} for s,values in path['options'].items()}}
    file=tmp_path/'request.json'
    write_json(file,{'signals':signals,'packages':[1,1],'stock_basket':{},'execution_path':path,
        'plan_policy':{'schema_version':1,'chain_root':str(tmp_path/'inputs/chains'),
            'engine_evidence_files':{'cash_secured_put':str(put_evidence)},
            'risk':{**RISK,'maximum_loss_budget':30000,'maximum_notional':30000},
            'reconciliation_max_days':1,'execution_window_sessions':5}})
    root=tmp_path/'workspace'
    create(root,{'schema_version':1,'account_id':'demo-account','initial_cash':'100000','kind':'options'},Config.load(ROOT/'configs/demo.toml'))
    started=worker(root,'start',input_file=file,engine_root=native_engine_root(),dotnet=native_dotnet(),fee_per_contract=2)
    first=worker(root,'step',started['run_id'],'2024-11-04')
    done=worker(root,'resume',started['run_id'],'2025-01-10')
    settled=worker(root,'resume',started['run_id'],'2025-01-13')
    assert settled['status']=='COMPLETED' and float(settled['details']['equity'])==99972
    repeat=worker(root,'resume',started['run_id'],'2025-01-13')
    assert repeat['repeated'] and repeat['events']==settled['events']==5
    con=sqlite3.connect((root/'runtime/demo/account.sqlite').as_uri()+'?mode=ro',uri=True)
    audits=[json.loads(row[0]) for row in con.execute("SELECT details FROM tasks WHERE task_id LIKE 'option-activation:%'")]
    assert len(audits)==2
    second=next(a for a in audits if a['request']['monthly_signal']['decision_at']==signals[1]['decision_at'])
    assert second['request']['monthly_signal']==signals[1]
    assert second['execution_window']['session']=='2024-12-03'
    assert second['request']['as_of']=='2024-12-03T20:40:00+00:00'
    assert second['request']['valid_until']=='2024-12-03T21:00:00+00:00'
    assert con.execute('SELECT count(*) FROM option_plans').fetchone()[0]==2
    con.close()
