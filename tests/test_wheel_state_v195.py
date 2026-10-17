from test_options_ledger_v19 import contract,option_event
from conftest import event
from personal_quant.options.wheel import decision

PARAMS={'underlying':'SPY','packages':1,'cash_buffer':10}


def test_wheel_uses_assignment_and_settlement_facts_before_changing_stage(ledger):
    c=contract(ledger,'PUT',95)
    ledger.import_events('sample',[event('fund','DEPOSIT',amount=10000)])
    cash=decision(ledger,'sample','2026-10-09T19:44:00Z',PARAMS)
    assert cash['phase']=='CASH' and cash['template_id']=='cash_secured_put' and not cash['executable']
    ledger.import_events('sample',[option_event('put','OPTION_TRADE',c,action='OPEN',trade_side='SELL',price=2)])
    assert decision(ledger,'sample','2026-10-09T20:01:00Z',PARAMS)['phase']=='PUT_OPEN'
    assignment={**option_event('assigned','OPTION_ASSIGNMENT',c,position_side='SHORT'),
                'effective_at':'2026-10-12T19:45:00Z','settlement_at':'2026-10-13T20:00:00Z'}
    ledger.import_events('sample',[assignment])
    assert decision(ledger,'sample','2026-10-12T20:01:00Z',PARAMS)['phase']=='SETTLEMENT_PENDING'
    stock=decision(ledger,'sample','2026-10-13T20:01:00Z',PARAMS)
    assert stock['phase']=='STOCK' and stock['template_id']=='covered_call'
    assert decision(ledger,'sample','2026-10-13T20:01:00Z',PARAMS)==stock
    assert ledger.sequence('sample')==3


def test_wheel_call_assignment_must_settle_before_cash_put_is_eligible(ledger):
    c=contract(ledger,'CALL',105)
    ledger.import_events('sample',[event('fund','DEPOSIT',amount=10000),
        event('stock','BUY',symbol='SPY',quantity=100,price=100,settlement_at='2024-07-02T20:00:00Z'),
        option_event('call','OPTION_TRADE',c,action='OPEN',trade_side='SELL',price=2)])
    assert decision(ledger,'sample','2026-10-10T00:00:00Z',PARAMS)['phase']=='CALL_OPEN'
    ledger.import_events('sample',[{**option_event('assigned','OPTION_ASSIGNMENT',c,position_side='SHORT'),
        'effective_at':'2026-10-12T19:45:00Z','settlement_at':'2026-10-13T20:00:00Z'}])
    assert decision(ledger,'sample','2026-10-12T20:00:00Z',PARAMS)['phase']=='SETTLEMENT_PENDING'
    cash=decision(ledger,'sample','2026-10-13T20:01:00Z',PARAMS)
    assert cash['phase']=='CASH' and cash['template_id']=='cash_secured_put'


def test_wheel_empty_cash_and_fractional_stock_never_get_trade_eligibility(ledger):
    assert decision(ledger,'sample','2026-10-10T00:00:00Z',PARAMS)['status']=='BLOCKED'
    ledger.import_events('sample',[event('fund','DEPOSIT',amount=10000),
        event('fraction','BUY',symbol='SPY',quantity=99.5,price=100,settlement_at='2024-07-02T20:00:00Z')])
    result=decision(ledger,'sample','2026-10-10T00:00:00Z',PARAMS)
    assert result['status']=='BLOCKED' and 'NONSTANDARD_WHEEL_SHARES' in result['checks']


def test_partial_put_assignment_does_not_start_call_with_remaining_put_obligation(ledger):
    c=contract(ledger,'PUT',95)
    ledger.import_events('sample',[event('fund','DEPOSIT',amount=20000),
        {**option_event('put','OPTION_TRADE',c,action='OPEN',trade_side='SELL',price=2),'quantity':2}])
    assigned={**option_event('one-assigned','OPTION_ASSIGNMENT',c,position_side='SHORT'),
        'effective_at':'2026-10-12T19:45:00Z','settlement_at':'2026-10-13T20:00:00Z'}
    ledger.import_events('sample',[assigned])
    ledger.import_events('sample',[assigned])
    midway=decision(ledger,'sample','2026-10-13T20:01:00Z',{**PARAMS,'packages':2})
    assert midway['phase']=='PUT_OPEN' and midway['template_id'] is None
    assert midway['executable'] is False and ledger.sequence('sample')==3
    ledger.import_events('sample',[{**option_event('other-expired','OPTION_EXPIRY',c,position_side='SHORT'),
        'effective_at':c.exercise_cutoff_at,'settlement_at':c.exercise_cutoff_at}])
    blocked=decision(ledger,'sample',c.exercise_cutoff_at,{**PARAMS,'packages':2})
    assert blocked['phase']=='STOCK' and blocked['status']=='BLOCKED'
    assert 'INSUFFICIENT_COVERED_SHARES' in blocked['checks']
    # Explicitly reducing the next candidate to one package uses actual shares;
    # the state tool never buys another 100 shares to satisfy the old target.
    one=decision(ledger,'sample',c.exercise_cutoff_at,PARAMS)
    assert one['template_id']=='covered_call' and not one['executable']
    assert ledger.snapshot('sample',c.exercise_cutoff_at)['positions']=={'SPY':'100'}


def test_wheel_unknown_contract_action_stays_blocked_with_original_receipt(ledger):
    from personal_quant.options.ledger import import_facts
    c=contract(ledger,'PUT',95)
    ledger.import_events('sample',[event('fund','DEPOSIT',amount=10000)])
    row=option_event('adjustment','UNKNOWN_OPTION_ACTION',c,position_side='SHORT')
    import_facts(ledger,'sample',[row],expected_sequence=1)
    import_facts(ledger,'sample',[row],expected_sequence=1)
    state=decision(ledger,'sample','2026-10-10T00:00:00Z',PARAMS)
    assert state['status']=='BLOCKED' and state['template_id'] is None
    assert state['checks'] and ledger.sequence('sample')==1
    assert ledger.connection.execute('SELECT count(*) FROM pending_option_events').fetchone()[0]==1
