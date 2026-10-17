from native_tools import native_engine_root,native_dotnet
import json
import sqlite3
import pytest
from personal_quant.options.monthly_replay import monthly_replay
from personal_quant.common import write_json
from personal_quant.config import Config
from personal_quant.workspace.service import create,worker
from test_options_monthly_replay_v19 import monthly_signals,ROOT
from test_options_monthly_natural_v19 import natural_path
from test_options_plans_v19 import RISK
from test_stock_preparation_workspace_v195 import covered_evidence


def inputs(tmp_path,template,spot):
    signals=monthly_signals(tmp_path,template);path=natural_path(signals,spot)
    path['stocks']['SPY']['2024-11-01']='99'
    # An explicit additional quote, never a runtime forward-fill.
    path['stocks']['SPY']['2025-01-22']=str(spot)
    return signals,path


@pytest.mark.parametrize('template,spot,expected,kind',[
    ('protective_put',90,99472.02,'OPTION_EXERCISE'),
    ('covered_call',110,100682.02,'OPTION_ASSIGNMENT'),
    ('collar',90,99556.02,'OPTION_EXERCISE'),
    ('collar',110,100556.02,'OPTION_ASSIGNMENT'),
    ('collar',100,100054.02,'OPTION_EXPIRY')])
def test_prepared_natural_delivery_and_next_day_remaining_stock_cleanup(tmp_path,template,spot,expected,kind):
    signals,path=inputs(tmp_path,template,spot)
    proof=monthly_replay(native_engine_root(),native_dotnet(),tmp_path/'native',signals,
        initial_cash=100000,fee_per_contract=2,stock_commission_bps=2,execution_path=path,
        retain_stock=True,prepare_stock=True,final_lifecycle='natural_expiry')
    assert float(proof['expected_equity'])==expected and float(proof['actual_equity'])==expected
    assert float(proof['ledger_bridge']['equity'])==expected
    assert proof['ledger_bridge']['positions']=={} and proof['ledger_bridge']['option_positions']=={}
    assert proof['evaluation_end']=='2025-01-22'
    assert any(r['kind']==kind for r in proof['lifecycle_receipts'])
    events=json.loads((tmp_path/'native/engine-events.json').read_text())
    sells=[e for e in events if e['right'] is None and e['order_type']=='MarketOnClose' and e['quantity']<0]
    if spot==100:assert len(sells)==1 and sells[0]['utc_time'].startswith('2025-01-22')
    else:assert sells==[]  # Delivered stock must not be sold a second time.


@pytest.mark.parametrize('spot,expected,stock_plans',[(90,99556.02,1),(100,100054.02,2)])
def test_managed_natural_delivery_has_no_fictitious_second_exit_task_or_stock_sale(tmp_path,covered_evidence,spot,expected,stock_plans):
    signals,path=inputs(tmp_path/'inputs','collar',spot);file=tmp_path/'request.json'
    write_json(file,{'signals':signals,'packages':[1,1],'stock_basket':{},'execution_path':path,
        'retain_stock':True,'rolling_end_session':'2025-01-22','prepare_stock':True,'final_lifecycle':'natural_expiry',
        'plan_policy':{'schema_version':1,'chain_root':str(tmp_path/'inputs/chains'),
            'engine_evidence_files':{'collar':str(covered_evidence)},
            'risk':{**RISK,'maximum_loss_budget':30000,'maximum_notional':30000},
            'reconciliation_max_days':1,'execution_window_sessions':5}})
    root=tmp_path/'workspace'
    create(root,{'schema_version':1,'account_id':'demo-account','initial_cash':'100000','kind':'options'},Config.load(ROOT/'configs/demo.toml'))
    run=worker(root,'start',input_file=file,engine_root=native_engine_root(),dotnet=native_dotnet(),fee_per_contract=2)
    worker(root,'step',run['run_id'],'2024-11-04')
    expired=worker(root,'resume',run['run_id'],'2025-01-17')
    assert expired['status']=='PAUSED' and expired['details']['lifecycle_receipts']
    recovered=worker(root,'resume',run['run_id'],'2025-01-22')
    done=worker(root,'resume',run['run_id'],'2025-01-23') if spot==100 else recovered
    assert done['status']=='COMPLETED' and float(done['details']['equity'])==expected
    repeat=worker(root,'resume',run['run_id'],done['through_session'])
    assert repeat['repeated'] and repeat['events']==done['events']
    con=sqlite3.connect((root/'runtime/demo/account.sqlite').as_uri()+'?mode=ro',uri=True)
    assert con.execute('SELECT count(*) FROM plans').fetchone()[0]==stock_plans
    assert con.execute("SELECT count(*) FROM tasks WHERE task_id LIKE 'option-exit-simulation:%'").fetchone()[0]==1
    assert con.execute("SELECT count(*) FROM events WHERE json_extract(payload,'$.kind') IN ('OPTION_EXERCISE','OPTION_EXPIRY')").fetchone()[0]==2
    con.close()
