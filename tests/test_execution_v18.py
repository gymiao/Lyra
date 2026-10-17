from dataclasses import replace
from decimal import Decimal
from personal_quant.execution.review import execution_review, review_csv
from personal_quant.execution.plans import PlanService
from test_plans import ready, AS_OF
from conftest import event


def test_partial_fill_price_difference_and_reversal_are_read_only(ledger,market,config):
    service,plan=ready(ledger,market,config)
    line=plan['payload']['sizing']['lines'][0];symbol=line['symbol'];price=Decimal(line['price'])
    ledger.import_events('sample',[event('partial','BUY',symbol=symbol,quantity=2,price=price+1,fee=3,plan_id=plan['plan_id'],effective_at='2024-08-01T20:00:00Z',settlement_at='2024-08-02T20:00:00Z')])
    seq=ledger.sequence('sample');result=execution_review(ledger,config,plan['plan_id'],'2024-08-02T21:00:00Z')
    value=next(l for l in result['lines'] if l['symbol']==symbol)
    assert value['actual_quantity_current_units']=='2'
    assert Decimal(value['relative_reference_cost'])==2
    assert Decimal(value['actual_fill_fees'])==3
    assert 'plan_id' in review_csv(result)
    assert ledger.sequence('sample')==seq
    ledger.import_events('sample',[event('undo','REVERSAL',reference_event_id='partial',effective_at='2024-08-01T20:00:00Z')])
    after=execution_review(ledger,config,plan['plan_id'],'2024-08-03T21:00:00Z')
    assert next(l for l in after['lines'] if l['symbol']==symbol)['actual_quantity_current_units']=='0'


def test_split_changes_reference_and_fill_units_once(ledger,market,config):
    service,plan=ready(ledger,market,config)
    line=plan['payload']['sizing']['lines'][0];symbol=line['symbol'];price=Decimal(line['price'])
    ledger.import_events('sample',[event('partial','BUY',symbol=symbol,quantity=2,price=price+1,fee=3,plan_id=plan['plan_id'],effective_at='2024-08-01T20:00:00Z',settlement_at='2024-08-02T20:00:00Z'),
        event('split','SPLIT',symbol=symbol,ratio=2,effective_at='2024-08-02T13:30:00Z')])
    result=execution_review(ledger,config,plan['plan_id'],'2024-08-02T21:00:00Z')
    value=next(l for l in result['lines'] if l['symbol']==symbol)
    assert value['actual_quantity_current_units']=='4'
    assert Decimal(value['reference_price_current_units'])==price/2
    assert Decimal(value['relative_reference_cost'])==2


def test_sell_reference_difference_is_positive_for_a_lower_sale_price(ledger,market,config):
    from personal_quant.strategies import signal
    from personal_quant.cli import references
    _,frame,meta,calendar=market
    cfg=replace(config,active_strategy='fixed',weights=(0,0,0))
    ledger.import_events('sample',[event('cash','DEPOSIT',amount=10000),event('holding','BUY',symbol='GLD',quantity=10,price=100,settlement_at='2024-07-01T20:00:00Z')])
    ledger.reconcile('sample',{'account_id':'sample','currency':'USD','as_of':AS_OF,'cash_basis':'settled','cash':9000,'positions':{'GLD':10}},references(frame,AS_OF))
    value=signal(frame,calendar,cfg,'2024-07-31','fixed',meta['snapshot_id'])
    plan=PlanService(ledger,cfg).create('sample',value,frame,meta,calendar,AS_OF)
    line=next(l for l in plan['payload']['sizing']['lines'] if l['side']=='SELL');price=Decimal(line['price'])
    ledger.import_events('sample',[event('sale','SELL',symbol='GLD',quantity=2,price=price-1,fee=3,plan_id=plan['plan_id'],effective_at='2024-08-01T20:00:00Z',settlement_at='2024-08-02T20:00:00Z')])
    result=execution_review(ledger,cfg,plan['plan_id'],'2024-08-02T21:00:00Z')
    assert Decimal(result['lines'][0]['relative_reference_cost'])==2
    assert Decimal(result['lines'][0]['actual_fill_fees'])==3
