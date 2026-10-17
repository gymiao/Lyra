from copy import deepcopy
from datetime import timedelta
import pandas as pd
from test_options_data_v19 import sample
from personal_quant.options.contracts import OptionContract
from personal_quant.options.data import OptionDataStore
from personal_quant.options.selection import select


PARAMS={'target_dte':45,'minimum_dte':30,'maximum_dte':80,'put_moneyness':.95,'call_moneyness':1.05,
        'exit_days_before_expiry':7,'max_age_seconds':900,'max_underlying_skew_seconds':60,
        'max_spread_fraction':.25,'max_leg_skew_seconds':10,'max_underlying_price_fraction':.01}


def chain():
    c,r,m=sample();contracts=[];records=[]
    for right,strike in [('CALL',100),('CALL',105),('CALL',110),('PUT',90),('PUT',95),('PUT',100)]:
        body=c.content();body.update(right=right,strike=str(strike),exercise_cash=str(strike*100),contract_id=f'{right}{strike}')
        item=OptionContract.from_dict(body);contracts.append(item)
        row={**r,'contract_id':item.contract_id,'contract_version':item.version_hash}
        if strike!=100:row.update(bid=1,ask=1.1)
        records.append(row)
    return contracts,records,m


def request(identifier):return {'template_id':identifier,'underlying':'SPY','decision_at':'2026-10-09T19:46:00Z','parameters':PARAMS}


def test_all_eight_rules_select_expected_frozen_contracts(tmp_path):
    contracts,records,metadata=chain();store=OptionDataStore(tmp_path)
    identity=store.save(contracts,pd.DataFrame(records),metadata)['snapshot_id']
    expected={'long_call':['CALL100'],'long_put':['PUT100'],'protective_put':['PUT95'],
              'covered_call':['CALL105'],'cash_secured_put':['PUT95'],'collar':['PUT95','CALL105'],
              'bull_call_debit_spread':['CALL100','CALL105'],'bear_put_debit_spread':['PUT100','PUT95']}
    for name,ids in expected.items():
        result=select(store,identity,request(name))
        assert [leg['contract']['contract_id'] for leg in result['legs']]==ids
        assert result['status']=='SELECTED_FOR_RESEARCH' and not result['executable']


def test_future_rows_cannot_shadow_prior_quotes_or_change_decision_hash(tmp_path):
    contracts,records,metadata=chain();store=OptionDataStore(tmp_path)
    identity=store.save(contracts,pd.DataFrame(records),metadata)['snapshot_id']
    first=select(store,identity,request('collar'))
    future=deepcopy(records[0]);future.update(exchange_timestamp='2026-10-10T19:45:00Z',
         available_at='2026-10-10T19:45:02Z',received_at='2026-10-10T19:45:04Z',underlying_timestamp='2026-10-10T19:45:00Z',underlying_price=500)
    other=store.save(contracts,pd.DataFrame(records+[future]),metadata)['snapshot_id']
    assert select(store,other,request('collar'))['decision_hash']==first['decision_hash']


def test_missing_or_unsynchronized_leg_blocks_whole_package(tmp_path):
    contracts,records,metadata=chain();store=OptionDataStore(tmp_path)
    for row in records:
        if row['contract_id']=='CALL105':row.update(bid_size=0)
        if row['contract_id']=='CALL110':row.update(bid_size=0)
    identity=store.save(contracts,pd.DataFrame(records),metadata)['snapshot_id']
    assert select(store,identity,request('collar'))['status']=='BLOCKED'


def test_future_open_interest_is_not_in_prior_decision_evidence(tmp_path):
    contracts,records,metadata=chain();store=OptionDataStore(tmp_path)
    for row in records:
        row['open_interest_available_at']='2026-10-10T12:00:00Z'
    first_id=store.save(contracts,pd.DataFrame(records),metadata)['snapshot_id']
    first=select(store,first_id,request('collar'))
    for row in records:row['open_interest']=999999
    second_id=store.save(contracts,pd.DataFrame(records),metadata)['snapshot_id']
    second=select(store,second_id,request('collar'))
    assert first['decision_hash']==second['decision_hash']
    assert all(leg['reference_quote']['open_interest'] is None for leg in first['legs'])
