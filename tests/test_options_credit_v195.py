from native_tools import native_engine_root,native_dotnet
from decimal import Decimal
from dataclasses import replace
import pandas as pd
import pytest
from test_options_selection_v19 import chain,request
from test_options_monthly_replay_v19 import monthly_signals,ROOT
from test_options_plans_v19 import RISK
from test_options_ledger_v19 import contract,option_event
from conftest import event
from personal_quant.common import QuantError
from personal_quant.options.catalog import A8,template
from personal_quant.options.data import OptionDataStore
from personal_quant.options.selection import select
from personal_quant.options.plans import sizing,unfilled_resources
from personal_quant.options.payoff import analyze
from personal_quant.options.ledger import register_contract
from personal_quant.options.monthly_replay import monthly_replay


def selection(tmp_path,name,*,width=5,credit=True):
    contracts,records,metadata=chain()
    for row in records:
        row.update(bid=2 if credit and row['contract_id'] in {'PUT95','CALL105'} else 1)
        row['ask']=row['bid']+.1
    store=OptionDataStore(tmp_path)
    identity=store.save(contracts,pd.DataFrame(records),metadata)['snapshot_id']
    rule=request(name);rule['parameters']={**rule['parameters'],'minimum_spread_width':width}
    return select(store,identity,rule)


@pytest.mark.parametrize('name,ids,required',[('bull_put_credit_spread',['PUT90','PUT95'],9624),('bear_call_credit_spread',['CALL110','CALL105'],11124)])
def test_credit_selection_budgets_and_unfilled_resources_are_conservative(tmp_path,name,ids,required):
    selected=selection(tmp_path,name)
    assert selected['status']=='SELECTED_FOR_RESEARCH' and name not in A8 and not selected['executable']
    assert [l['contract']['contract_id'] for l in selected['legs']]==ids
    snapshot={'positions':{},'reserved_positions':{},'available_cash':20000,'equity':20000,'anomalies':[]}
    sized=sizing(selected,snapshot,1,RISK)
    assert sized['sizing_status']=='PASSED' and Decimal(sized['net_premium_debit'])==-90
    assert Decimal(sized['required_cash'])==required
    assert Decimal(sized['expiry_payoff']['maximum_loss'])==414
    body={'selection':selected,'sizing':sized,'request':{'risk':RISK}}
    assert Decimal(unfilled_resources(body,{})['reserved_cash'])==required
    assert Decimal(unfilled_resources(body,{ids[0]:1})['reserved_cash'])==required-112
    assert unfilled_resources(body,{ids[0]:1,ids[1]:1})['reserved_cash']=='0'
    assert 'INSUFFICIENT_SETTLED_CASH' in sizing(selected,{**snapshot,'available_cash':required-1},1,RISK)['checks']


@pytest.mark.parametrize('name',['bull_put_credit_spread','bear_call_credit_spread'])
def test_credit_rejects_missing_width_unavailable_protection_and_non_credit(tmp_path,name):
    assert selection(tmp_path/'wide',name,width=10)['status']=='BLOCKED'
    assert selection(tmp_path/'debit',name,credit=False)['status']=='BLOCKED'
    with pytest.raises(QuantError):selection(tmp_path/'zero',name,width=0)
    payoff=analyze(template(name,premium=2,second_premium=1,fee=2),prices=[80,100,120])
    assert Decimal(payoff['maximum_loss'])==404 and Decimal(payoff['maximum_profit'])==96


def test_bear_call_collateral_and_assignment_keep_intermediate_exposure_visible(ledger):
    long=contract(ledger,'CALL',110)
    body=long.content();body.update(contract_id='CALL105',strike='105',exercise_cash='10500')
    short=register_contract(ledger,body)
    ledger.import_events('sample',[event('fund','DEPOSIT',amount=20000),
        option_event('long','OPTION_TRADE',long,action='OPEN',trade_side='BUY',price=1,fee=2),
        option_event('short','OPTION_TRADE',short,action='OPEN',trade_side='SELL',price=2,fee=2)])
    state=ledger.snapshot('sample','2026-10-10T00:00:00Z',{long.contract_id:1,short.contract_id:2})
    assert Decimal(state['equity'])==19996 and Decimal(state['option_cash_collateral'])==11000
    assert not state['anomalies'] and state['option_covered_shares']=={}
    ledger.import_events('sample',[option_event('assigned','OPTION_ASSIGNMENT',short,position_side='SHORT')])
    mid=ledger.snapshot('sample','2026-10-10T00:00:00Z',{'SPY':120,long.contract_id:10})
    assert mid['positions']=={'SPY':'-100'} and mid['anomalies']
    ledger.import_events('sample',[option_event('exercised','OPTION_EXERCISE',long,position_side='LONG')])
    final=ledger.snapshot('sample','2026-10-10T00:00:00Z',{})
    assert final['positions']=={} and final['option_positions']=={}
    assert Decimal(final['equity'])==19596 and Decimal(final['investment_pnl'])==-404


@pytest.mark.parametrize('name',['bull_put_credit_spread','bear_call_credit_spread'])
def test_credit_native_two_months_matches_costs_and_one_cash_ledger(tmp_path,name):
    signals=monthly_signals(tmp_path,name)
    proof=monthly_replay(native_engine_root(),native_dotnet(),tmp_path/'engine',signals,initial_cash=100000,fee_per_contract=2)
    assert float(proof['actual_equity'])==99944 and float(proof['ledger_bridge']['equity'])==99944
    assert proof['ledger_bridge']['positions']=={} and proof['ledger_bridge']['option_positions']=={}
    assert proof['duplicate_events_added']==0


def test_pending_bear_call_uses_funded_protection_cash_without_inventing_stock_cover(tmp_path):
    from personal_quant.options.lifecycle import pending_resources
    selected=selection(tmp_path,'bear_call_credit_spread')
    long,short=[leg['contract']['contract_id'] for leg in selected['legs']]
    body={'selection':selected,'manual_execution':{'pending':True,'filled_basis':{long:'1',short:'0'},
        'orders':[{'contract_id':short,'side':'SELL','contracts':'1','limit_price':'2','fee_per_contract':'2'}]}}
    cash,shares,remaining=pending_resources(body,{long:Decimal(1),short:Decimal(0)})
    assert cash==11002 and shares=={} and remaining=={short:'1'}
    cash,shares,remaining=pending_resources(body,{long:Decimal(1),short:Decimal(1)})
    assert cash==0 and shares=={} and remaining=={short:'0'}
