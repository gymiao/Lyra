import pytest
from personal_quant.common import digest
from personal_quant.options.incidents import save,status
from personal_quant.options.receipts import import_batch
from personal_quant.hedging.monitor import monitor
from test_options_incidents_v19 import review
from test_options_receipts_v19 import account,CLOCK
from conftest import event


def test_reversal_and_corrected_delivery_can_be_cited_without_erasing_old_incident(review):
    book,request,directory,original=review
    call=original['request']['rows'][1]
    book.import_events('sample',[event('undo-call','REVERSAL',reference_event_id='call-exercise',
                                      effective_at=call['effective_at']),
                                {**call,'event_id':'correct-call'}])
    book.reconcile('sample',{'account_id':'sample','currency':'USD','as_of':CLOCK,
                           'cash_basis':'settled','cash':19600,'positions':{},'option_positions':{},'equity':19600})
    rid=book.connection.execute('SELECT max(id) FROM reconciliations').fetchone()[0]
    corrected={**request,'expected_sequence':7,'reconciliation_id':rid,
               'recovery_event_ids':['call-exercise','undo-call','correct-call']}
    saved=save(book,'sample',corrected,directory,commit=True)
    assert set(saved['recovery_events'])=={'call-exercise','undo-call','correct-call'}
    assert status(book,'sample',CLOCK)['incidents'][0]['view']['snapshot']['positions']=={'SPY':'-100'}
    assert monitor(book,'sample',CLOCK)['status']=='NO_ACTION' and book.sequence('sample')==7


def test_pending_context_is_not_mislabelled_as_financial_deficit(account):
    book,c,_,_=account
    book.import_events('sample',[event('context-fund','DEPOSIT',amount=1000)])
    supported=event('context-open','OPTION_TRADE',contract_version=c.version_hash,quantity=1,
                    action='OPEN',trade_side='BUY',price=2,effective_at='2026-10-09T19:45:00Z',
                    settlement_at='2026-10-09T20:00:00Z')
    unknown={**supported,'event_id':'context-pending','kind':'UNKNOWN_OPTION_ACTION'}
    rows=[unknown,supported]
    result=import_batch(book,'sample',{'request_id':'context-receipts','rows':rows,
                     'expected_sequence':book.sequence('sample'),'expected_hash':digest(rows)},CLOCK)
    assert result['risk_history']['prefixes'][0]['status']=='REVIEW_REQUIRED'
    assert status(book,'sample',CLOCK)['status']=='NO_ACTION'
    assert monitor(book,'sample',CLOCK)['status']=='BLOCKED'
