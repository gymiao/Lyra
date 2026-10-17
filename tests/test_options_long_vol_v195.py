from native_tools import native_engine_root,native_dotnet
from decimal import Decimal
import pandas as pd
import pytest
from test_options_selection_v19 import chain,request
from test_options_monthly_replay_v19 import monthly_signals,ROOT
from personal_quant.options.catalog import A8,template
from personal_quant.options.data import OptionDataStore
from personal_quant.options.selection import select
from personal_quant.options.payoff import analyze
from personal_quant.options.monthly_replay import monthly_replay
from personal_quant.options.contracts import OptionContract


@pytest.mark.parametrize('name,ids',[('long_straddle',['CALL100','PUT100']),('long_strangle',['PUT95','CALL105'])])
def test_long_vol_selection_and_expiry_loss_are_explicit(tmp_path,name,ids):
    contracts,records,metadata=chain();store=OptionDataStore(tmp_path)
    identity=store.save(contracts,pd.DataFrame(records),metadata)['snapshot_id']
    frozen=select(store,identity,request(name))
    assert [leg['contract']['contract_id'] for leg in frozen['legs']]==ids
    assert all(leg['quantity_per_package']==1 for leg in frozen['legs'])
    assert not frozen['executable'] and name not in A8
    result=analyze(template(name,premium=2,second_premium=3,fee=1),prices=[80,100,120])
    assert Decimal(result['maximum_loss'])==502
    assert result['profit_unbounded'] and not result['loss_unbounded']
    assert Decimal(result['points'][1]['pnl'])==-502
    assert Decimal(result['points'][0]['pnl'])==(1498 if name=='long_straddle' else 998)


def test_straddle_uses_shared_strike_in_asymmetric_chain(tmp_path):
    contracts,records,metadata=chain()
    contracts=[c for c in contracts if c.contract_id!='PUT100']
    records=[r for r in records if r['contract_id']!='PUT100']
    store=OptionDataStore(tmp_path);identity=store.save(contracts,pd.DataFrame(records),metadata)['snapshot_id']
    assert select(store,identity,request('long_straddle'))['status']=='BLOCKED'


def test_straddle_distance_is_not_biased_by_number_of_contract_ids(tmp_path):
    contracts,records,metadata=chain()
    put95=next(c for c in contracts if c.contract_id=='PUT95')
    extra=OptionContract.from_dict({**put95.content(),'right':'CALL','contract_id':'CALL95'})
    contracts.append(extra)
    base=next(r for r in records if r['contract_id']=='PUT95')
    records.append({**base,'contract_id':extra.contract_id,'contract_version':extra.version_hash})
    call100=next(c for c in contracts if c.contract_id=='CALL100')
    base=next(r for r in records if r['contract_id']=='CALL100')
    for index in range(10):
        c=OptionContract.from_dict({**call100.content(),'contract_id':f'CALL100-{index}'})
        contracts.append(c);records.append({**base,'contract_id':c.contract_id,'contract_version':c.version_hash})
    for row in records:row['underlying_price']=99
    store=OptionDataStore(tmp_path);identity=store.save(contracts,pd.DataFrame(records),metadata)['snapshot_id']
    result=select(store,identity,request('long_straddle'))
    assert result['status']=='SELECTED_FOR_RESEARCH'
    assert {leg['contract']['strike'] for leg in result['legs']}=={'100'}


@pytest.mark.parametrize('name',['long_straddle','long_strangle'])
def test_native_two_month_long_vol_costs_and_ledger(tmp_path,name):
    signals=monthly_signals(tmp_path,name)
    proof=monthly_replay(native_engine_root(),native_dotnet(),tmp_path/'engine',signals,initial_cash=100000,fee_per_contract=2)
    # Constant underlying/quotes: 2 legs x 2 cycles x ($10 bid/ask + $4 fees).
    assert float(proof['actual_equity'])==99944
    assert float(proof['ledger_bridge']['equity'])==99944
    assert proof['ledger_bridge']['positions']=={} and proof['ledger_bridge']['option_positions']=={}
    assert proof['duplicate_events_added']==0
