import hashlib
import json
from pathlib import Path
import pytest
from personal_quant.common import QuantError,digest
from personal_quant.options.incidents import save,status
from personal_quant.options.receipts import import_batch
from personal_quant.hedging.monitor import monitor,require_planning
from personal_quant.portfolio import Ledger
from personal_quant.portfolio.backup import create_bundle,verify_bundle,restore_bundle,_validate_references
from test_options_receipts_v19 import account,CLOCK
from test_options_receipt_risk_v19 import exercise_pair
from conftest import event


@pytest.fixture
def review(account,tmp_path):
    book,batch=exercise_pair(account);original=import_batch(book,'sample',batch,CLOCK)
    incident=status(book,'sample',CLOCK)['incidents'][0]
    book.reconcile('sample',{'account_id':'sample','currency':'USD','as_of':CLOCK,
        'cash_basis':'settled','cash':19600,'positions':{},'option_positions':{},'equity':19600})
    rid=book.connection.execute('SELECT max(id) FROM reconciliations').fetchone()[0]
    directory=tmp_path/'evidence';directory.mkdir();blob=b'synthetic statement: put and call exercise, final shares zero'
    (directory/'statement.txt').write_bytes(blob)
    request={'schema_version':1,'request_id':'review-1','incident_id':incident['incident_id'],
        'expected_hash':incident['view_hash'],'expected_sequence':5,'as_of':CLOCK,
        'recovery_event_ids':['call-exercise'],'reconciliation_id':rid,'reviewer':'fixture-reviewer',
        'reason':'同批Call实际行权抵销Put交割；核对现金19600/零股',
        'evidence_type':'test','evidence_files':{'statement.txt':hashlib.sha256(blob).hexdigest()}}
    return book,request,directory,original


def test_final_flat_balance_does_not_silently_clear_intermediate_incident(review):
    book,request,directory,original=review
    assert monitor(book,'sample',CLOCK)['status']=='BLOCKED'
    with pytest.raises(QuantError,match='OPTION_INCIDENT_REVIEW_REQUIRED'):require_planning(book,'sample',CLOCK)
    before=book.connection.execute('SELECT count(*) FROM tasks').fetchone()[0]
    assert save(book,'sample',request,directory)['status']=='PREVIEW'
    assert book.connection.execute('SELECT count(*) FROM tasks').fetchone()[0]==before
    accepted=save(book,'sample',request,directory,commit=True)
    assert accepted['status']=='REVIEWED' and not accepted['executable']
    assert save(book,'sample',request,directory,commit=True)==accepted
    assert status(book,'sample',CLOCK)['status']=='REVIEWED'
    assert monitor(book,'sample',CLOCK)['status']=='NO_ACTION'
    assert original['risk_history']['prefixes'][0]['snapshot']['positions']=={'SPY':'-100'}
    assert book.sequence('sample')==5


@pytest.mark.parametrize('field,value,code',[
    ('expected_sequence',4,'STALE_PREVIEW'),('expected_hash','wrong','STALE_INCIDENT'),
    ('recovery_event_ids',['put-exercise'],'INVALID_RECOVERY_FACT'),
    ('recovery_event_ids',['unknown'],'INVALID_RECOVERY_FACT'),
    ('reconciliation_id',999,'INCIDENT_RECONCILIATION_REQUIRED')])
def test_unsupported_waivers_never_change_financial_state(review,field,value,code):
    book,request,directory,_=review
    with pytest.raises(QuantError) as exc:save(book,'sample',{**request,field:value},directory,commit=True)
    assert exc.value.code==code
    assert status(book,'sample',CLOCK)['status']=='BLOCKED' and book.sequence('sample')==5


def test_recovery_cannot_omit_offsetting_fact(review):
    book,request,directory,_=review
    book.import_events('sample',[event('extra','DEPOSIT',amount=10,effective_at=CLOCK)])
    with pytest.raises(QuantError) as exc:
        save(book,'sample',{**request,'expected_sequence':6,'recovery_event_ids':['extra']},directory,commit=True)
    assert exc.value.code=='INCOMPLETE_RECOVERY_FACTS'


def test_review_tamper_blocks_monitor_and_full_backup(review,tmp_path):
    book,request,directory,_=review;accepted=save(book,'sample',request,directory,commit=True)
    path=tmp_path/'config.toml';path.write_bytes((Path(__file__).resolve().parents[1]/'configs/demo.toml').read_bytes())
    create_bundle(book.path.parent,path,tmp_path/'bundle');verify_bundle(tmp_path/'bundle','demo')
    restore_bundle(tmp_path/'bundle',tmp_path/'restored','demo')
    recovered=Ledger(tmp_path/'restored/runtime/demo/account.sqlite','demo')
    try:assert status(recovered,'sample',CLOCK)==status(book,'sample',CLOCK)
    finally:recovered.close()
    target=book.path.parent/'options/incident-evidence'/accepted['request_hash']/'statement.txt'
    target.write_text('changed')
    assert monitor(book,'sample',CLOCK)['checks'][0]['code']=='CORRUPT_INCIDENT_REVIEW'
    with pytest.raises(QuantError,match='凭据'):_validate_references(book.path.parent,book)


def test_same_review_id_cannot_replace_evidence_or_reason(review):
    book,request,directory,_=review;save(book,'sample',request,directory,commit=True)
    with pytest.raises(QuantError) as exc:
        save(book,'sample',{**request,'reason':'different'},directory,commit=True)
    assert exc.value.code=='EVENT_CONFLICT'
    with pytest.raises(QuantError) as exc:
        save(book,'sample',{**request,'request_id':'another'},directory,commit=True)
    assert exc.value.code=='INCIDENT_ALREADY_REVIEWED'


def test_rehashed_financial_review_tamper_still_blocked(review):
    book,request,directory,_=review;accepted=save(book,'sample',request,directory,commit=True)
    accepted['snapshot']['settled_cash']='99999'
    accepted['review_hash']=digest({k:v for k,v in accepted.items() if k!='review_hash'})
    book.connection.execute('UPDATE tasks SET details=? WHERE task_id=?',
                            (json.dumps(accepted),accepted['audit_task_id']))
    assert monitor(book,'sample',CLOCK)['checks'][0]['code']=='CORRUPT_INCIDENT_REVIEW'


def test_later_account_change_does_not_rewrite_old_review(review):
    book,request,directory,_=review;accepted=save(book,'sample',request,directory,commit=True)
    book.import_events('sample',[event('later','DEPOSIT',amount=10,effective_at=CLOCK)])
    assert status(book,'sample',CLOCK)['incidents'][0]['review']==accepted
    assert book.sequence('sample')==6
