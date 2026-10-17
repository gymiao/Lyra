from native_tools import native_engine_root,native_dotnet
"""Restore an actual native receipt subprefix, with the protective leg still open."""
import json
import sqlite3
import pytest
from personal_quant.common import QuantError,write_json
from personal_quant.config import Config
from personal_quant.portfolio import Ledger
from personal_quant.portfolio.backup import create_bundle,restore_bundle
from personal_quant.options.exit_tasks import pending_exits
from personal_quant.options.ledger import register_contract
from personal_quant.options.monthly_replay import monthly_replay
from personal_quant.workspace.option_policy import bind_events,import_planned_events
from personal_quant.workspace.service import create,worker
from test_options_plans_v19 import RISK
from test_options_monthly_replay_v19 import ROOT
from test_stock_preparation_v195 import prepared_inputs
from test_stock_preparation_workspace_v195 import covered_evidence


def test_native_short_close_survives_backup_and_remaining_protection_resumes(tmp_path,monkeypatch,covered_evidence):
    signals,path=prepared_inputs(tmp_path/'inputs','collar')
    request=tmp_path/'request.json'
    write_json(request,{'signals':signals,'packages':[1,1],'stock_basket':{},'execution_path':path,
        'retain_stock':True,'rolling_end_session':'2025-01-13','prepare_stock':True,
        'plan_policy':{'schema_version':1,'chain_root':str(tmp_path/'inputs/chains'),
            'engine_evidence_files':{'collar':str(covered_evidence)},
            'risk':{**RISK,'maximum_loss_budget':30000,'maximum_notional':30000},
            'reconciliation_max_days':1,'execution_window_sessions':5}})
    workspace=tmp_path/'workspace'
    create(workspace,{'schema_version':1,'account_id':'demo-account','initial_cash':'100000','kind':'options'},Config.load(ROOT/'configs/demo.toml'))
    run=worker(workspace,'start',input_file=request,engine_root=native_engine_root(),dotnet=native_dotnet(),fee_per_contract=2)
    runtime=workspace/'runtime/demo';directory=runtime/'simulation/options'/run['run_id']
    native=directory/'prefix-2024-12-02-receipt-subprefix'
    clipped={**path,'stocks':{s:{d:p for d,p in vs.items() if d<='2024-12-02'} for s,vs in path['stocks'].items()},
        'options':{s:{d:p for d,p in vs.items() if d<='2024-12-02'} for s,vs in path['options'].items()}}
    proof=monthly_replay(native_engine_root(),native_dotnet(),native,signals,
        initial_cash=100000,fee_per_contract=2,stock_commission_bps=2,execution_path=clipped,
        retain_stock=True,prepare_stock=True,rolling_end_session='2025-01-13',through='2024-12-02')
    engine=sqlite3.connect(native/'bridge.sqlite')
    terms=[json.loads(r[0]) for r in engine.execute('SELECT payload FROM option_contracts')]
    rows=[json.loads(r[0]) for r in engine.execute('SELECT payload FROM events ORDER BY seq') if json.loads(r[0])['event_id']!='capital']
    engine.close()
    policy=json.loads((directory/'plan-policy.json').read_text())
    desired=bind_events([{**e,'account_id':'demo-account'} for e in rows],proof['cycles'],signals,[1,1],'demo-account',policy,run_id=run['run_id'])
    first_close=next(i for i,e in enumerate(desired) if e['kind']=='OPTION_TRADE' and e['action']=='CLOSE')
    assert desired[first_close]['trade_side']=='BUY' # native short CALL obligation first
    book=Ledger(runtime/'account.sqlite','demo')
    with book.transaction():
        for term in terms:register_contract(book,term)
        import_planned_events(book,directory,'demo-account',
            [{k:v for k,v in e.items() if k!='contract'} for e in desired[:first_close+1]],
            signals,[1,1],clipped,policy,config=Config.load(workspace/'config.json'),run_id=run['run_id'],
            cycles=proof['cycles'],native_directory=native)
    assert book.sequence('demo-account')==5 # deposit, stock, PUT, CALL, short CALL close
    assert len(pending_exits(book,'demo-account','2024-12-02T21:00:00Z'))==1
    assert book.connection.execute("SELECT count(*) FROM tasks WHERE task_id LIKE 'option-exit-simulation:%'").fetchone()[0]==0
    progress_row=book.connection.execute("SELECT task_id,details FROM tasks WHERE task_id LIKE 'option-exit-prefix-progress:%'").fetchone()
    progress=json.loads(progress_row['details']);assert len(progress['receipts'])==1
    book.close();monkeypatch.chdir(workspace)
    create_bundle(runtime,workspace/'config.json',tmp_path/'bundle')
    # A changed count cannot become an authoritative restored progress record.
    book=Ledger(runtime/'account.sqlite','demo')
    changed={**progress,'closed':{k:'99' for k in progress['closed']}}
    book.record_task(progress_row['task_id'],'SUCCESS',changed);book.close()
    with pytest.raises(QuantError) as caught:create_bundle(runtime,workspace/'config.json',tmp_path/'corrupt-bundle')
    assert caught.value.code=='CORRUPT_OPTION_AUDIT'
    restored=tmp_path/'restored';result=restore_bundle(tmp_path/'bundle',restored,'demo')
    recovered=restored/Config.load(result['config']).runtime_dir
    book=Ledger(recovered/'account.sqlite','demo')
    assert book.sequence('demo-account')==5
    assert len(pending_exits(book,'demo-account','2024-12-02T21:00:00Z'))==1
    book.close()
    # No checkpoint was committed for the interrupted receipt batch. Official
    # replay must preserve its existing event prefix and import only the remainder.
    resumed=worker(restored,'resume',run['run_id'],'2025-01-13')
    final=worker(restored,'resume',run['run_id'],'2025-01-14')
    assert final['status']=='COMPLETED' and final['events']==11
    assert float(final['details']['equity'])==100040.02
    assert worker(restored,'resume',run['run_id'],'2025-01-14')['repeated']
    book=Ledger(recovered/'account.sqlite','demo')
    assert pending_exits(book,'demo-account','2025-01-14T22:00:00Z')==[]
    assert book.connection.execute("SELECT count(*) FROM tasks WHERE task_id LIKE 'option-exit-simulation:%'").fetchone()[0]==2
    book.close()
