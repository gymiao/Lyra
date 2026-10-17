from native_tools import native_engine_root,native_dotnet
import json
import os
from pathlib import Path
import sqlite3
import pandas as pd
import pytest
from personal_quant.common import write_json,QuantError
from personal_quant.config import Config
from personal_quant.options.data import OptionDataStore
from personal_quant.options.replay import fixture_replay
from personal_quant.workspace.service import create,worker,status
from test_options_monthly_replay_v19 import ROOT
from test_wheel_native_v195 import wheel_inputs
from test_options_plans_v19 import RISK


@pytest.fixture(scope='module')
def put_evidence(tmp_path_factory):
    existing=os.environ.get('LYRAX_TEST_PUT_POLICY_EVIDENCE')
    if existing:
        from personal_quant.options.qualification import assess_engine
        assert assess_engine(existing,'cash_secured_put')['status']=='PASSED'
        return Path(existing)
    root=tmp_path_factory.mktemp('put-policy-evidence');examples=ROOT/'examples/options'
    store=OptionDataStore(root/'chains')
    identity=store.save(json.loads((examples/'contracts-engine-fixture.json').read_text()),
        pd.read_csv(examples/'quotes-engine-fixture.csv'),json.loads((examples/'metadata.json').read_text()))['snapshot_id']
    fixture_replay(native_engine_root(),native_dotnet(),root/'engine',store,identity,
        json.loads((examples/'selection-engine-fixture.json').read_text()),exercise_case=True,templates=['cash_secured_put'])
    return root/'engine/verification.json'


def setup(tmp_path,evidence,risk=None):
    signals,path=wheel_inputs(tmp_path/'inputs',False)
    # Both helpers contain identical full source chains, despite different scope.
    policy={'schema_version':1,'chain_root':str(tmp_path/'inputs/put/chains'),
        'engine_evidence_files':{'cash_secured_put':str(evidence)},
        'risk':risk or {**RISK,'maximum_contracts':1,'maximum_loss_budget':30000,'maximum_notional':30000,'cash_buffer':0},
        'reconciliation_max_days':1}
    request=tmp_path/'request.json'
    write_json(request,{'signals':signals,'packages':[1,1],'stock_basket':{},'execution_path':path,
        'wheel':True,'wheel_end_session':'2024-12-19','plan_policy':policy})
    root=tmp_path/'workspace'
    create(root,{'schema_version':1,'account_id':'demo-account','initial_cash':'100000','kind':'options'},Config.load(ROOT/'configs/demo.toml'))
    return root,request


def test_option_workspace_plans_activate_reserve_and_link_native_cycles_once(tmp_path,put_evidence):
    root,file=setup(tmp_path,put_evidence)
    run=worker(root,'start',input_file=file,engine_root=native_engine_root(),dotnet=native_dotnet(),fee_per_contract=2)
    first=worker(root,'step',run['run_id'],'2024-11-04')
    assert first['details']['plan_support']=='OPENING_PLANS_LINKED_EXIT_FACTS'
    assert first['events']==2
    db=root/'runtime/demo/account.sqlite'
    con=sqlite3.connect(db.as_uri()+'?mode=ro',uri=True)
    plans=[json.loads(r[0]) for r in con.execute('SELECT payload FROM option_plans')]
    assert len(plans)==1 and plans[0]['status']=='FILLED'
    assert plans[0]['activation'] and float(plans[0]['active_reservation']['reserved_cash'])==0
    trade=json.loads(con.execute("SELECT payload FROM events WHERE json_extract(payload,'$.kind')='OPTION_TRADE'").fetchone()[0])
    assert trade['plan_id']==plans[0]['plan_id']
    con.close()
    done=worker(root,'resume',run['run_id'],'2024-12-19')
    assert done['status']=='COMPLETED' and float(done['details']['equity'])==100196
    repeat=worker(root,'resume',run['run_id'],'2024-12-19')
    assert repeat['repeated'] and repeat['events']==done['events']==5
    con=sqlite3.connect(db.as_uri()+'?mode=ro',uri=True)
    assert con.execute('SELECT count(*) FROM option_plans').fetchone()[0]==2
    assert con.execute("SELECT count(*) FROM tasks WHERE task_id LIKE 'option-activation:%'").fetchone()[0]==2
    assert con.execute("SELECT count(*) FROM events WHERE json_extract(payload,'$.kind') LIKE 'OPTION_%' AND json_extract(payload,'$.plan_id') IS NOT NULL").fetchone()[0]==4
    con.close()


def test_policy_wrong_fee_fails_before_native_or_plan_writes(tmp_path,put_evidence):
    root,file=setup(tmp_path,put_evidence,{**RISK,'fee_per_contract':3})
    with pytest.raises(QuantError) as caught:
        worker(root,'start',input_file=file,engine_root=native_engine_root(),dotnet=native_dotnet(),fee_per_contract=2)
    assert caught.value.code=='INVALID_OPTION_RISK' and '计划费用须与原生费用一致' in str(caught.value)
    assert status(root)['events']==1


def test_frozen_policy_tamper_is_rejected_before_replay(tmp_path,put_evidence):
    root,file=setup(tmp_path,put_evidence)
    run=worker(root,'start',input_file=file,engine_root=native_engine_root(),dotnet=native_dotnet(),fee_per_contract=2)
    policy=root/'runtime/demo/simulation/options'/run['run_id']/'plan-policy.json'
    altered=json.loads(policy.read_text());altered['risk']['cash_buffer']=100
    write_json(policy,altered)
    with pytest.raises(QuantError) as caught:worker(root,'step',run['run_id'],'2024-11-04')
    assert '冻结计划政策改变' in str(caught.value)
    assert status(root)['events']==1


def test_plan_budget_failure_rolls_back_native_import_and_activation(tmp_path,put_evidence):
    root,file=setup(tmp_path,put_evidence,{**RISK,'maximum_loss_budget':1})
    run=worker(root,'start',input_file=file,engine_root=native_engine_root(),dotnet=native_dotnet(),fee_per_contract=2)
    with pytest.raises(QuantError) as caught:worker(root,'step',run['run_id'],'2024-11-04')
    assert 'LOSS_BUDGET_EXCEEDED' in str(caught.value)
    assert status(root)['events']==1
    con=sqlite3.connect((root/'runtime/demo/account.sqlite').as_uri()+'?mode=ro',uri=True)
    assert con.execute('SELECT count(*) FROM option_plans').fetchone()[0]==0
    assert con.execute("SELECT count(*) FROM tasks WHERE task_id LIKE 'option-activation:%'").fetchone()[0]==0
    assert con.execute('SELECT status FROM simulation_runs').fetchone()[0]=='FAILED'
    con.close()


@pytest.mark.parametrize('changed_at,blocked',[('2024-11-03T20:00:00Z',True),('2024-11-06T20:00:00Z',False),
    ('2024-11-05T21:00:00Z',False),('2024-11-05T20:59:59Z',True)])
def test_retired_plan_ignores_only_changes_after_actual_close_and_settlement(ledger,tmp_path,put_evidence,changed_at,blocked):
    from test_options_activation_v19 import setup as activation_setup
    from personal_quant.options.activation import activate
    from personal_quant.options.lifecycle import review
    from conftest import event
    store,plan,request=activation_setup(ledger,tmp_path,put_evidence,cash=100000,packages=1,template='cash_secured_put')
    assert activate(ledger,store,request)['status']=='ACTIVATED'
    leg=plan['selection']['legs'][0]
    common={'contract_version':leg['contract_version'],'plan_id':plan['plan_id'],'quantity':1,'price':1,'fee':2,'source':'explicit_test_statement','evidence_type':'test'}
    ledger.import_events('sample',[{**common,'event_id':'open','kind':'OPTION_TRADE','action':'OPEN','trade_side':'SELL',
        'effective_at':'2024-11-01T20:00:00Z','settlement_at':'2024-11-04T21:00:00Z'},
        {**common,'event_id':'close','kind':'OPTION_TRADE','action':'CLOSE','trade_side':'BUY',
        'effective_at':'2024-11-04T21:00:00Z','settlement_at':'2024-11-05T21:00:00Z'},
        event('external','DEPOSIT',amount=50,effective_at=changed_at)])
    result=review(ledger,plan['plan_id'],'2024-11-07T21:00:00Z')
    assert result['lifecycle']['status']=='CLOSED'
    assert any('未关联变化' in reason for reason in result['progress']['fact_anomalies']) is blocked
    assert float(ledger.snapshot('sample','2024-11-07T21:00:00Z')['investment_pnl'])==-4
