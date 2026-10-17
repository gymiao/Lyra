import pandas as pd
from personal_quant.common import decimal as D
from test_options_selection_v19 import chain,request
from test_options_ledger_v19 import contract
from conftest import event
from personal_quant.options.data import OptionDataStore
from personal_quant.options.selection import select
from personal_quant.options.plans import draft,sizing,unfilled_resources

RISK={'premium_budget':1000,'maximum_loss_budget':12000,'maximum_notional':12000,
      'maximum_contracts':1,'fee_per_contract':2,'adverse_slippage_fraction':0,
      'cash_buffer':10,'early_assignment_cash_reserve':0}


def test_draft_is_idempotent_and_cannot_silently_reserve_or_execute(ledger,tmp_path):
    contract(ledger)
    ledger.import_events('sample',[event('deposit','DEPOSIT',amount=10500),
        event('stock','BUY',symbol='SPY',quantity=100,price=100,settlement_at='2024-07-02T20:00:00Z')])
    contracts,records,metadata=chain();store=OptionDataStore(tmp_path/'chains')
    identity=store.save(contracts,pd.DataFrame(records),metadata)['snapshot_id']
    body={'selection':request('covered_call'),'packages':1,'risk':RISK,'revision':1}
    first=draft(ledger,store,identity,'sample',body);second=draft(ledger,store,identity,'sample',body)
    assert first['plan_id']==second['plan_id'] and first['sizing']['sizing_status']=='PASSED'
    assert first['sizing']['net_premium_debit']=='-100' and first['sizing']['estimated_fees']=='2'
    assert first['sizing']['required_cash']=='12'
    assert not first['executable'] and first['status']=='DRAFT'
    assert first['checks']==['LYRAX_ENGINE_LIFECYCLE_NOT_VALIDATED']
    assert ledger.connection.execute('SELECT count(*) FROM option_plans').fetchone()[0]==1
    state=ledger.snapshot('sample','2026-10-09T20:00:00Z',{'SPY':100})
    assert state['settled_cash']=='500' and state['reserved_cash']=='0' and state['equity']=='10500'
    from personal_quant.options.lifecycle import review
    viewed=review(ledger,first['plan_id'],'2026-10-09T20:00:00Z')
    assert viewed['reservation_preview']['reserved_cash']=='12' and viewed['reservation_preview']['applied'] is False
    assert viewed['reservation_preview']['reserved_positions']=={'SPY':'100'}
    assert ledger.snapshot('sample','2026-10-09T20:00:00Z',{'SPY':100})['reserved_cash']=='0'
    revised=draft(ledger,store,identity,'sample',{**body,'revision':2})
    assert revised['plan_id']!=first['plan_id']
    assert draft(ledger,store,identity,'sample',body)['status']=='SUPERSEDED'


def test_stock_already_reserved_and_full_put_cash_cannot_be_reused(tmp_path):
    contracts,records,metadata=chain();store=OptionDataStore(tmp_path/'chains')
    identity=store.save(contracts,pd.DataFrame(records),metadata)['snapshot_id']
    snapshot={'positions':{'SPY':'100'},'reserved_positions':{'SPY':'100'},'available_cash':'200',
              'equity':'10200','anomalies':[]}
    call=sizing(select(store,identity,request('covered_call')),snapshot,1,RISK)
    assert 'UNDERLYING_ALREADY_RESERVED_OR_INSUFFICIENT:SPY' in call['checks']
    put=sizing(select(store,identity,request('cash_secured_put')),snapshot,1,RISK)
    assert put['put_cash_collateral']=='9500' and put['required_cash']=='9512'
    assert 'INSUFFICIENT_SETTLED_CASH' in put['checks']


def test_unfilled_budget_moves_put_obligation_once_without_using_future_premium(tmp_path):
    contracts,records,metadata=chain();store=OptionDataStore(tmp_path/'chains')
    identity=store.save(contracts,pd.DataFrame(records),metadata)['snapshot_id']
    selected=select(store,identity,request('cash_secured_put'))
    snapshot={'positions':{},'reserved_positions':{},'available_cash':30000,'equity':30000,'anomalies':[]}
    risk={**RISK,'maximum_contracts':2,'maximum_notional':30000,'maximum_loss_budget':30000}
    body={'selection':selected,'sizing':sizing(selected,snapshot,2,risk),'request':{'risk':risk}}
    symbol=selected['legs'][0]['contract']['contract_id']
    assert unfilled_resources(body,{})['reserved_cash']=='19014'
    assert unfilled_resources(body,{symbol:1})['reserved_cash']=='9512'
    assert unfilled_resources(body,{symbol:2})['reserved_cash']=='0'


def test_unfilled_collar_stock_cover_and_call_spread_exercise_cash_do_not_duplicate(tmp_path):
    contracts,records,metadata=chain();store=OptionDataStore(tmp_path/'chains')
    identity=store.save(contracts,pd.DataFrame(records),metadata)['snapshot_id']
    snapshot={'positions':{'SPY':100},'reserved_positions':{},'available_cash':20000,'equity':30000,'anomalies':[]}
    def body(template):
        selected=select(store,identity,request(template))
        return {'selection':selected,'sizing':sizing(selected,snapshot,1,RISK),'request':{'risk':RISK}}
    collar=body('collar');short=next(l['contract_id'] for l in collar['sizing']['lines'] if l['side']=='SELL')
    assert unfilled_resources(collar,{})['reserved_positions']=={'SPY':'100'}
    assert unfilled_resources(collar,{short:1})['reserved_positions']=={} # actual call owns the cover
    spread=body('bull_call_debit_spread');long=next(l['contract_id'] for l in spread['sizing']['lines'] if l['side']=='BUY')
    short=next(l['contract_id'] for l in spread['sizing']['lines'] if l['side']=='SELL')
    assert D(unfilled_resources(spread,{})['reserved_cash'])==10224
    assert D(unfilled_resources(spread,{long:1})['reserved_cash'])==10012
    assert unfilled_resources(spread,{long:1,short:1})['reserved_cash']=='0'
