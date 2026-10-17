import pytest
from personal_quant.common import QuantError
from personal_quant.options.activation import activate
from personal_quant.options.exit_tasks import pending_exits
from personal_quant.workspace.option_policy import refresh_reference
from personal_quant.workspace.option_exit import freeze,check_fill,record
from test_options_activation_v19 import setup
from test_stock_preparation_workspace_v195 import covered_evidence

DAY='2024-11-04';CLOCK='2024-11-04T20:40:00Z';CLOSE='2024-11-04T21:00:00Z'


def opening(ledger,tmp_path,evidence,template,packages,shares):
    store,body,activation=setup(ledger,tmp_path,evidence,cash=100000,packages=packages,template=template,shares=shares)
    assert activate(ledger,store,activation)['status']=='ACTIVATED'
    for i,leg in enumerate(body['selection']['legs']):
        ledger.import_events('sample',[dict(event_id='open-'+str(i),kind='OPTION_TRADE',action='OPEN',
            trade_side='BUY' if leg['quantity_per_package']>0 else 'SELL',quantity=packages,price=leg['reference_price'],fee=2*packages,
            contract_version=leg['contract_version'],plan_id=body['plan_id'],source='explicit_test_statement',evidence_type='test',
            effective_at='2024-11-01T20:00:00Z',settlement_at=CLOSE)])
    path={'stocks':{'SPY':{DAY:'100'}},'options':{leg['contract']['contract_id']:{DAY:{'bid':'1','ask':'1.1'}} for leg in body['selection']['legs']}}
    from personal_quant.common import utc
    signal=activation['monthly_signal']
    quote,marks=refresh_reference(ledger,store,signal,path,'sample',utc(CLOCK))
    return store,body,signal,quote,marks


def closing(ledger,body,leg,identity):
    row=dict(event_id=identity,kind='OPTION_TRADE',action='CLOSE',trade_side='BUY' if leg['quantity_per_package']<0 else 'SELL',
        quantity=1,price='1.1' if leg['quantity_per_package']<0 else '1',fee=2,contract_version=leg['contract_version'],
        plan_id=body['plan_id'],source='explicit_test_statement',evidence_type='test',effective_at=CLOSE,settlement_at='2024-11-05T21:00:00Z')
    return row,ledger.normalize_event(row,'sample')


def test_partial_exit_keeps_frozen_task_and_cover_until_both_receipts_arrive(ledger,tmp_path,covered_evidence):
    from personal_quant.common import utc
    store,body,signal,quote,marks=opening(ledger,tmp_path,covered_evidence,'covered_call',2,200)
    leg=body['selection']['legs'][0];row,event=closing(ledger,body,leg,'close-one')
    proposal=freeze(ledger,store,signal,event,{'risk':body['request']['risk'],'reconciliation_max_days':1},quote,utc(CLOCK))
    key,progress=check_fill(ledger,proposal,event,'independent-unit-receipt-one')
    ledger.import_events('sample',[row]);record(ledger,proposal,event,key,progress,marks)
    state=ledger.snapshot('sample',CLOSE,marks)
    assert state['option_covered_shares']=={'SPY':'100'}
    assert pending_exits(ledger,'sample',CLOSE)==[proposal['proposal']['exit_id']]
    assert not ledger.connection.execute("SELECT 1 FROM tasks WHERE task_id LIKE 'option-exit-simulation:%'").fetchone()
    row2,event2=closing(ledger,body,leg,'close-two')
    key,progress=check_fill(ledger,proposal,event2,'independent-unit-receipt-two')
    ledger.import_events('sample',[row2]);record(ledger,proposal,event2,key,progress,marks)
    assert pending_exits(ledger,'sample',CLOSE)==[]
    state=ledger.snapshot('sample','2024-11-06T21:00:00Z',marks)
    assert state['option_positions']=={} and float(state['equity'])==99972
    assert ledger.import_events('sample',[row2])['duplicates']==1 and ledger.sequence('sample')==5
    import json
    audit=json.loads(ledger.connection.execute("SELECT details FROM tasks WHERE task_id LIKE 'option-exit-simulation:%'").fetchone()[0])
    assert audit['account']['pending_option_exits']==[]


def test_protection_cannot_close_before_obligation_receipt(ledger,tmp_path,covered_evidence):
    from personal_quant.common import utc
    store,body,signal,quote,marks=opening(ledger,tmp_path,covered_evidence,'collar',1,100)
    leg=next(l for l in body['selection']['legs'] if l['quantity_per_package']>0)
    row,event=closing(ledger,body,leg,'put-first')
    proposal=freeze(ledger,store,signal,event,{'risk':body['request']['risk'],'reconciliation_max_days':1},quote,utc(CLOCK))
    before=ledger.sequence('sample')
    with pytest.raises(QuantError) as caught:check_fill(ledger,proposal,event,'not-imported-unit-receipt')
    assert caught.value.code=='OPTION_EXIT_DEPENDENCY' and ledger.sequence('sample')==before


def test_cancelled_frozen_exit_cannot_be_resumed_by_prefix_import(ledger,tmp_path,covered_evidence):
    from personal_quant.common import utc
    from personal_quant.options.exit_tasks import cancel_exit
    store,body,signal,quote,marks=opening(ledger,tmp_path,covered_evidence,'covered_call',1,100)
    row,event=closing(ledger,body,body['selection']['legs'][0],'cancelled-fill')
    proposal=freeze(ledger,store,signal,event,{'risk':body['request']['risk'],'reconciliation_max_days':1},quote,utc(CLOCK))
    cancel_exit(ledger,{'exit_id':proposal['proposal']['exit_id'],'as_of':'2024-11-04T20:50:00Z',
        'expected_sequence':ledger.sequence('sample'),'reason':'显式测试取消剩余意图'})
    before=ledger.sequence('sample')
    with pytest.raises(QuantError) as caught:check_fill(ledger,proposal,event,'not-consumed')
    assert caught.value.code=='OPTION_EXIT_CANCELLED' and ledger.sequence('sample')==before
