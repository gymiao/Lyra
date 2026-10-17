from decimal import Decimal as D
import pandas as pd
import pytest
from test_options_selection_v19 import chain, request
from test_options_plans_v19 import RISK
from personal_quant.options.data import OptionDataStore
from personal_quant.options.selection import select
from personal_quant.options.plans import sizing, unfilled_resources
from personal_quant.options.payoff import analyze
from personal_quant.options.catalog import template


def selected(tmp_path,name):
    contracts,records,metadata=chain()
    for r in records:
        strike=int(r['contract_id'].replace('PUT','').replace('CALL',''))
        r['bid']=dict(zip([90,95,100,105,110],[.5,1,2,6,11] if 'PUT' in r['contract_id'] else [11,6,2,1,.5]))[strike]
        r['ask']=r['bid']+.05
    store=OptionDataStore(tmp_path)
    snapshot=store.save(contracts,pd.DataFrame(records),metadata)['snapshot_id']
    rule=request(name);rule['parameters']={**rule['parameters'],'minimum_spread_width':5}
    return store,snapshot,rule,select(store,snapshot,rule)


@pytest.mark.parametrize('name,ids,credit,required,loss',[('iron_condor',['PUT90','CALL110','PUT95','CALL105'],90,20628,418),('iron_butterfly',['PUT95','CALL105','PUT100','CALL100'],190,20728,318)])
def test_four_leg_selection_funded_cash_and_terminal_loss(tmp_path,name,ids,credit,required,loss):
    _,_,_,result=selected(tmp_path,name)
    assert result['status']=='SELECTED_FOR_RESEARCH'
    assert [x['contract']['contract_id'] for x in result['legs']]==ids
    snapshot={'positions':{},'reserved_positions':{},'available_cash':100000,'equity':100000,'anomalies':[]}
    sized=sizing(result,snapshot,1,RISK)
    assert sized['checks']==[]
    assert D(sized['net_premium_debit'])==-credit
    assert D(sized['expiry_payoff']['maximum_loss'])==loss
    assert D(sized['required_cash'])==required
    body={'selection':result,'sizing':sized,'request':{'risk':RISK}}
    assert D(unfilled_resources(body,{})['reserved_cash'])==required
    assert D(unfilled_resources(body,{ids[0]:1,ids[1]:1})['reserved_cash'])==20514
    assert unfilled_resources(body,{x:1 for x in ids})['reserved_cash']=='0'
    assert 'INSUFFICIENT_SETTLED_CASH' in sizing(result,{**snapshot,'available_cash':required-1},1,RISK)['checks']


@pytest.mark.parametrize('name',['iron_condor','iron_butterfly'])
def test_four_leg_missing_wing_blocks_and_payoff_is_bounded(tmp_path,name):
    store,snapshot,rule,_=selected(tmp_path,name)
    rule['parameters']['minimum_spread_width']=30
    assert select(store,snapshot,rule)['status']=='BLOCKED'
    payoff=analyze(template(name,premium=2,second_premium=1,fee=2),prices=[0,100,200])
    assert not payoff['loss_unbounded'] and D(payoff['maximum_profit'])==192
    assert D(payoff['maximum_loss'])==308


@pytest.mark.parametrize('name',['iron_condor','iron_butterfly'])
def test_missing_all_call_protection_candidates_blocks_whole_structure(tmp_path,name):
    store,identity,rule,result=selected(tmp_path,name)
    contracts,records,metadata,_=store.load(identity)
    long=next(l for l in result['legs'] if l['quantity_per_package']>0 and l['contract']['right']=='CALL')
    strike=D(long['contract']['strike'])
    for row in records:
        c=contracts[row['contract_id']]
        if c.right=='CALL' and c.strike>=strike:row['ask_size']='0'
    other=store.save(list(contracts.values()),pd.DataFrame(records),metadata)['snapshot_id']
    assert select(store,other,rule)['status']=='BLOCKED'
