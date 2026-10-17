import json
import pytest
from personal_quant.common import canonical,digest,QuantError
from personal_quant.options.lifecycle import review,resolve_pending
from personal_quant.options.ledger import register_contract,import_facts
from test_options_ledger_v19 import contract,option_event
from conftest import event


def plan(book,c,quantity=2):
    body={'plan_id':'test-option-plan','account_id':'sample','status':'DRAFT','checks':['ENGINE_NOT_VALIDATED'],
          'selection':{'legs':[{'contract':c.content()}]},
          'check_status':'BLOCKED','executable':False,'sizing':{'lines':[{'contract_id':c.contract_id,
          'contract_version':c.version_hash,'side':'BUY','contracts':str(quantity)}]}}
    book.connection.execute('INSERT INTO option_plans VALUES(?,?,?,?,?,?,?)',
        (body['plan_id'],'sample','DRAFT',canonical(body),'0','{}','2026-10-09T19:46:00Z'))
    return body['plan_id']


def test_explicit_option_partial_fill_duplicate_and_reversal(ledger):
    c=contract(ledger);identity=plan(ledger,c)
    ledger.import_events('sample',[event('deposit','DEPOSIT',amount=1000)])
    row=option_event('fill1','OPTION_TRADE',c,action='OPEN',trade_side='BUY',price=2,fee=1,plan_id=identity)
    ledger.import_events('sample',[row]);ledger.import_events('sample',[row])
    partial=review(ledger,identity,'2026-10-10T00:00:00Z')
    assert partial['status']=='PARTIAL' and partial['progress']['remaining_contracts']=={c.contract_id:'1'}
    assert not partial['executable']
    ledger.import_events('sample',[dict(row,event_id='fill2')])
    assert review(ledger,identity,'2026-10-10T00:00:00Z')['status']=='FILLED'
    assert ledger.snapshot('sample','2026-10-10T00:00:00Z',{c.contract_id:2})['settled_cash']=='598'
    ledger.import_events('sample',[event('reverse','REVERSAL',reference_event_id='fill2',effective_at=row['effective_at'])])
    assert review(ledger,identity,'2026-10-10T00:00:00Z')['status']=='PARTIAL'
    assert ledger.snapshot('sample','2026-10-10T00:00:00Z',{c.contract_id:2})['settled_cash']=='799'


def test_excess_fact_preserved_and_blocks_account(ledger):
    c=contract(ledger);identity=plan(ledger,c,1)
    ledger.import_events('sample',[event('deposit','DEPOSIT',amount=1000),
        dict(option_event('overfill','OPTION_TRADE',c,action='OPEN',trade_side='BUY',price=2,plan_id=identity),quantity=2)])
    result=review(ledger,identity,'2026-10-10T00:00:00Z')
    assert result['status']=='PARTIAL' and result['progress']['fact_anomalies']
    snapshot=ledger.snapshot('sample','2026-10-10T00:00:00Z',{c.contract_id:2})
    assert snapshot['settled_cash']=='600' and snapshot['option_positions']=={c.contract_id:'2'}
    assert any('超过建议' in issue for issue in snapshot['anomalies'])
    previous=ledger.connection.execute('SELECT payload FROM option_plans WHERE plan_id=?',(identity,)).fetchone()[0]
    historical=review(ledger,identity,'2026-10-08T00:00:00Z')
    assert historical['status']=='DRAFT'
    assert ledger.connection.execute('SELECT payload FROM option_plans WHERE plan_id=?',(identity,)).fetchone()[0]==previous
    assert any('超过建议' in issue for issue in ledger.snapshot('sample','2026-10-10T00:00:00Z',{c.contract_id:2})['anomalies'])
    # A snapshot frozen before this fill must not borrow its later plan anomaly.
    earlier=ledger.snapshot('sample','2026-10-10T00:00:00Z',{},ledger_seq=1)
    assert earlier['anomalies']==[] and earlier['equity']=='1000'


def test_pending_receipt_retried_after_contract_registered_and_audit_is_idempotent(ledger):
    c=contract(ledger);body=c.content();body['contract_id']='UNKNOWN-UNTIL-REGISTERED'
    from personal_quant.options.contracts import OptionContract
    unknown=OptionContract.from_dict(body)
    raw=option_event('late-contract','OPTION_TRADE',unknown,action='OPEN',trade_side='BUY',price=2)
    result=import_facts(ledger,'sample',[raw],expected_sequence=0)
    assert result['pending_events']==['late-contract'] and ledger.sequence('sample')==0
    register_contract(ledger,body)
    with pytest.raises(QuantError,match='发生变化'):
        resolve_pending(ledger,'sample',raw['event_id'],expected_sequence=0,expected_hash='wrong')
    resolved=resolve_pending(ledger,'sample',raw['event_id'],expected_sequence=0,expected_hash=digest(raw))
    assert resolved['receipt']==raw and resolved['import']['added']==1
    assert resolve_pending(ledger,'sample',raw['event_id'],expected_sequence=0,expected_hash=digest(raw))==resolved
    assert ledger.connection.execute('SELECT count(*) FROM pending_option_events').fetchone()[0]==0
    assert ledger.sequence('sample')==1


def test_option_plan_resource_reservations_share_cash_and_stock_budget(ledger):
    c=contract(ledger);identity=plan(ledger,c)
    ledger.import_events('sample',[event('deposit','DEPOSIT',amount=11000),
        event('stock','BUY',symbol='SPY',quantity=100,price=100,settlement_at='2024-07-02T20:00:00Z')])
    # Inject reservation state to verify the shared accounting boundary; this does not activate execution.
    ledger.connection.execute('UPDATE option_plans SET reserved_cash=?,reserved_positions=? WHERE plan_id=?',
                              ('200',json.dumps({'SPY':'100'}),identity))
    snapshot=ledger.snapshot('sample','2026-10-10T00:00:00Z',{'SPY':100})
    assert snapshot['available_cash']=='800' and snapshot['reserved_positions']=={'SPY':'100'}
    assert snapshot['equity']=='11000' and snapshot['investment_pnl']=='0'


def test_linked_close_preserves_fill_progress_and_tracks_settlement(ledger):
    c=contract(ledger);identity=plan(ledger,c)
    ledger.import_events('sample',[event('deposit','DEPOSIT',amount=1000),
        dict(option_event('open','OPTION_TRADE',c,action='OPEN',trade_side='BUY',price=2,plan_id=identity),quantity=2)])
    close=option_event('close-one','OPTION_TRADE',c,action='CLOSE',trade_side='SELL',price=3,plan_id=identity)
    close.update(effective_at='2026-10-09T19:46:00Z',settlement_at='2026-10-09T20:00:00Z')
    ledger.import_events('sample',[close]);ledger.import_events('sample',[close])
    pending=review(ledger,identity,'2026-10-09T19:47:00Z')
    assert pending['status']=='FILLED' and pending['progress']['fact_anomalies']==[]
    assert pending['progress']['filled_contracts']=={c.contract_id:'2'}
    assert pending['lifecycle']['status']=='SETTLEMENT_PENDING'
    assert pending['lifecycle']['position_status']=='PARTIAL_CLOSE'
    assert pending['lifecycle']['open_contracts']=={c.contract_id:'1'}
    assert ledger.snapshot('sample','2026-10-09T20:01:00Z',{c.contract_id:3})['equity']=='1200'
    ledger.import_events('sample',[dict(close,event_id='close-two',effective_at='2026-10-09T19:47:00Z')])
    completed=review(ledger,identity,'2026-10-09T20:01:00Z')
    assert completed['status']=='FILLED' and completed['lifecycle']['status']=='CLOSED'
    assert completed['progress']['remaining_contracts']=={c.contract_id:'0'}
    assert ledger.snapshot('sample','2026-10-09T20:01:00Z')['equity']=='1200'
    # Historical views and ledger sequence must not inherit future exits.
    prior=review(ledger,identity,'2026-10-09T19:45:30Z')
    assert prior['lifecycle']['position_status']=='OPEN'
    assert prior['lifecycle']['open_contracts']=={c.contract_id:'2'}
    from personal_quant.options.lifecycle import refresh
    before_exit=refresh(ledger,'sample','2026-10-09T20:01:00Z',persist=False,ledger_seq=2)[0]
    assert before_exit['lifecycle']['status']=='OPEN'


@pytest.mark.parametrize('side,kind,pending_status',[
    ('BUY','OPTION_EXERCISE','EXERCISE_PENDING'),('SELL','OPTION_ASSIGNMENT','ASSIGNMENT_PENDING')])
def test_linked_delivery_is_lifecycle_not_open_fill_anomaly(ledger,side,kind,pending_status):
    c=contract(ledger);identity=plan(ledger,c,1)
    if side=='SELL':
        body=json.loads(ledger.connection.execute('SELECT payload FROM option_plans').fetchone()[0])
        body['sizing']['lines'][0]['side']='SELL'
        ledger.connection.execute('UPDATE option_plans SET payload=?',(canonical(body),))
    ledger.import_events('sample',[event('deposit','DEPOSIT',amount=20000),
        event('stock','BUY',symbol='SPY',quantity=100,price=100,settlement_at='2024-07-02T20:00:00Z'),
        option_event('open','OPTION_TRADE',c,action='OPEN',trade_side=side,price=2,plan_id=identity)])
    delivery=option_event('delivery',kind,c,position_side='LONG' if side=='BUY' else 'SHORT',plan_id=identity)
    delivery.update(effective_at='2026-10-09T19:46:00Z')
    ledger.import_events('sample',[delivery])
    pending=review(ledger,identity,'2026-10-09T19:47:00Z')
    assert pending['status']=='FILLED' and pending['progress']['fact_anomalies']==[]
    assert pending['lifecycle']['status']==pending_status
    assert pending['lifecycle']['position_status']=='CLOSED'
    settled=review(ledger,identity,'2026-10-09T20:01:00Z')
    assert settled['lifecycle']['status']=='CLOSED'
    state=ledger.snapshot('sample','2026-10-09T20:01:00Z',{'SPY':100})
    assert state['positions']==({} if side=='BUY' else {'SPY':'200'})
    assert state['settled_cash']==('19800' if side=='BUY' else '200')
    assert state['anomalies']==[]


def test_exit_cannot_consume_other_plans_opened_contracts(ledger):
    c=contract(ledger);identity=plan(ledger,c,1)
    ledger.import_events('sample',[event('deposit','DEPOSIT',amount=1000),
        option_event('other-open','OPTION_TRADE',c,action='OPEN',trade_side='BUY',price=2),
        option_event('wrong-close','OPTION_TRADE',c,action='CLOSE',trade_side='SELL',price=3,plan_id=identity)])
    state=review(ledger,identity,'2026-10-09T20:01:00Z')
    assert state['lifecycle']['status']=='RECONCILIATION_REQUIRED'
    assert any('超过本计划持仓' in issue for issue in state['progress']['fact_anomalies'])
    assert state['progress']['filled_contracts']=={}
    # Actual facts remain in cash; a bad association never erases a receipt.
    assert ledger.sequence('sample')==3
    assert ledger.snapshot('sample','2026-10-09T20:01:00Z')['settled_cash']=='1100'


def test_date_alone_does_not_clear_obligation_and_expiry_fact_does(ledger):
    from datetime import timedelta
    from personal_quant.common import utc
    c=contract(ledger);identity=plan(ledger,c,1)
    ledger.import_events('sample',[event('deposit','DEPOSIT',amount=1000),
        option_event('open','OPTION_TRADE',c,action='OPEN',trade_side='BUY',price=2,plan_id=identity)])
    after=(utc(c.exercise_cutoff_at)+timedelta(seconds=1)).isoformat()
    assert review(ledger,identity,after)['lifecycle']['status']=='OPEN'
    expiry=option_event('expiry','OPTION_EXPIRY',c,position_side='LONG',plan_id=identity)
    expiry.update(effective_at=c.exercise_cutoff_at,settlement_at=c.exercise_cutoff_at)
    ledger.import_events('sample',[expiry]);ledger.import_events('sample',[expiry])
    result=review(ledger,identity,after)
    assert result['status']=='FILLED' and result['lifecycle']['status']=='CLOSED'
    assert result['progress']['fact_anomalies']==[]
    assert ledger.snapshot('sample',after)['equity']=='800'
    assert ledger.sequence('sample')==3
    ledger.import_events('sample',[event('undo-expiry','REVERSAL',reference_event_id='expiry',effective_at=expiry['effective_at'])])
    assert review(ledger,identity,after)['lifecycle']['status']=='OPEN'
