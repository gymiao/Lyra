import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from personal_quant.common import QuantError, canonical, digest
from personal_quant.hedging.allocation_store import resources
from personal_quant.hedging.intent_actions import history, save
from personal_quant.hedging.intents import records, save as save_parent, validate_references
from personal_quant.portfolio import Ledger
from personal_quant.portfolio.backup import create_bundle, restore_bundle, verify_bundle
from test_hedging_archive_v19 import frozen_risk
from test_hedging_exposure_v19 import risk_market
from test_hedging_intents_v19 import parent


def close_request(book, original, action='CANCELLED'):
    return dict(schema_version=1, request_id='close-one', hedge_id=original['hedge_id'],
                expected_version=original['version_hash'], expected_resource_hash=resources(book,'sample'),
                action=action, reason='Explicit synthetic research closure')


def test_preview_commit_retry_preserve_original_and_finances(frozen_risk):
    book,*_=frozen_risk
    original=save_parent(book,'sample',parent(frozen_risk),commit=True)
    req=close_request(book,original)
    before=resources(book,'sample')
    assert save(book,'sample',req)['proposed_status']=='CANCELLED'
    assert history(book,'sample')==[] and resources(book,'sample')==before
    closed=save(book,'sample',req,commit=True)
    after=resources(book,'sample')
    assert after!=before and save(book,'sample',req,commit=True)==closed
    assert resources(book,'sample')==after and records(book,'sample')==[original]
    assert book.sequence('sample')==2
    assert not closed['releases_reservations'] and not closed['cancels_broker_orders']
    with pytest.raises(QuantError,match='关闭请求ID'):
        save(book,'sample',dict(req,reason='changed'),commit=True)
    validate_references(book.path.parent,book)


@pytest.mark.parametrize('change,code',[
    ({'expected_version':'old'},'STALE_HEDGE_INTENT_VERSION'),
    ({'expected_resource_hash':'old'},'STALE_HEDGE_RESOURCES'),
    ({'hedge_id':'unknown'},'UNKNOWN_HEDGE_INTENT'),
    ({'action':'FILLED'},'INVALID_HEDGE_INTENT_ACTION'),
    ({'schema_version':True},'INVALID_HEDGE_INTENT_ACTION')])
def test_invalid_or_stale_closure_does_not_write(frozen_risk,change,code):
    book,*_=frozen_risk
    original=save_parent(book,'sample',parent(frozen_risk),commit=True)
    req=close_request(book,original);before=resources(book,'sample')
    with pytest.raises(QuantError) as exc:save(book,'sample',dict(req,**change),commit=True)
    assert exc.value.code==code and history(book,'sample')==[] and resources(book,'sample')==before


def test_expiry_time_and_repeat_close(frozen_risk):
    book,*_=frozen_risk
    req=parent(frozen_risk);req['valid_until']='2099-01-01T00:00:00Z'
    original=save_parent(book,'sample',req,commit=True)
    closing=close_request(book,original,'EXPIRED')
    with pytest.raises(QuantError) as exc:save(book,'sample',closing,commit=True)
    assert exc.value.code=='HEDGE_INTENT_NOT_EXPIRED'
    save(book,'sample',dict(closing,action='CANCELLED'),commit=True)
    with pytest.raises(QuantError) as exc:
        save(book,'sample',dict(closing,request_id='another',expected_resource_hash=resources(book,'sample')),commit=True)
    assert exc.value.code=='HEDGE_INTENT_CLOSED'


def test_expired_parent_can_close_at_actual_processing_time(frozen_risk):
    book,*_=frozen_risk
    original=save_parent(book,'sample',parent(frozen_risk),commit=True)
    closed=save(book,'sample',close_request(book,original,'EXPIRED'),commit=True)
    assert closed['generated_at']>original['valid_until']
    assert closed['generated_at']!=original['decision_at']
    assert history(book,'sample')==[closed]


def test_closed_parent_cannot_reopen_but_new_decision_can_use_scope(frozen_risk):
    book,*_=frozen_risk
    req=parent(frozen_risk);original=save_parent(book,'sample',req,commit=True)
    save(book,'sample',close_request(book,original),commit=True)
    assert save_parent(book,'sample',req,commit=True)==original
    revised=dict(req,request_id='revision',expected_version=original['version_hash'],
                 expected_resource_hash=resources(book,'sample'))
    with pytest.raises(QuantError) as exc:save_parent(book,'sample',revised,commit=True)
    assert exc.value.code=='HEDGE_INTENT_CLOSED'
    new=dict(req,request_id='new-decision',trigger='explicit_new_research',
             expected_resource_hash=resources(book,'sample'))
    created=save_parent(book,'sample',new,commit=True)
    assert created['hedge_id']!=original['hedge_id']
    assert records(book,'sample')[0]==original


def test_unresolved_groups_block_closure(frozen_risk):
    book,*_=frozen_risk
    original=save_parent(book,'sample',parent(frozen_risk),commit=True)
    # Simulate a valid future persisted execution-group reference.
    original['execution_groups']=['pending-group']
    original['record_hash']=digest({k:v for k,v in original.items() if k!='record_hash'})
    book.connection.execute("UPDATE tasks SET details=? WHERE task_id LIKE 'hedge-intent:%'",(canonical(original),))
    with pytest.raises(QuantError) as exc:save(book,'sample',close_request(book,original),commit=True)
    assert exc.value.code=='UNRESOLVED_HEDGE_EXECUTION' and history(book,'sample')==[]


def test_closure_backup_restore_and_tamper_rejection(frozen_risk,tmp_path):
    book,*_=frozen_risk
    original=save_parent(book,'sample',parent(frozen_risk),commit=True)
    closed=save(book,'sample',close_request(book,original),commit=True)
    cfg=tmp_path/'demo.toml'
    cfg.write_bytes((Path(__file__).resolve().parents[1]/'configs/demo.toml').read_bytes())
    create_bundle(book.path.parent,cfg,tmp_path/'bundle')
    verify_bundle(tmp_path/'bundle','demo')
    restore_bundle(tmp_path/'bundle',tmp_path/'restored','demo')
    restored=Ledger(tmp_path/'restored/runtime/demo/account.sqlite','demo')
    assert history(restored,'sample')==[closed]
    validate_references(restored.path.parent,restored);restored.close()
    bad=dict(closed,status='EXPIRED')
    book.connection.execute("UPDATE tasks SET details=? WHERE task_id LIKE 'hedge-intent-action:%'",(json.dumps(bad),))
    with pytest.raises(QuantError) as exc:validate_references(book.path.parent,book)
    assert exc.value.code=='CORRUPT_HEDGE_INTENT_ACTION'


def test_concurrent_same_request_creates_one_closure(frozen_risk):
    book,*_=frozen_risk
    original=save_parent(book,'sample',parent(frozen_risk),commit=True)
    req=close_request(book,original)
    def worker(_):
        connection=Ledger(book.path,book.environment)
        try:return save(connection,'sample',req,commit=True)
        finally:connection.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(worker,range(2)))
    assert results[0]==results[1] and history(book,'sample')==[results[0]]
    assert book.sequence('sample')==2

