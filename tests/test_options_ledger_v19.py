import pytest
from personal_quant.common import QuantError
from personal_quant.portfolio.schema import apply_workbench_schema,apply_v18_schema,apply_v19_schema
from personal_quant.options.ledger import register_contract
from test_options_data_v19 import sample
from conftest import event


def contract(ledger,right='PUT',strike=100):
    with ledger.transaction():
        apply_workbench_schema(ledger.connection);apply_v18_schema(ledger.connection);apply_v19_schema(ledger.connection)
    body=sample()[0].content();body.update(right=right,strike=str(strike),exercise_cash=str(strike*100))
    return register_contract(ledger,body)


def option_event(identity,kind,c,**values):
    return event(identity,kind,contract_version=c.version_hash,quantity=1,
                 effective_at='2026-10-09T19:45:00Z',settlement_at='2026-10-09T20:00:00Z',**values)


def test_unsupported_receipt_kept_once_and_blocks_instead_of_disappearing(ledger):
    from personal_quant.options.ledger import import_facts
    c=contract(ledger)
    row=option_event('adjustment','UNKNOWN_OPTION_ACTION',c,position_side='LONG')
    first=import_facts(ledger,'sample',[row],expected_sequence=0)
    second=import_facts(ledger,'sample',[row],expected_sequence=0)
    assert first['pending_events']==second['pending_events']==['adjustment']
    assert ledger.connection.execute('SELECT count(*) FROM pending_option_events').fetchone()[0]==1
    state=ledger.snapshot('sample','2026-10-10T00:00:00Z')
    assert state['equity']=='0' and any('未核实' in text for text in state['anomalies'])


def test_short_put_premium_is_liability_and_assignment_moves_cash_stock_once(ledger):
    c=contract(ledger)
    rows=[event('deposit','DEPOSIT',amount=10000),option_event('put','OPTION_TRADE',c,action='OPEN',trade_side='SELL',price=2)]
    assert ledger.import_events('sample',rows)['added']==2
    snapshot=ledger.snapshot('sample','2026-10-10T00:00:00Z',{c.contract_id:2})
    assert snapshot['settled_cash']=='10200' and snapshot['option_market_value']=='-200'
    assert snapshot['equity']=='10000' and snapshot['investment_pnl']=='0'
    assert snapshot['available_cash']=='200' and snapshot['reserved_cash']=='10000'
    assigned=option_event('assigned','OPTION_ASSIGNMENT',c,position_side='SHORT')
    ledger.import_events('sample',[assigned]);ledger.import_events('sample',[assigned])
    snapshot=ledger.snapshot('sample','2026-10-10T00:00:00Z',{'SPY':90})
    assert snapshot['settled_cash']=='200' and snapshot['positions']=={'SPY':'100'}
    assert snapshot['equity']=='9200' and snapshot['investment_pnl']=='-800'
    assert snapshot['option_positions']=={} and snapshot['reserved_cash']=='0'


def test_protective_put_exercise_and_covered_call_assignment_hand_computed(ledger):
    c=contract(ledger,'PUT',95)
    ledger.import_events('sample',[event('deposit','DEPOSIT',amount=10200),
        event('stock','BUY',symbol='SPY',quantity=100,price=100,settlement_at='2024-07-02T20:00:00Z'),
        option_event('put','OPTION_TRADE',c,action='OPEN',trade_side='BUY',price=2)])
    ledger.import_events('sample',[option_event('exercise','OPTION_EXERCISE',c,position_side='LONG')])
    state=ledger.snapshot('sample','2026-10-10T00:00:00Z')
    assert state['settled_cash']=='9500' and state['equity']=='9500' and state['investment_pnl']=='-700'


def test_covered_call_no_extra_intrinsic_cash_deduction(ledger):
    c=contract(ledger,'CALL',105)
    ledger.import_events('sample',[event('deposit','DEPOSIT',amount=10000),
        event('stock','BUY',symbol='SPY',quantity=100,price=100,settlement_at='2024-07-02T20:00:00Z'),
        option_event('call','OPTION_TRADE',c,action='OPEN',trade_side='SELL',price=2)])
    open_state=ledger.snapshot('sample','2026-10-10T00:00:00Z',{'SPY':100,c.contract_id:2})
    assert open_state['equity']=='10000' and open_state['option_covered_shares']=={'SPY':'100'}
    ledger.import_events('sample',[option_event('assigned','OPTION_ASSIGNMENT',c,position_side='SHORT')])
    state=ledger.snapshot('sample','2026-10-10T00:00:00Z')
    assert state['equity']=='10700' and state['investment_pnl']=='700'


def test_fee_flow_reversal_and_insufficient_cover_remain_visible(ledger):
    c=contract(ledger,'CALL',105)
    ledger.import_events('sample',[event('deposit','DEPOSIT',amount=10000),
        option_event('call','OPTION_TRADE',c,action='OPEN',trade_side='SELL',price=2,fee=3)])
    state=ledger.snapshot('sample','2026-10-10T00:00:00Z',{c.contract_id:2})
    assert state['equity']=='9997' and state['anomalies']
    ledger.import_events('sample',[event('bonus','DEPOSIT',amount=1000,effective_at='2026-10-09T20:00:00Z')])
    state=ledger.snapshot('sample','2026-10-10T00:00:00Z',{c.contract_id:2})
    assert state['investment_pnl']=='-3'
    ledger.import_events('sample',[event('reverse','REVERSAL',reference_event_id='call',effective_at='2026-10-09T19:45:00Z')])
    state=ledger.snapshot('sample','2026-10-10T00:00:00Z')
    assert state['equity']=='11000' and state['investment_pnl']=='0'


def test_physical_contract_cannot_import_cash_settlement_or_fractional_contracts(ledger):
    c=contract(ledger)
    with pytest.raises(QuantError):ledger.import_events('sample',[option_event('bad','OPTION_CASH_SETTLEMENT',c,position_side='SHORT',amount=1000)])
    row=option_event('fraction','OPTION_TRADE',c,action='OPEN',trade_side='SELL',price=2);row['quantity']=.5
    with pytest.raises(QuantError,match='整张'):ledger.import_events('sample',[row])


def test_long_call_protection_used_once_and_exercise_cash_not_subtracted_from_nav(ledger):
    contract(ledger)
    contracts=[]
    for identity,strike in [('long100',100),('short105',105),('short110',110)]:
        body=sample()[0].content();body.update(contract_id=identity,strike=str(strike),exercise_cash=str(strike*100))
        contracts.append(register_contract(ledger,body))
    long,short,extra=contracts
    ledger.import_events('sample',[event('deposit','DEPOSIT',amount=100000),
        option_event('long','OPTION_TRADE',long,action='OPEN',trade_side='BUY',price=2),
        option_event('short','OPTION_TRADE',short,action='OPEN',trade_side='SELL',price=1)])
    state=ledger.snapshot('sample','2026-10-10T00:00:00Z',{'long100':2,'short105':1})
    assert state['equity']=='100000' and state['settled_cash']=='99900'
    assert state['option_cash_collateral']=='10000' and state['available_cash']=='89900'
    assert state['option_covered_shares']=={} and state['anomalies']==[]
    ledger.import_events('sample',[option_event('extra','OPTION_TRADE',extra,action='OPEN',trade_side='SELL',price=1)])
    state=ledger.snapshot('sample','2026-10-10T00:00:00Z',{'long100':2,'short105':1,'short110':1})
    assert state['option_cash_collateral']=='10000'
    assert state['option_covered_shares']=={'SPY':'100'}
    assert any('覆盖证券不足' in item for item in state['anomalies'])


def test_real_workspace_cannot_register_synthetic_contract_terms(tmp_path):
    from personal_quant.portfolio import Ledger
    book=Ledger(tmp_path/'real.sqlite','real')
    with book.transaction():
        apply_workbench_schema(book.connection);apply_v18_schema(book.connection);apply_v19_schema(book.connection)
    with pytest.raises(QuantError,match='实际合约单位凭据'):
        register_contract(book,sample()[0].content())
    book.close()


def test_real_contract_proof_tampering_blocks_import_valuation_and_backup(tmp_path):
    import hashlib
    from personal_quant.portfolio import Ledger
    from personal_quant.portfolio.backup import _validate_references
    book=Ledger(tmp_path/'real.sqlite','real');book.account('sample')
    with book.transaction():
        apply_workbench_schema(book.connection);apply_v18_schema(book.connection);apply_v19_schema(book.connection)
    # This exercises the evidence boundary with a local test document, not a broker connection.
    proof=tmp_path/'test-unit-document.txt';proof.write_text('Test document: standard SPY put, 100 shares, strike 100.')
    identity=hashlib.sha256(proof.read_bytes()).hexdigest()
    body=sample()[0].content();body['evidence_hash']=identity
    c=register_contract(book,body,proof)
    row=option_event('put','OPTION_TRADE',c,action='OPEN',trade_side='BUY',price=2)
    row['evidence_type']='actual'
    book.import_events('sample',[row])
    assert book.snapshot('sample','2026-10-10T00:00:00Z',{c.contract_id:2})['equity']=='0'
    archived=tmp_path/'options/contract-evidence'/identity
    archived.write_text('Changed document')
    state=book.snapshot('sample','2026-10-10T00:00:00Z',{c.contract_id:2})
    assert state['equity'] is None and state['investment_pnl'] is None
    assert state['unverified_option_units']==[c.contract_id]
    with pytest.raises(QuantError,match='实际合约单位凭据'):
        book.import_events('sample',[dict(row,event_id='another')])
    with pytest.raises(QuantError,match='实际合约单位凭据'):
        _validate_references(tmp_path,book)
    book.close()
