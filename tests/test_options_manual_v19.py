import pytest
from personal_quant.options.lifecycle import manual_action,review
from personal_quant.common import QuantError
from test_options_lifecycle_v19 import plan
from test_options_ledger_v19 import contract,option_event
from conftest import event


def test_partial_fill_converts_reserve_once_and_cancel_requires_confirmed_end(ledger):
    c=contract(ledger);identity=plan(ledger,c)
    ledger.import_events('sample',[event('deposit','DEPOSIT',amount=1000)])
    request={'request_id':'submitted','plan_id':identity,'action':'record-submitted','as_of':'2026-10-09T19:40:00Z',
      'expected_sequence':1,'reason':'Test statement: manually submitted limit order',
      'orders':[{'contract_id':c.contract_id,'side':'BUY','contracts':2,'limit_price':2,'fee_per_contract':1}]}
    first=manual_action(ledger,request);assert manual_action(ledger,request)==first
    before=ledger.snapshot('sample','2026-10-09T19:41:00Z')
    assert before['available_cash']=='598' and before['reserved_cash']=='402' and before['equity']=='1000'
    row=option_event('fill','OPTION_TRADE',c,action='OPEN',trade_side='BUY',price=2,fee=1,plan_id=identity)
    ledger.import_events('sample',[row]);ledger.import_events('sample',[row])
    state=ledger.snapshot('sample','2026-10-10T00:00:00Z',{c.contract_id:2})
    assert state['settled_cash']=='799' and state['reserved_cash']=='201' and state['available_cash']=='598'
    assert state['equity']=='999' and review(ledger,identity,'2026-10-10T00:00:00Z')['status']=='PARTIAL'
    end={**request,'request_id':'end','action':'cancel','as_of':'2026-10-09T21:00:00Z','expected_sequence':2,'orders':[]}
    with pytest.raises(QuantError,match='先确认'):manual_action(ledger,end)
    manual_action(ledger,{**end,'action':'confirm-ended'})
    manual_action(ledger,{**end,'request_id':'cancel'})
    state=ledger.snapshot('sample','2026-10-10T00:00:00Z',{c.contract_id:2})
    assert state['available_cash']=='799' and state['reserved_cash']=='0' and state['equity']=='999'
    assert review(ledger,identity,'2026-10-10T00:00:00Z')['status']=='CANCELLED'
    # Later confirmation must not erase earlier commitments or leak backwards.
    before_submit=ledger.snapshot('sample','2026-10-09T19:39:00Z')
    during=ledger.snapshot('sample','2026-10-09T19:41:00Z')
    assert before_submit['reserved_cash']=='0' and during['reserved_cash']=='402'


def test_manual_option_commitment_invalidates_existing_etf_check_without_releasing_it(ledger,market,config):
    from test_plans import ready
    service,etf=ready(ledger,market,config)
    before=service.get(etf['plan_id']);c=contract(ledger);identity=plan(ledger,c)
    request={'request_id':'manual','plan_id':identity,'action':'record-submitted','as_of':'2026-10-09T19:40:00Z',
      'expected_sequence':1,'reason':'Synthetic existing manual order',
      'orders':[{'contract_id':c.contract_id,'side':'BUY','contracts':2,'limit_price':2,'fee_per_contract':1}]}
    manual_action(ledger,request)
    after=service.get(etf['plan_id'])
    assert before['check_status']=='PASSED' and after['check_status']=='BLOCKED'
    assert after['reserved_cash']==before['reserved_cash']
    assert after['execution_status']==before['execution_status']
