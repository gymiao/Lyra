from native_tools import native_engine_root,native_dotnet
import json
import os
from pathlib import Path
import pandas as pd
import pytest
from personal_quant.common import QuantError
from personal_quant.options.activation import activate
from personal_quant.options.data import OptionDataStore
from personal_quant.options.plans import draft
from personal_quant.options.lifecycle import review
from personal_quant.options.replay import fixture_replay
from test_options_monthly_replay_v19 import monthly_signals,ROOT
from test_options_ledger_v19 import contract,option_event
from test_options_plans_v19 import RISK
from conftest import event


@pytest.fixture(scope='session')
def engine_evidence(tmp_path_factory,request):
    # Reuse an immutable, fully verified archive when only Python integration
    # changed. assess_engine rejects stale C# sources, inputs or assemblies.
    archive = os.environ.get('LYRAX_TEST_ENGINE_EVIDENCE') or getattr(request.config,'_lyrax_native_a8_evidence',None)
    if archive:
        from personal_quant.options.qualification import assess_engine
        proof = Path(archive)
        for template in ('long_call','long_put','protective_put','covered_call','cash_secured_put',
                         'collar','bull_call_debit_spread','bear_put_debit_spread'):
            assert assess_engine(proof, template)['status'] == 'PASSED'
        return proof
    if not (native_dotnet()).is_file():pytest.skip('隔离引擎未安装')
    root=tmp_path_factory.mktemp('activation-engine');e=ROOT/'examples/options';store=OptionDataStore(root/'chains')
    identity=store.save(json.loads((e/'contracts-engine-fixture.json').read_text()),pd.read_csv(e/'quotes-engine-fixture.csv'),json.loads((e/'metadata.json').read_text()))['snapshot_id']
    fixture_replay(native_engine_root(),native_dotnet(),root/'engine',store,identity,
        json.loads((e/'selection-engine-fixture.json').read_text()),exercise_case=True)
    proof=root/'engine/verification.json'
    request.config._lyrax_native_a8_evidence=proof
    return proof


def setup(ledger,tmp_path,evidence,cash=22000,packages=2,template='cash_secured_put',shares=0):
    if ledger.connection.execute('SELECT version FROM schema_version').fetchone()[0]!=5:
        contract(ledger) # Explicitly enable v5 without adding account assets.
    ledger.import_events('sample',[event('capital','DEPOSIT',amount=cash)])
    if shares:
        ledger.import_events('sample',[event('stock','BUY',symbol='SPY',quantity=shares,price=100,
            settlement_at='2024-07-02T20:00:00Z')])
    monthly=monthly_signals(tmp_path,template)[0];store=OptionDataStore(tmp_path/'chains')
    contracts,rows,metadata,_=store.load(monthly['input']['snapshot_id'])
    selected={l['contract']['contract_id'] for l in monthly['selection']['legs']}
    fresh=[]
    for row in rows:
        row=dict(row)
        if row['contract_id'] in selected:
            for field in ['exchange_timestamp','underlying_timestamp']:row[field]='2024-11-01T19:39:00Z'
            row.update(available_at='2024-11-01T19:39:02Z',received_at='2024-11-01T19:39:04Z')
        fresh.append(row)
    quote_id=store.save(list(contracts.values()),pd.DataFrame(fresh),metadata)['snapshot_id']
    risk={**RISK,'maximum_contracts':2,'maximum_loss_budget':30000,'maximum_notional':30000}
    plan=draft(ledger,store,monthly['input']['snapshot_id'],'sample',{'selection':monthly['input']['request'],'packages':packages,'risk':risk,'revision':1})
    ledger.reconcile('sample',{'account_id':'sample','currency':'USD','as_of':'2024-11-01T19:38:00Z','cash_basis':'settled',
        'cash':cash-shares*100,'positions':{'SPY':shares} if shares else {},'equity':cash},{'SPY':100} if shares else {})
    request={'request_id':'activate','plan_id':plan['plan_id'],'as_of':'2024-11-01T19:40:00Z','valid_until':'2024-11-01T20:00:00Z',
        'expected_sequence':1+bool(shares),'monthly_signal':monthly,'engine_evidence_file':str(evidence),'quote_snapshot_id':quote_id,'reconciliation_max_days':1}
    return store,plan,request


@pytest.mark.parametrize('template,cash_budget,stock_budget',[
    ('long_call',222,0),('long_put',222,0),('protective_put',122,100),
    ('covered_call',12,100),('cash_secured_put',9512,0),('collar',124,100),
    ('bull_call_debit_spread',10224,0),('bear_put_debit_spread',9724,0)])
def test_a8_activation_has_independent_resource_budget(ledger,tmp_path,engine_evidence,template,cash_budget,stock_budget):
    store,plan,request=setup(ledger,tmp_path,engine_evidence,cash=100000,packages=1,
        template=template,shares=stock_budget)
    audit=activate(ledger,store,request)
    assert audit['status']=='ACTIVATED' and activate(ledger,store,request)==audit
    state=ledger.snapshot('sample',request['as_of'],{'SPY':100})
    assert float(state['reserved_cash'])==cash_budget
    assert state['reserved_positions']==({'SPY':str(stock_budget)} if stock_budget else {})
    assert float(state['equity'])==100000
    assert float(state['available_cash'])==100000-stock_budget*100-cash_budget
    assert audit['result']['account_basis']['ledger_seq']==request['expected_sequence']
    assert ledger.sequence('sample')==request['expected_sequence']


def test_multileg_activation_rejects_unsynchronised_quotes_and_no_stock(ledger,tmp_path,engine_evidence):
    store,plan,request=setup(ledger,tmp_path,engine_evidence,cash=100000,packages=1,template='collar')
    blocked=activate(ledger,store,request)
    assert blocked['status']=='BLOCKED' and 'UNDERLYING_ALREADY_RESERVED_OR_INSUFFICIENT:SPY' in blocked['checks']
    contracts,rows,metadata,_=store.load(request['quote_snapshot_id'])
    symbol=plan['selection']['legs'][0]['contract']['contract_id']
    for row in rows:
        if row['contract_id']==symbol:
            row.update(exchange_timestamp='2024-11-01T19:38:00Z',underlying_timestamp='2024-11-01T19:38:00Z')
    identity=store.save(list(contracts.values()),pd.DataFrame(rows),metadata)['snapshot_id']
    blocked=activate(ledger,store,{**request,'request_id':'skew','quote_snapshot_id':identity})
    assert 'CURRENT_LEG_TIME_MISMATCH' in blocked['checks']
    assert ledger.snapshot('sample',request['as_of'])['reserved_cash']=='0'


def test_paper_activation_does_not_inherit_demo_engine_permission(tmp_path,engine_evidence):
    from personal_quant.portfolio import Ledger
    book=Ledger(tmp_path/'paper.sqlite','paper');book.account('sample')
    try:
        store,plan,request=setup(book,tmp_path/'input',engine_evidence,packages=1)
        result=activate(book,store,request)
        assert result['status']=='BLOCKED'
        assert set(['OPTION_SOURCE_QUALIFICATION_REQUIRED','ACCOUNT_OPTION_PERMISSIONS_REQUIRED','FORWARD_SIGNAL_REQUIRED'])<=set(result['checks'])
        assert book.snapshot('sample',request['as_of'])['reserved_cash']=='0'
    finally:book.close()


def test_activation_partial_fill_idempotency_and_historical_budget(ledger,tmp_path,engine_evidence):
    store,plan,request=setup(ledger,tmp_path,engine_evidence)
    audit=activate(ledger,store,request);assert audit['status']=='ACTIVATED' and activate(ledger,store,request)==audit
    at=ledger.snapshot('sample',request['as_of']);assert at['reserved_cash']=='19014' and at['available_cash']=='2986'
    assert ledger.snapshot('sample','2024-11-01T19:39:00Z')['reserved_cash']=='0'
    assert ledger.snapshot('sample',request['as_of'],ledger_seq=0)['reserved_cash']=='0'
    assert review(ledger,plan['plan_id'],request['as_of'])['status']=='READY'
    c=audit['result']['selection']['legs'][0]['contract']
    from personal_quant.options.contracts import OptionContract
    c=OptionContract.from_dict(c)
    row=option_event('partial','OPTION_TRADE',c,action='OPEN',trade_side='SELL',price=1,fee=2,plan_id=plan['plan_id'])
    row.update(effective_at='2024-11-01T19:50:00Z',settlement_at='2024-11-01T19:50:00Z')
    ledger.import_events('sample',[row]);state=ledger.snapshot('sample','2024-11-01T19:51:00Z',{c.contract_id:1})
    assert state['option_cash_collateral']=='9500' and state['reserved_cash']=='19012'
    assert state['available_cash']=='3086' and review(ledger,plan['plan_id'],'2024-11-01T19:51:00Z')['status']=='PARTIAL'
    ledger.import_events('sample',[dict(row,event_id='rest',effective_at='2024-11-01T19:52:00Z',settlement_at='2024-11-01T19:52:00Z')])
    state=ledger.snapshot('sample','2024-11-01T19:53:00Z',{c.contract_id:1})
    assert state['reserved_cash']=='19000' and review(ledger,plan['plan_id'],'2024-11-01T19:53:00Z')['status']=='FILLED'


def test_activation_blocked_cash_and_stale_quote_do_not_reserve(ledger,tmp_path,engine_evidence):
    store,plan,request=setup(ledger,tmp_path,engine_evidence,cash=1000)
    result=activate(ledger,store,request)
    assert result['status']=='BLOCKED' and 'INSUFFICIENT_SETTLED_CASH' in result['checks']
    assert ledger.snapshot('sample',request['as_of'])['reserved_cash']=='0'
    result=activate(ledger,store,{**request,'request_id':'stale','quote_snapshot_id':request['monthly_signal']['input']['snapshot_id']})
    assert result['status']=='BLOCKED' and any(c.startswith('STALE_QUOTE') for c in result['checks'])
    assert review(ledger,plan['plan_id'],request['as_of'])['status']=='DRAFT'


def test_expiry_keeps_manual_commitment_until_confirmed_end(ledger,tmp_path,engine_evidence):
    from personal_quant.options.lifecycle import manual_action
    store,plan,request=setup(ledger,tmp_path,engine_evidence)
    activated=activate(ledger,store,request)
    symbol=activated['result']['selection']['legs'][0]['contract']['contract_id']
    action={'request_id':'submitted','plan_id':plan['plan_id'],'action':'record-submitted',
        'as_of':'2024-11-01T19:45:00Z','expected_sequence':1,'reason':'Synthetic manual order receipt',
        'orders':[{'contract_id':symbol,'side':'SELL','contracts':2,'limit_price':1,'fee_per_contract':2}]}
    manual_action(ledger,action)
    expired=review(ledger,plan['plan_id'],'2024-11-01T20:01:00Z')
    assert not expired['executable'] and expired['check_status']=='BLOCKED'
    assert ledger.snapshot('sample','2024-11-01T20:01:00Z')['reserved_cash']=='19014'
    manual_action(ledger,{**action,'request_id':'ended','action':'confirm-ended',
        'as_of':'2024-11-01T20:02:00Z','orders':[]})
    assert review(ledger,plan['plan_id'],'2024-11-01T20:03:00Z')['status']=='EXPIRED'
    assert ledger.snapshot('sample','2024-11-01T20:03:00Z')['reserved_cash']=='0'
    assert ledger.snapshot('sample','2024-11-01T19:46:00Z')['reserved_cash']=='19014'


def test_external_deposit_and_reconciliation_difference_block_execution(ledger,tmp_path,engine_evidence):
    store,plan,request=setup(ledger,tmp_path,engine_evidence)
    activate(ledger,store,request)
    ledger.import_events('sample',[event('new-capital','DEPOSIT',amount=100,effective_at='2024-11-01T19:45:00Z')])
    state=review(ledger,plan['plan_id'],'2024-11-01T19:46:00Z')
    assert not state['executable'] and state['check_status']=='BLOCKED'
    assert state['status']=='CANCELLED' and state['intent_closure']['reason']=='EXTERNAL_CAPITAL_CHANGED'
    assert ledger.snapshot('sample','2024-11-01T19:46:00Z')['reserved_cash']=='0'
    assert any('未关联变化' in issue for issue in state['progress']['fact_anomalies'])
    ledger.reconcile('sample',{'account_id':'sample','currency':'USD','as_of':'2024-11-01T19:47:00Z',
        'cash_basis':'settled','cash':22000,'positions':{},'equity':22000})
    state=review(ledger,plan['plan_id'],'2024-11-01T19:48:00Z')
    assert '账户对账未通过' in state['progress']['fact_anomalies']
    assert review(ledger,plan['plan_id'],request['as_of'])['executable']


def test_capital_change_preserves_only_submitted_order_and_actual_collateral(ledger,tmp_path,engine_evidence):
    from personal_quant.options.lifecycle import manual_action
    from personal_quant.options.contracts import OptionContract
    store,plan,request=setup(ledger,tmp_path,engine_evidence)
    audit=activate(ledger,store,request)
    c=OptionContract.from_dict(audit['result']['selection']['legs'][0]['contract'])
    order={'request_id':'submitted','plan_id':plan['plan_id'],'action':'record-submitted',
        'as_of':'2024-11-01T19:42:00Z','expected_sequence':1,'reason':'Synthetic one-contract order',
        'orders':[{'contract_id':c.contract_id,'side':'SELL','contracts':1,'limit_price':1,'fee_per_contract':2}]}
    manual_action(ledger,order)
    ledger.import_events('sample',[event('withdraw','WITHDRAWAL',amount=100,effective_at='2024-11-01T19:45:00Z')])
    state=review(ledger,plan['plan_id'],'2024-11-01T19:46:00Z')
    assert state['intent_closure']['status']=='WAITING_MANUAL_CONFIRMATION'
    assert ledger.snapshot('sample','2024-11-01T19:46:00Z')['reserved_cash']=='9502'
    fill=option_event('fill','OPTION_TRADE',c,action='OPEN',trade_side='SELL',price=1,fee=2,plan_id=plan['plan_id'])
    fill.update(effective_at='2024-11-01T19:47:00Z',settlement_at='2024-11-01T19:47:00Z')
    ledger.import_events('sample',[fill])
    state=ledger.snapshot('sample','2024-11-01T19:48:00Z',{c.contract_id:1})
    assert state['reserved_cash']=='9500' and state['option_cash_collateral']=='9500'
    manual_action(ledger,{**order,'request_id':'ended','action':'confirm-ended','orders':[],
        'as_of':'2024-11-01T19:49:00Z','expected_sequence':3})
    closed=review(ledger,plan['plan_id'],'2024-11-01T19:50:00Z')
    assert closed['status']=='CANCELLED' and closed['progress']['filled_contracts'][c.contract_id]=='1'
    assert closed['progress']['remaining_contracts'][c.contract_id]=='1'
    assert ledger.snapshot('sample','2024-11-01T19:50:00Z',{c.contract_id:1})['reserved_cash']=='9500'
    assert ledger.snapshot('sample','2024-11-01T19:44:00Z')['reserved_cash']=='19014'
    assert ledger.snapshot('sample','2024-11-01T19:46:00Z',ledger_seq=1)['reserved_cash']=='19014'
    assert ledger.snapshot('sample','2024-11-01T19:50:00Z',ledger_seq=1)['reserved_cash']=='19014'


def test_reversed_capital_does_not_reopen_old_monthly_intent(ledger,tmp_path,engine_evidence):
    store,plan,request=setup(ledger,tmp_path,engine_evidence)
    activate(ledger,store,request)
    ledger.import_events('sample',[event('new','DEPOSIT',amount=100,effective_at='2024-11-01T19:45:00Z')])
    ledger.import_events('sample',[event('correction','REVERSAL',reference_event_id='new',effective_at='2024-11-01T19:45:00Z')])
    state=review(ledger,plan['plan_id'],'2024-11-01T19:47:00Z')
    assert state['status']=='CANCELLED' and state['intent_closure']['event_ids']==['new']
    # Changing package count changes intent_id, but cannot revive the same signal.
    second=draft(ledger,store,plan['snapshot_id'],'sample',{**plan['request'],'revision':2,'packages':1})
    result=activate(ledger,store,{**request,'request_id':'new-revision','plan_id':second['plan_id'],
        'expected_sequence':3,'as_of':'2024-11-01T19:48:00Z'})
    assert result['status']=='BLOCKED' and 'OPTION_INTENT_CLOSED_FOR_CAPITAL_CHANGE' in result['checks']


def test_same_intent_revision_cannot_activate_twice(ledger,tmp_path,engine_evidence):
    store,plan,request=setup(ledger,tmp_path,engine_evidence,cash=50000)
    activate(ledger,store,request)
    second=draft(ledger,store,plan['snapshot_id'],'sample',{**plan['request'],'revision':2})
    result=activate(ledger,store,{**request,'request_id':'revision','plan_id':second['plan_id']})
    assert result['status']=='BLOCKED' and 'OPTION_INTENT_ALREADY_ACTIVATED' in result['checks']
    assert ledger.snapshot('sample',request['as_of'])['reserved_cash']=='19014'


def test_activation_archive_backup_restore_preserves_budget(tmp_path,monkeypatch,engine_evidence):
    import shutil
    from personal_quant.portfolio import Ledger
    from personal_quant.portfolio.backup import create_bundle,verify_bundle,restore_bundle
    monkeypatch.chdir(tmp_path)
    config=tmp_path/'local.toml';config.write_bytes((ROOT/'configs/demo.toml').read_bytes())
    root=Path('runtime/demo')
    book=Ledger(root/'account.sqlite','demo');book.account('sample')
    try:
        store,plan,request=setup(book,tmp_path/'inputs',engine_evidence)
        shutil.copytree(store.root,root/'options/chains')
        audit=activate(book,store,request)
        assert audit['status']=='ACTIVATED'
        create_bundle(root,config,tmp_path/'bundle')
        verified=verify_bundle(tmp_path/'bundle','demo')
        assert request['quote_snapshot_id'] in verified['references']['referenced_option_snapshots']
        restore_bundle(tmp_path/'bundle',tmp_path/'recovered','demo')
        recovered=Ledger(tmp_path/'recovered'/root/'account.sqlite','demo')
        try:
            state=recovered.snapshot('sample',request['as_of'])
            assert state['reserved_cash']=='19014' and state['available_cash']=='2986'
            assert review(recovered,plan['plan_id'],request['as_of'])['executable']
        finally:recovered.close()
        # Recomputing the outer bundle manifest cannot legitimise changed engine bytes.
        from test_backup import rewrite_manifest
        dll=tmp_path/'bundle'/root/'options/engine-evidence'/audit['engine_assessment']['evidence_hash']/'adapter-bin/LyraX.Options.dll'
        dll.write_bytes(b'corrupt')
        rewrite_manifest(tmp_path/'bundle')
        with pytest.raises(QuantError,match='程序集改变'):verify_bundle(tmp_path/'bundle','demo')
    finally:book.close()
