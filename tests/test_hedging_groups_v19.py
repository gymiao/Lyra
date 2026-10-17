import json
from datetime import timedelta
from pathlib import Path

import pytest

from personal_quant.common import QuantError,canonical,utc
from personal_quant.hedging.allocation_store import resources
from personal_quant.hedging.groups import history,progress,save
from personal_quant.hedging.intents import save as save_parent,validate_references
from personal_quant.hedging.intent_actions import save as close_parent
from personal_quant.portfolio import Ledger
from personal_quant.portfolio.backup import create_bundle,restore_bundle,verify_bundle
from test_hedging_archive_v19 import frozen_risk
from test_hedging_exposure_v19 import risk_market
from test_hedging_intents_v19 import parent
from test_hedging_intent_actions_v19 import close_request
from conftest import event


def native_stock(book,plan_id,side='SELL',quantity=40):
    body={'as_of':'2025-01-15T21:30:00Z','sizing':{'lines':[dict(symbol='SPY',side=side,quantity=str(quantity),price='100')]}}
    book.connection.execute('INSERT INTO plans VALUES(?,?,?,?,?,?,?,?,?,?)',
        (plan_id,plan_id,1,'sample','DRAFT','BLOCKED',canonical(body),'0','{}',0))


def request(fixture):
    book,*_=fixture
    original=save_parent(book,'sample',parent(fixture),commit=True)
    native_stock(book,'native-sale')
    return original,dict(schema_version=1,request_id='group-one',hedge_id=original['hedge_id'],
        parent_version=original['version_hash'],expected_resource_hash=resources(book,'sample'),
        stages=[dict(stage_id='sale',plan_kind='stock',plan_id='native-sale',action='OPEN',depends_on=[])],
        reason='Explicit synthetic native-plan binding')


def fill(book,original,*,quantity=40,plan_id='native-sale',side='SELL',day=1):
    clock=utc(original['decision_at'])+timedelta(days=day)
    receipt=event('receipt-'+str(plan_id),side,plan_id=plan_id,symbol='SPY',quantity=quantity,price=100,
                  effective_at=clock.isoformat(),settlement_at=(clock+timedelta(days=1)).isoformat())
    book.import_events('sample',[receipt])
    return clock


def test_binding_preview_exact_match_retry_and_no_second_reservations(frozen_risk):
    book,*_=frozen_risk;original,req=request(frozen_risk)
    before=resources(book,'sample')
    preview=save(book,'sample',req)
    assert history(book,'sample')==[] and resources(book,'sample')==before
    group=save(book,'sample',req,commit=True)
    assert group['group_id']==preview['group_id'] and save(book,'sample',req,commit=True)==group
    assert not group['creates_reservations'] and not group['executable'] and book.sequence('sample')==2
    with pytest.raises(QuantError) as exc:save(book,'sample',dict(req,reason='changed'),commit=True)
    assert exc.value.code=='HEDGE_GROUP_REQUEST_CONFLICT'
    assert progress(book,'sample',group,'2026-10-10T00:00:00Z')['stages'][0]['status']=='WAITING_FACTS'


@pytest.mark.parametrize('change,code',[
    ({'parent_version':'old'},'STALE_HEDGE_INTENT_VERSION'),
    ({'expected_resource_hash':'old'},'STALE_HEDGE_RESOURCES'),
    ({'hedge_id':'missing'},'UNKNOWN_HEDGE_INTENT'),
    ({'stages':[dict(stage_id='sale',plan_kind='stock',plan_id='missing',action='OPEN',depends_on=[])]},'UNKNOWN_HEDGE_PLAN'),
    ({'stages':[dict(stage_id='sale',plan_kind='stock',plan_id='native-sale',action='OPEN',depends_on=['later'])]},'INVALID_HEDGE_GROUP')])
def test_invalid_definition_is_atomic(frozen_risk,change,code):
    book,*_=frozen_risk;_,req=request(frozen_risk);before=resources(book,'sample')
    with pytest.raises(QuantError) as exc:save(book,'sample',dict(req,**change),commit=True)
    assert exc.value.code==code and history(book,'sample')==[] and resources(book,'sample')==before


def test_candidate_quantity_conflict_and_parent_revision_blocked(frozen_risk):
    book,*_=frozen_risk;original,req=request(frozen_risk)
    native_stock(book,'wrong-sale',quantity=41)
    bad=dict(req,stages=[dict(req['stages'][0],plan_id='wrong-sale')],expected_resource_hash=resources(book,'sample'))
    with pytest.raises(QuantError) as exc:save(book,'sample',bad,commit=True)
    assert exc.value.code=='HEDGE_CANDIDATE_PLAN_MISMATCH'
    req['expected_resource_hash']=resources(book,'sample');save(book,'sample',req,commit=True)
    revision=dict(parent(frozen_risk),request_id='revision',expected_version=original['version_hash'],
                  expected_resource_hash=resources(book,'sample'))
    with pytest.raises(QuantError) as exc:save_parent(book,'sample',revision,commit=True)
    assert exc.value.code=='HEDGE_INTENT_GROUP_BOUND'


def test_partial_settlement_prefix_and_close_gate(frozen_risk):
    book,*_=frozen_risk;original,req=request(frozen_risk)
    group=save(book,'sample',req,commit=True)
    with pytest.raises(QuantError) as exc:close_parent(book,'sample',close_request(book,original),commit=True)
    assert exc.value.code=='UNRESOLVED_HEDGE_EXECUTION'
    clock=fill(book,original,quantity=20)
    assert progress(book,'sample',group,clock)['stages'][0]['status']=='SETTLEMENT_PENDING'
    assert progress(book,'sample',group,clock+timedelta(days=1))['stages'][0]['status']=='PARTIAL'
    book.import_events('sample',[event('second','SELL',plan_id='native-sale',symbol='SPY',quantity=20,price=100,
        effective_at=(clock+timedelta(days=1)).isoformat(),settlement_at=(clock+timedelta(days=2)).isoformat())])
    assert progress(book,'sample',group,clock+timedelta(days=2))['status']=='COMPLETE'
    assert progress(book,'sample',group,clock+timedelta(days=2),ledger_seq=2)['status']=='IN_PROGRESS'
    closed=close_parent(book,'sample',close_request(book,original),commit=True)
    assert closed['status']=='CANCELLED' and book.sequence('sample')==4


def test_dependency_violation_remains_after_later_settlement(frozen_risk):
    book,*_=frozen_risk;original,req=request(frozen_risk)
    native_stock(book,'native-buyback','BUY')
    req['stages'].append(dict(stage_id='exit',plan_kind='stock',plan_id='native-buyback',action='CLOSE',depends_on=['sale']))
    req['expected_resource_hash']=resources(book,'sample')
    group=save(book,'sample',req,commit=True)
    clock=fill(book,original)
    fill(book,original,plan_id='native-buyback',side='BUY')
    result=progress(book,'sample',group,clock+timedelta(days=2))
    assert result['stages'][0]['status']=='COMPLETE'
    assert result['status']=='BLOCKED'
    assert 'DEPENDENCY_NOT_COMPLETED_AT_FILL' in result['stages'][1]['checks']


def test_unrelated_facts_and_changed_native_lines_do_not_complete_group(frozen_risk):
    book,*_=frozen_risk;original,req=request(frozen_risk);group=save(book,'sample',req,commit=True)
    fill(book,original,plan_id=None)
    assert progress(book,'sample',group,'2026-10-10T00:00:00Z')['status']=='IN_PROGRESS'
    book.connection.execute("UPDATE plans SET payload=? WHERE plan_id='native-sale'",
                            (canonical({'sizing':{'lines':[dict(symbol='SPY',side='SELL',quantity='39')]}}),))
    result=progress(book,'sample',group,'2026-10-10T00:00:00Z')
    assert result['status']=='BLOCKED' and set(result['stages'][0]['checks'])=={'NATIVE_PLAN_LINES_CHANGED','NATIVE_STOCK_UNIT_BASIS_MISSING'}


def test_group_backup_restore_and_tamper(frozen_risk,tmp_path):
    book,*_=frozen_risk;_,req=request(frozen_risk);group=save(book,'sample',req,commit=True)
    cfg=tmp_path/'demo.toml';cfg.write_bytes((Path(__file__).resolve().parents[1]/'configs/demo.toml').read_bytes())
    create_bundle(book.path.parent,cfg,tmp_path/'bundle');verify_bundle(tmp_path/'bundle','demo')
    restore_bundle(tmp_path/'bundle',tmp_path/'restored','demo')
    restored=Ledger(tmp_path/'restored/runtime/demo/account.sqlite','demo')
    assert history(restored,'sample')==[group];validate_references(restored.path.parent,restored);restored.close()
    bad=dict(group,parent_version='changed')
    book.connection.execute("UPDATE tasks SET details=? WHERE task_id LIKE 'hedge-group:%'",(json.dumps(bad),))
    with pytest.raises(QuantError) as exc:validate_references(book.path.parent,book)
    assert exc.value.code=='CORRUPT_HEDGE_GROUP'


def test_native_option_open_partial_close_and_settlement_progress(ledger):
    from test_options_ledger_v19 import contract,option_event
    from test_options_lifecycle_v19 import plan
    from personal_quant.hedging.groups import _plan
    c=contract(ledger);identity=plan(ledger,c,quantity=2)
    def receipt(name,kind,**values):return dict(option_event(name,kind,c),**values)
    _,_,lines=_plan(ledger,'sample','option',identity)
    opening=dict(stage_id='open',plan_kind='option',plan_id=identity,action='OPEN',depends_on=[],lines=lines)
    closing=dict(stage_id='close',plan_kind='option',plan_id=identity,action='CLOSE',depends_on=['open'],lines=lines)
    group=dict(group_id='explicit-progress-unit',parent_version='explicit-unit-basis',stages=[opening,closing])
    ledger.import_events('sample',[event('deposit','DEPOSIT',amount=1000),
        receipt('open','OPTION_TRADE',action='OPEN',trade_side='BUY',quantity=2,price=2,plan_id=identity,
                     effective_at='2026-10-09T19:40:00Z',settlement_at='2026-10-09T19:41:00Z'),
        receipt('close-one','OPTION_TRADE',action='CLOSE',trade_side='SELL',price=3,plan_id=identity,
                     settlement_at='2026-10-09T19:46:00Z')])
    partial=progress(ledger,'sample',group,'2026-10-09T19:46:00Z')
    assert partial['stages'][0]['status']=='COMPLETE' and partial['stages'][1]['status']=='PARTIAL'
    ledger.import_events('sample',[receipt('close-two','OPTION_TRADE',action='CLOSE',trade_side='SELL',price=3,plan_id=identity,
                     effective_at='2026-10-09T19:47:00Z',settlement_at='2026-10-09T19:48:00Z')])
    assert progress(ledger,'sample',group,'2026-10-09T19:47:00Z')['stages'][1]['status']=='SETTLEMENT_PENDING'
    assert progress(ledger,'sample',group,'2026-10-09T19:48:00Z')['status']=='COMPLETE'
    assert ledger.snapshot('sample','2026-10-09T19:48:00Z')['settled_cash']=='1200'


def test_split_blocks_original_units_instead_of_fake_completion(frozen_risk):
    book,*_=frozen_risk;original,req=request(frozen_risk);group=save(book,'sample',req,commit=True)
    book.import_events('sample',[event('split','SPLIT',symbol='SPY',ratio=2,
                         effective_at=(utc(original['decision_at'])+timedelta(days=1)).isoformat())])
    result=progress(book,'sample',group,'2026-10-10T00:00:00Z')
    assert result['status']=='BLOCKED'
    assert 'STOCK_UNITS_CHANGED_REQUIRES_GROUP_REVISION' in result['stages'][0]['checks']



def test_rehashed_native_and_group_quantity_cannot_change_frozen_candidate(frozen_risk):
    from copy import deepcopy
    from personal_quant.common import digest
    book,*_=frozen_risk;_,req=request(frozen_risk);group=save(book,'sample',req,commit=True)
    changed=deepcopy(group);changed['stages'][0]['lines'][0]['quantity']='39'
    changed['group_basis']['stages']=changed['stages'];changed['group_id']=digest(changed['group_basis'])
    changed['record_hash']=digest({k:v for k,v in changed.items() if k!='record_hash'})
    body=json.loads(book.connection.execute('SELECT payload FROM plans WHERE plan_id=?',('native-sale',)).fetchone()[0])
    body['sizing']['lines'][0]['quantity']='39'
    book.connection.execute('UPDATE plans SET payload=? WHERE plan_id=?',(canonical(body),'native-sale'))
    from personal_quant.hedging.groups import PREFIX
    key=PREFIX+digest({'account_id':'sample','request_id':req['request_id']})
    book.connection.execute('UPDATE tasks SET details=? WHERE task_id=?',(canonical(changed),key))
    with pytest.raises(QuantError) as exc:history(book,'sample')
    assert exc.value.code=='CORRUPT_HEDGE_GROUP'
