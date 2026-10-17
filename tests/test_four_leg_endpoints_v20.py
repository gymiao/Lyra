from decimal import Decimal as D
from test_four_leg_v20 import selected
from conftest import event
from personal_quant.options.ledger import register_contract


def test_each_open_close_endpoint_matches_manual_cash_and_funded_collateral(tmp_path,ledger):
    from personal_quant.portfolio.schema import apply_workbench_schema,apply_v18_schema,apply_v19_schema
    with ledger.transaction():
        apply_workbench_schema(ledger.connection);apply_v18_schema(ledger.connection);apply_v19_schema(ledger.connection)
    _,_,_,selection=selected(tmp_path,'iron_condor')
    contracts=[register_contract(ledger,l['contract']) for l in selection['legs']]
    rows=[event('fund','DEPOSIT',amount=100000)]
    ledger.import_events('sample',rows)
    cash=D(100000)
    for i,(contract,side,price) in enumerate(zip(contracts,['BUY','BUY','SELL','SELL'],['.55','.55','1','1'])):
        row=event('open-'+str(i),'OPTION_TRADE',quantity=1,price=price,fee=2,
            effective_at='2026-10-09T19:45:00Z',settlement_at='2026-10-09T20:00:00Z',
            contract_version=contract.version_hash,trade_side=side,action='OPEN')
        ledger.import_events('sample',[row]);cash+=(-1 if side=='BUY' else 1)*D(price)*100-2
        state=ledger.snapshot('sample','2026-10-10T00:00:00Z',{'SPY':100,**{c.contract_id:p for c,p in zip(contracts,['.55','.55','1','1'])}})
        assert D(state['settled_cash'])==cash and not state['anomalies']
        expected=0 if i<2 else 9500 if i==2 else 20500
        assert D(state['option_cash_collateral'])==expected
    assert cash==100082 and D(state['equity'])==99992
    for j,i in enumerate([3,2,1,0]):
        contract=contracts[i];side='BUY' if i>=2 else 'SELL';price='1.05' if i>=2 else '.5'
        row=event('close-'+str(j),'OPTION_TRADE',quantity=1,price=price,fee=2,
            effective_at='2026-10-09T19:46:00Z',settlement_at='2026-10-09T20:00:00Z',
            contract_version=contract.version_hash,trade_side=side,action='CLOSE')
        ledger.import_events('sample',[row]);cash+=(-1 if side=='BUY' else 1)*D(price)*100-2
        state=ledger.snapshot('sample','2026-10-10T00:00:00Z',{'SPY':100,**{c.contract_id:1 for c in contracts}})
        assert D(state['settled_cash'])==cash and not state['anomalies']
    assert cash==99964 and state['positions']=={} and state['option_positions']=={}
    assert D(state['equity'])==99964


import pytest


@pytest.mark.parametrize('name,right,expected_cash,expected_equity,collateral,recovered_cash',[
    ('iron_condor','PUT',90664,99171,31500,99664),('iron_condor','CALL',110664,99169,30000,99664),
    ('iron_butterfly','PUT',90364,99369,31000,99864),('iron_butterfly','CALL',110364,99369,30500,99864)])
def test_one_of_two_contracts_assignment_preserves_other_obligations_and_funded_recovery(tmp_path,ledger,name,right,expected_cash,expected_equity,collateral,recovered_cash):
    from personal_quant.portfolio.schema import apply_workbench_schema,apply_v18_schema,apply_v19_schema
    with ledger.transaction():
        apply_workbench_schema(ledger.connection);apply_v18_schema(ledger.connection);apply_v19_schema(ledger.connection)
    _,_,_,selection=selected(tmp_path,name)
    contracts=[register_contract(ledger,l['contract']) for l in selection['legs']]
    ledger.import_events('sample',[event('fund','DEPOSIT',amount=100000)])
    for i,(c,side,price) in enumerate(zip(contracts,['BUY','BUY','SELL','SELL'],['.55','.55','1','1'] if name=='iron_condor' else ['1.05','1.05','2','2'])):
        ledger.import_events('sample',[event('open-'+str(i),'OPTION_TRADE',quantity=2,price=price,fee=4,
            contract_version=c.version_hash,trade_side=side,action='OPEN',effective_at='2026-10-09T19:45:00Z',settlement_at='2026-10-09T20:00:00Z')])
    short=next(c for c,l in zip(contracts,selection['legs']) if c.right==right and l['quantity_per_package']<0)
    long=next(c for c,l in zip(contracts,selection['legs']) if c.right==right and l['quantity_per_package']>0)
    row=event('partial-assignment','OPTION_ASSIGNMENT',quantity=1,contract_version=short.version_hash,position_side='SHORT',
        effective_at='2026-10-09T20:01:00Z',settlement_at='2026-10-09T20:01:00Z')
    ledger.import_events('sample',[row]);before=ledger.sequence('sample');ledger.import_events('sample',[row])
    assert ledger.sequence('sample')==before
    spot=D(90 if right=='PUT' else 120)
    marks={'SPY':spot,**{c.contract_id:str(max(D('.06'),max(D(0),c.strike-spot if c.right=='PUT' else spot-c.strike)+D('.05'))) for c in contracts}}
    state=ledger.snapshot('sample','2026-10-09T20:02:00Z',marks)
    assert state['positions']=={'SPY':'100' if right=='PUT' else '-100'}
    assert state['option_positions'][short.contract_id]=='-1'
    assert D(state['settled_cash'])==expected_cash and D(state['equity'])==expected_equity
    assert D(state['option_cash_collateral'])==collateral
    assert bool(state['anomalies'])==(right=='CALL')
    ledger.import_events('sample',[event('funded-recovery','OPTION_EXERCISE',quantity=1,contract_version=long.version_hash,position_side='LONG',
        effective_at='2026-10-09T20:03:00Z',settlement_at='2026-10-09T20:03:00Z')])
    recovered=ledger.snapshot('sample','2026-10-09T20:04:00Z',marks)
    assert recovered['positions']=={} and not recovered['anomalies']
    assert recovered['option_positions'][short.contract_id]=='-1' and recovered['option_positions'][long.contract_id]=='1'
    assert D(recovered['settled_cash'])==recovered_cash
