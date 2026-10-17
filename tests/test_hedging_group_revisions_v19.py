from datetime import timedelta
import json
from pathlib import Path
import pytest
from personal_quant.common import QuantError,canonical,decimal as D,digest,utc
from personal_quant.hedging.allocation_store import resources
from personal_quant.hedging.group_revisions import save as revise,heads
from personal_quant.hedging.groups import history,progress,save
from personal_quant.hedging.intent_actions import save as close_parent
from personal_quant.portfolio import Ledger
from personal_quant.portfolio.backup import create_bundle,verify_bundle,restore_bundle
from test_hedging_groups_v19 import request,native_stock,fill
from test_hedging_archive_v19 import frozen_risk
from test_hedging_exposure_v19 import risk_market
from test_hedging_intent_actions_v19 import close_request
from conftest import event


@pytest.fixture
def partial(frozen_risk):
    book,*_=frozen_risk;parent,req=request(frozen_risk);root=save(book,'sample',req,commit=True)
    clock=fill(book,parent,quantity=10)+timedelta(days=2)
    book.connection.execute("UPDATE plans SET execution_status='SUPERSEDED' WHERE plan_id='native-sale'")
    native_stock(book,'native-rest',quantity=30)
    request2={'schema_version':1,'request_id':'amend-1','previous_group_id':root['group_id'],
              'expected_group_hash':root['record_hash'],'expected_resource_hash':resources(book,'sample'),
              'as_of':clock.isoformat(),'replacements':{'sale':'native-rest'},'reason':'保留已卖10，剩余30引用新计划'}
    return book,parent,root,request2,clock


def test_partial_amendment_conserves_fact_target_and_resources(partial):
    book,parent,root,request2,clock=partial;before=resources(book,'sample')
    preview=revise(book,'sample',request2)
    assert len(history(book,'sample'))==1 and resources(book,'sample')==before
    amended=revise(book,'sample',request2,commit=True)
    assert amended['group_id']==preview['group_id'] and amended['revision']==2
    assert [s['lines'][0]['quantity'] for s in amended['stages']]==['10','30']
    assert not amended['creates_reservations'] and not amended['executable']
    assert resources(book,'sample')!=before and book.sequence('sample')==3 # registry is part of CAS
    state=book.snapshot('sample',clock)
    assert D(state['settled_cash'])==21000 and state['positions']=={'SPY':'90'} and D(state['reserved_cash'])==0
    assert revise(book,'sample',request2,commit=True)==amended
    assert heads(history(book,'sample'))==[amended]
    assert heads(history(book,'sample'),parent['decision_at'])==[root]
    assert heads(history(book,'sample'),clock,2)==[root]
    status=progress(book,'sample',amended,clock)
    assert [s['status'] for s in status['stages']]==['COMPLETE','WAITING_FACTS']
    fill(book,parent,quantity=30,plan_id='native-rest',day=4)
    assert progress(book,'sample',amended,clock+timedelta(days=3))['status']=='COMPLETE'
    assert progress(book,'sample',root,clock+timedelta(days=3))['status']=='IN_PROGRESS'
    assert close_parent(book,'sample',close_request(book,parent),commit=True)['status']=='CANCELLED'
    assert book.snapshot('sample',clock+timedelta(days=3))['positions']=={'SPY':'60'}


@pytest.mark.parametrize('problem,code',[
    ('stale','STALE_HEDGE_GROUP_REVISION'),('resources','STALE_HEDGE_RESOURCES'),
    ('not-ended','NATIVE_PLAN_NOT_RELEASED'),('reserved','NATIVE_PLAN_NOT_RELEASED'),
    ('quantity','HEDGE_REMAINING_QUANTITY_MISMATCH'),('expired','HEDGE_INTENT_EXPIRED')])
def test_invalid_amendment_is_atomic(partial,problem,code):
    book,_,_,req,_=partial
    if problem=='stale':req={**req,'expected_group_hash':'old'}
    if problem=='resources':req={**req,'expected_resource_hash':'old'}
    if problem=='not-ended':book.connection.execute("UPDATE plans SET execution_status='READY' WHERE plan_id='native-sale'")
    if problem=='reserved':book.connection.execute("UPDATE plans SET reserved_cash='1' WHERE plan_id='native-sale'")
    if problem in {'not-ended','reserved'}:req={**req,'expected_resource_hash':resources(book,'sample')}
    if problem=='quantity':
        native_stock(book,'wrong',quantity=31);req={**req,'replacements':{'sale':'wrong'},'expected_resource_hash':resources(book,'sample')}
    if problem=='expired':req={**req,'as_of':'2026-10-10T00:00:00Z'}
    before=resources(book,'sample')
    with pytest.raises(QuantError) as exc:revise(book,'sample',req,commit=True)
    assert exc.value.code==code and len(history(book,'sample'))==1 and resources(book,'sample')==before


def test_late_old_fill_is_visible_instead_of_disappearing(partial):
    book,parent,_,req,clock=partial;amended=revise(book,'sample',req,commit=True)
    late=event('late-old','SELL',plan_id='native-sale',symbol='SPY',quantity=1,price=100,
               effective_at=(clock+timedelta(days=1)).isoformat(),settlement_at=(clock+timedelta(days=2)).isoformat())
    book.import_events('sample',[late])
    state=progress(book,'sample',amended,clock+timedelta(days=2))
    assert state['status']=='BLOCKED' and 'UNEXPECTED_OR_EXCESS_LINKED_FACT' in state['stages'][0]['checks']
    assert book.sequence('sample')==4 and book.snapshot('sample',clock+timedelta(days=2))['positions']=={'SPY':'89'}


def test_empty_retired_slice_still_catches_late_facts(frozen_risk):
    book,*_=frozen_risk;parent,req=request(frozen_risk);root=save(book,'sample',req,commit=True)
    book.connection.execute("UPDATE plans SET execution_status='CANCELLED' WHERE plan_id='native-sale'")
    native_stock(book,'rest-all')
    new={'schema_version':1,'request_id':'replace-unfilled','previous_group_id':root['group_id'],
         'expected_group_hash':root['record_hash'],'expected_resource_hash':resources(book,'sample'),
         'as_of':parent['decision_at'],'replacements':{'sale':'rest-all'},'reason':'明确未成交取消后替换'}
    amended=revise(book,'sample',new,commit=True)
    assert amended['stages'][0]['lines']==[]
    fill(book,parent,quantity=1)
    assert progress(book,'sample',amended,utc(parent['decision_at'])+timedelta(days=3))['status']=='BLOCKED'


def test_backdated_new_fill_cannot_use_revision_rules(partial):
    book,parent,_,req,clock=partial;amended=revise(book,'sample',req,commit=True)
    fill(book,parent,quantity=30,plan_id='native-rest',day=2)
    view=progress(book,'sample',amended,clock+timedelta(days=2))
    assert view['status']=='BLOCKED' and 'LATE_FACT_BEFORE_GROUP_REVISION' in view['stages'][1]['checks']


def test_revision_restore_and_rehashed_definition_tamper(partial,tmp_path):
    book,_,_,req,_=partial;amended=revise(book,'sample',req,commit=True)
    cfg=tmp_path/'demo.toml';cfg.write_bytes((Path(__file__).resolve().parents[1]/'configs/demo.toml').read_bytes())
    create_bundle(book.path.parent,cfg,tmp_path/'bundle');verify_bundle(tmp_path/'bundle','demo')
    restore_bundle(tmp_path/'bundle',tmp_path/'restored','demo')
    restored=Ledger(tmp_path/'restored/runtime/demo/account.sqlite','demo')
    try:assert heads(history(restored,'sample'))==[amended]
    finally:restored.close()
    bad=json.loads(json.dumps(amended));bad['stages'][1]['lines'][0]['quantity']='31'
    bad['record_hash']=digest({k:v for k,v in bad.items() if k!='record_hash'})
    book.connection.execute("UPDATE tasks SET details=? WHERE task_id LIKE 'hedge-group-revision:%'",(canonical(bad),))
    with pytest.raises(QuantError) as exc:history(book,'sample')
    assert exc.value.code=='CORRUPT_HEDGE_GROUP_REVISION'
