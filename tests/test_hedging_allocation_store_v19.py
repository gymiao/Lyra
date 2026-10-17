import copy
import json
from pathlib import Path

import pytest

from personal_quant.common import QuantError,now_utc
from personal_quant.hedging.allocation_store import current_basis,history,update,validate_references
from personal_quant.hedging.securities import register
from personal_quant.portfolio import Ledger
from personal_quant.portfolio.backup import create_bundle,restore_bundle,verify_bundle
from test_hedging_coverage_v19 import funded,request
from test_hedging_securities_v19 import identity
from test_options_lifecycle_v19 import plan
from test_options_ledger_v19 import contract,option_event
from personal_quant.options.lifecycle import manual_action
from conftest import event


def change(book):
    c=funded(book);registered=register(book.path.parent,'demo',identity())
    query=request(book,c);rows=query.pop('allocations');query['allocations']=[]
    query['security_versions']={'SPY':registered['record']['version_hash']}
    basis=current_basis(book,'sample')
    return c,dict(schema_version=1,request_id='first',expected_version=basis['version_hash'],
        expected_resource_hash=basis['resource_hash'],coverage_request=query,changes=rows,
        retire_ids=[],reason='synthetic actual Put coverage reference')


def test_preview_commit_repeat_and_future_events_do_not_rewrite_saved_version(ledger):
    _,req=change(ledger);before=copy.deepcopy(req)
    preview=update(ledger,'sample',req)
    assert history(ledger,'sample')==[] and ledger.sequence('sample')==3
    first=update(ledger,'sample',req,commit=True)
    assert first['version_hash']==preview['version_hash'] and first['coverage']['actual_protected_shares']['security-us-spy']=='100'
    ledger.import_events('sample',[event('later','DEPOSIT',amount=1000)])
    assert update(ledger,'sample',req,commit=True)==first and req==before
    assert len(history(ledger,'sample'))==1 and not first['creates_reservations'] and not first['executable']


def test_request_id_conflict_and_new_request_stale_revision(ledger):
    _,req=change(ledger);first=update(ledger,'sample',req,commit=True)
    with pytest.raises(QuantError) as exc:update(ledger,'sample',dict(req,reason='different'),commit=True)
    assert exc.value.code=='ALLOCATION_REQUEST_CONFLICT'
    with pytest.raises(QuantError) as exc:update(ledger,'sample',dict(req,request_id='second'),commit=True)
    assert exc.value.code=='STALE_ALLOCATION_VERSION'
    assert history(ledger,'sample')==[first]


def test_resource_change_without_new_event_invalidates_precheck(ledger):
    c,req=change(ledger);plan(ledger,c)
    assert ledger.sequence('sample')==3
    with pytest.raises(QuantError) as exc:update(ledger,'sample',req,commit=True)
    assert exc.value.code=='STALE_HEDGE_RESOURCES'
    assert history(ledger,'sample')==[]


def test_old_parent_is_merged_for_cross_version_duplicate_check(ledger):
    _,req=change(ledger);first=update(ledger,'sample',req,commit=True)
    basis=current_basis(ledger,'sample')
    second=dict(req,request_id='different-policy-version',expected_version=first['version_hash'],
        expected_resource_hash=basis['resource_hash'],changes=[dict(req['changes'][0],allocation_id='new',parent_id='other')])
    with pytest.raises(QuantError) as exc:update(ledger,'sample',second,commit=True)
    assert exc.value.code=='DUPLICATE_PROTECTION'
    assert len(history(ledger,'sample'))==1


def test_explicit_retirement_is_not_a_financial_release_and_history_remains(ledger):
    _,req=change(ledger);first=update(ledger,'sample',req,commit=True)
    before=ledger.snapshot('sample',req['coverage_request']['as_of'])
    basis=current_basis(ledger,'sample')
    second=dict(req,request_id='retire-reference',expected_version=first['version_hash'],
        expected_resource_hash=basis['resource_hash'],changes=[],retire_ids=['allocation-put'],reason='End reference, keep actual option facts')
    result=update(ledger,'sample',second,commit=True)
    assert result['revision']==2 and result['previous_version']==first['version_hash']
    assert result['coverage']['actual_protected_shares']['security-us-spy']=='0'
    assert result['coverage']['unallocated_actual_contracts'][0]['unallocated_contracts']=='1'
    assert ledger.snapshot('sample',req['coverage_request']['as_of'])==before and len(history(ledger,'sample'))==2


def test_partial_transition_preserves_parent_identity_and_no_transaction_on_failure(ledger):
    _,req=change(ledger);first=update(ledger,'sample',req,commit=True);basis=current_basis(ledger,'sample')
    bad=dict(req,request_id='bad-edit',expected_version=first['version_hash'],expected_resource_hash=basis['resource_hash'],
        changes=[dict(req['changes'][0],parent_id='changed')])
    with pytest.raises(QuantError) as exc:update(ledger,'sample',bad,commit=True)
    assert exc.value.code=='ALLOCATION_IDENTITY_CONFLICT'
    assert len(history(ledger,'sample'))==1


def test_full_backup_restore_and_history_tamper_rejected(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path);runtime=tmp_path/'runtime/demo';runtime.mkdir(parents=True)
    book=Ledger(runtime/'account.sqlite','demo');book.account('sample');_,req=change(book)
    saved=update(book,'sample',req,commit=True);validate_references(runtime,book)
    cfg=tmp_path/'demo.toml';cfg.write_bytes((Path(__file__).resolve().parents[1]/'configs/demo.toml').read_bytes())
    create_bundle(runtime,cfg,tmp_path/'bundle');verify_bundle(tmp_path/'bundle','demo')
    restore_bundle(tmp_path/'bundle',tmp_path/'restored','demo')
    restored=Ledger(tmp_path/'restored/runtime/demo/account.sqlite','demo')
    assert history(restored,'sample')==[saved];validate_references(restored.path.parent,restored);restored.close()
    corrupted=dict(saved,revision=99)
    book.connection.execute("UPDATE tasks SET details=? WHERE task_id LIKE 'hedge-allocation:%'",(json.dumps(corrupted),))
    with pytest.raises(QuantError) as exc:validate_references(runtime,book)
    assert exc.value.code=='CORRUPT_ALLOCATION_HISTORY';book.close()


def test_real_partial_fill_transitions_persisted_intent_to_actual_and_remaining(ledger):
    c=contract(ledger);plan_id=plan(ledger,c)
    ledger.import_events('sample',[event('cash','DEPOSIT',amount=30000),
        event('stock','BUY',symbol='SPY',quantity=200,price=100,settlement_at='2026-10-09T20:00:00Z')])
    manual_action(ledger,dict(request_id='submitted',plan_id=plan_id,action='record-submitted',
        as_of='2026-10-09T19:40:00Z',expected_sequence=2,reason='synthetic manual order',
        orders=[dict(contract_id=c.contract_id,side='BUY',contracts=2,limit_price=2,fee_per_contract=1)]))
    registered=register(ledger.path.parent,'demo',identity());query=request(ledger,c)
    rows=query.pop('allocations');rows[0].update(state='inflight',contracts=2,share_end=200)
    query.update(allocations=[],inflight_plan_ids=[plan_id],security_versions={'SPY':registered['record']['version_hash']})
    basis=current_basis(ledger,'sample')
    req=dict(schema_version=1,request_id='pending',expected_version=None,expected_resource_hash=basis['resource_hash'],
             coverage_request=query,changes=rows,retire_ids=[],reason='pending two Put contracts')
    first=update(ledger,'sample',req,commit=True)
    assert first['coverage']['actual_protected_shares']['security-us-spy']=='0'
    assert first['coverage']['inflight_intended_shares']['security-us-spy']=='200'
    ledger.import_events('sample',[option_event('fill','OPTION_TRADE',c,action='OPEN',trade_side='BUY',price=2,fee=1,plan_id=plan_id)])
    before=ledger.snapshot('sample',query['as_of']);basis=current_basis(ledger,'sample')
    query=dict(query,ledger_seq=3,knowledge_cutoff=now_utc())
    second=dict(req,request_id='partial',expected_version=first['version_hash'],expected_resource_hash=basis['resource_hash'],
        coverage_request=query,changes=[dict(rows[0],state='actual',contracts=1,share_end=100),
                                       dict(rows[0],allocation_id='remaining',contracts=1,share_start=100)])
    result=update(ledger,'sample',second,commit=True)
    assert result['coverage']['actual_protected_shares']['security-us-spy']=='100'
    assert result['coverage']['inflight_intended_shares']['security-us-spy']=='100'
    assert ledger.snapshot('sample',query['as_of'])==before and before['reserved_cash']=='201'


def test_concurrent_writers_using_same_basis_create_one_revision(ledger):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    _,req=change(ledger);barrier=Barrier(2)
    def submit(request_id):
        book=Ledger(ledger.path,'demo')
        try:
            barrier.wait(timeout=10)
            try:return update(book,'sample',dict(req,request_id=request_id),commit=True)['status']
            except QuantError as exc:return exc.code
        finally:book.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(submit,['one','two']))
    assert sorted(results)==['COMMITTED','STALE_ALLOCATION_VERSION']
    assert len(history(ledger,'sample'))==1 and ledger.sequence('sample')==3
