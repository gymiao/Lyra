import json
import pytest
from personal_quant.common import QuantError, digest
from personal_quant.options.receipts import import_batch
from personal_quant.options.receipt_risk import history
from personal_quant.portfolio.backup import _validate_references
from test_options_receipts_v19 import account, batch, CLOCK
from test_options_ledger_v19 import option_event
from personal_quant.options.ledger import register_contract
from conftest import event


def exercise_pair(account):
    book,put,_,_=account
    body=put.content();body.update(contract_id='SPY-CALL-100-RISK',right='CALL')
    call=register_contract(book,body)
    book.import_events('sample',[event('deposit','DEPOSIT',amount=20000),
        option_event('put-open','OPTION_TRADE',put,action='OPEN',trade_side='BUY',price=2),
        option_event('call-open','OPTION_TRADE',call,action='OPEN',trade_side='BUY',price=2)])
    first=option_event('put-exercise','OPTION_EXERCISE',put,position_side='LONG')
    second=option_event('call-exercise','OPTION_EXERCISE',call,position_side='LONG')
    return book,batch([first,second],3)


def test_same_time_delivery_short_not_erased_by_final_flat_balance(account):
    book,request=exercise_pair(account)
    audit=import_batch(book,'sample',request,CLOCK)
    risk=audit['risk_history'];first,second=risk['prefixes']
    assert first['effective_at']==second['effective_at']
    assert first['ledger_seq']==4 and second['ledger_seq']==5
    assert first['snapshot']['positions']=={'SPY':'-100'}
    assert first['status']=='REVIEW_REQUIRED'
    assert second['snapshot']['positions']=={} and second['status']=='NO_ACCOUNT_ANOMALY'
    assert risk['has_intermediate_anomaly'] and not risk['current_account_anomaly']
    assert risk['final_snapshot']['settled_cash']=='19600'
    assert first['valuation_status']=='NOT_EVALUATED' and first['snapshot']['equity'] is None
    assert import_batch(book,'sample',request,CLOCK)==audit
    assert book.sequence('sample')==5
    assert history(book,'sample')[0]['risk_history']==risk


def test_duplicate_facts_have_no_new_prefixes(account):
    book,request=exercise_pair(account)
    import_batch(book,'sample',request,CLOCK)
    duplicate=import_batch(book,'sample',batch(request['rows'],5,'second-file'),CLOCK)
    assert duplicate['result']['added']==0
    assert duplicate['risk_history']['prefixes']==[]
    assert history(book,'sample')[0]['risk_history']['has_intermediate_anomaly']


@pytest.mark.parametrize('tamper',['snapshot','prefix','rehashed_balance'])
def test_audit_tamper_rejected_by_replay_and_backup(account,tamper):
    book,request=exercise_pair(account)
    audit=import_batch(book,'sample',request,CLOCK)
    risk=audit['risk_history']
    if tamper in {'snapshot','rehashed_balance'}:
        risk['prefixes'][0]['snapshot']['positions']={}
        if tamper=='rehashed_balance':risk['audit_hash']=digest({k:v for k,v in risk.items() if k!='audit_hash'})
    else:
        risk['prefixes'][0]['ledger_prefix_hash']='wrong'
        risk['audit_hash']=digest({k:v for k,v in risk.items() if k!='audit_hash'})
    book.connection.execute('UPDATE tasks SET details=? WHERE task_id=?',
                            (json.dumps(audit),audit['audit_task_id']))
    with pytest.raises(QuantError,match='逐凭据'):import_batch(book,'sample',request,CLOCK)
    with pytest.raises(QuantError,match='逐凭据'):_validate_references(book.path.parent,book)


def test_legacy_batch_not_relabelled_as_prefix_proof(account):
    book,request=exercise_pair(account)
    audit=import_batch(book,'sample',request,CLOCK);audit.pop('risk_history')
    book.connection.execute('UPDATE tasks SET details=? WHERE task_id=?',
                            (json.dumps(audit),audit['audit_task_id']))
    assert history(book,'sample')[0]['proof_status']=='LEGACY_UNVERIFIED'
    assert book.sequence('sample')==5
