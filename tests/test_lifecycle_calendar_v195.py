from test_options_ledger_v19 import contract,option_event
from conftest import event
from personal_quant.workspace.lifecycle_calendar import calendar_view


def test_calendar_is_read_only_does_not_include_future_fills_or_invent_expiry(ledger):
    c=contract(ledger,'CALL',100)
    ledger.import_events('sample',[event('capital','DEPOSIT',amount=10000),
        {**option_event('open','OPTION_TRADE',c,action='OPEN',trade_side='BUY',price=2),'settlement_at':'2026-10-12T20:00:00Z'},
        {**option_event('close','OPTION_TRADE',c,action='CLOSE',trade_side='SELL',price=1),
         'effective_at':'2026-10-12T19:45:00Z','settlement_at':'2026-10-13T20:00:00Z'}])
    changes=ledger.connection.total_changes
    early=calendar_view(ledger,'sample','2026-10-10T21:00:00Z')
    assert early['read_only'] and early['contracts'][0]['recorded_contracts']=='1'
    assert [e['event_id'] for e in early['pending_settlements']]==['open']
    late=calendar_view(ledger,'sample','2026-10-13T21:00:00Z')
    assert late['contracts'][0]['status']=='CLOSED_RECORDED' and not late['pending_settlements']
    assert ledger.connection.total_changes==changes and ledger.sequence('sample')==3


def test_calendar_does_not_retire_a_position_without_a_receipt(ledger):
    c=contract(ledger,'CALL',100)
    ledger.import_events('sample',[event('capital','DEPOSIT',amount=10000),
        option_event('open','OPTION_TRADE',c,action='OPEN',trade_side='BUY',price=2)])
    result=calendar_view(ledger,'sample','2027-01-01T21:00:00Z')
    assert result['contracts'][0]['status']=='PAST_CUTOFF_REQUIRE_RECEIPT'
    assert result['contracts'][0]['recorded_contracts']=='1' and ledger.sequence('sample')==2


def test_contract_revision_history_does_not_duplicate_current_quantity(ledger):
    from personal_quant.options.ledger import register_contract
    c=contract(ledger,'CALL',100)
    newer=register_contract(ledger,{**c.content(),'revision':'revision-2'})
    ledger.import_events('sample',[event('capital','DEPOSIT',amount=10000),
        option_event('open','OPTION_TRADE',c,action='OPEN',trade_side='BUY',price=2),
        {**option_event('close','OPTION_TRADE',c,action='CLOSE',trade_side='SELL',price=2),'effective_at':'2026-10-12T19:45:00Z','settlement_at':'2026-10-13T20:00:00Z'},
        {**option_event('new','OPTION_TRADE',newer,action='OPEN',trade_side='BUY',price=3),'effective_at':'2026-10-13T19:45:00Z','settlement_at':'2026-10-14T20:00:00Z'}])
    result=calendar_view(ledger,'sample','2026-10-14T21:00:00Z')
    quantities={row['contract_version']:row['recorded_contracts'] for row in result['contracts']}
    assert quantities=={c.version_hash:'0',newer.version_hash:'1'}
