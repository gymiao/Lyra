import json
from pathlib import Path
import pytest
from native_tools import native_engine_root,native_dotnet
from personal_quant.config import Config
from personal_quant.workspace.service import create,worker
from personal_quant.workspace.option_setup import prepare
from personal_quant.portfolio import Ledger
ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('name',['iron_condor','iron_butterfly'])
def test_two_cycles_public_plan_reservations_facts_settlement_and_resume(tmp_path,name,four_evidence,monkeypatch):
    root=tmp_path/'workspace';create(root,{'schema_version':1,'kind':'options','account_id':'demo-account','initial_cash':'100000'},Config.load(ROOT/'configs/demo.toml'))
    spec=json.loads((ROOT/'configs/v195-option-setup.json').read_text());spec['template_id']=name
    spec['selection_parameters']['minimum_spread_width']=5
    from test_options_plans_v19 import RISK
    spec['plan_policy']={'risk':{**RISK,'maximum_loss_budget':30000,'maximum_notional':30000},
        'engine_evidence_file':str(four_evidence),'reconciliation_max_days':1,'execution_window_sessions':5}
    prepared=prepare(root,spec)
    start=worker(root,'start',input_file=prepared['request_file'],engine_root=native_engine_root(),dotnet=native_dotnet(),fee_per_contract=2)
    first=worker(root,'step',start['run_id'],'2024-11-04')
    assert first['events']==5 and first['details']['plan_support']=='OPENING_PLANS_LINKED_EXIT_FACTS'
    from personal_quant.portfolio.backup import create_bundle,restore_bundle
    monkeypatch.chdir(root)
    create_bundle(root/'runtime/demo',root/'config.json',tmp_path/'backup')
    restored=tmp_path/'restored';restore_bundle(tmp_path/'backup',restored,'demo')
    root=restored
    market=worker(root,'resume',start['run_id'],prepared['last_market_session'])
    assert float(market['details']['equity'])==99928
    final=worker(root,'resume',start['run_id'],prepared['last_settlement_session'])
    assert final['status']=='COMPLETED' and float(final['details']['equity'])==99928
    again=worker(root,'resume',start['run_id'],prepared['last_settlement_session'])
    assert again['events']==final['events']==17
    book=Ledger.read_only(root/'runtime/demo/account.sqlite','demo')
    try:
        plans=[json.loads(r[0]) for r in book.connection.execute('SELECT payload FROM option_plans')]
        assert len(plans)==2 and all(p['activation'] and float(p['active_reservation']['reserved_cash'])==0 for p in plans)
        state=book.snapshot('demo-account',final['details']['as_of'],{})
        assert state['positions']=={} and state['option_positions']=={} and not state['anomalies']
        assert float(state['equity'])==99928 and float(state['receivables'])==float(state['payables'])==0
    finally:book.close()
