from native_tools import native_engine_root,native_dotnet
from decimal import Decimal
import pytest
from test_options_activation_v19 import setup
from personal_quant.options.activation import activate
from personal_quant.options.lifecycle import review
from personal_quant.options.contracts import OptionContract
from personal_quant.options.ledger import register_contract


@pytest.mark.parametrize('name,reserve,collateral',[('bull_put_credit_spread',9624,9500),('bear_call_credit_spread',11124,11000)])
def test_credit_plan_activation_partial_fill_reservations_and_completion(ledger,tmp_path,credit_evidence,name,reserve,collateral):
    store,plan,request=setup(ledger,tmp_path,credit_evidence,cash=100000,packages=1,template=name)
    audit=activate(ledger,store,request)
    assert audit['status']=='ACTIVATED'
    assert activate(ledger,store,request)==audit
    assert Decimal(ledger.snapshot('sample',request['as_of'])['reserved_cash'])==reserve
    rows=[]
    for index,leg in enumerate(plan['selection']['legs']):
        c=register_contract(ledger,leg['contract'])
        rows.append({'event_id':f'fill-{index}','source':'explicit_test_statement','evidence_type':'test',
            'kind':'OPTION_TRADE','contract_version':c.version_hash,'plan_id':plan['plan_id'],
            'effective_at':'2024-11-01T19:41:00Z','settlement_at':'2024-11-01T19:41:00Z',
            'action':'OPEN','trade_side':'BUY' if leg['quantity_per_package']>0 else 'SELL',
            'quantity':1,'price':leg['reference_price'],'fee':2})
    ledger.import_events('sample',rows[:1])
    partial=review(ledger,plan['plan_id'],'2024-11-01T19:42:00Z')
    assert partial['status']=='PARTIAL'
    assert Decimal(partial['active_reservation']['reserved_cash'])==reserve-112
    ledger.import_events('sample',rows[1:])
    filled=review(ledger,plan['plan_id'],'2024-11-01T19:42:00Z')
    assert filled['status']=='FILLED' and Decimal(filled['active_reservation']['reserved_cash'])==0
    marks={leg['contract']['contract_id']:(Decimal(leg['reference_quote']['bid'])+Decimal(leg['reference_quote']['ask']))/2 for leg in plan['selection']['legs']}
    state=ledger.snapshot('sample','2024-11-01T19:42:00Z',marks)
    assert Decimal(state['option_cash_collateral'])==collateral
    assert Decimal(state['equity'])==99986 and not state['anomalies']
    assert ledger.import_events('sample',rows)['duplicates']==2
    assert ledger.sequence('sample')==3


@pytest.mark.parametrize('name,collateral',[('bull_put_credit_spread',9500),('bear_call_credit_spread',11000)])
def test_credit_native_simulation_uses_ready_plan_once_and_does_not_call_premium_profit(ledger,tmp_path,credit_evidence,name,collateral):
    import json
    from test_options_simulation_v19 import closing_quotes
    from test_options_monthly_replay_v19 import ROOT
    from personal_quant.options.monthly_report import monthly_compare
    from personal_quant.options.simulation import execute
    store,plan,activation=setup(ledger,tmp_path/'inputs',credit_evidence,cash=100000,packages=1,template=name)
    assert activate(ledger,store,activation)['status']=='ACTIVATED'
    signals=sorted((json.loads(p.read_text()) for p in (tmp_path/'inputs/monthly').glob('*.json')),key=lambda s:s['decision_at'])
    directory=ledger.path.parent/'options/monthly-research/comparison'
    monthly_compare(native_engine_root(),native_dotnet(),directory,signals,
                    initial_cash=100000,fee_per_contract=2,stock_commission_bps=2)
    request={'plan_id':plan['plan_id'],'report_id':'comparison','execution_snapshot_id':closing_quotes(store,activation),
             'as_of':'2024-11-01T20:01:00Z','expected_sequence':activation['expected_sequence']}
    first=execute(ledger,store,request)
    assert first['status']=='SIMULATED' and first['result']['status']=='FILLED'
    assert execute(ledger,store,request)==first
    assert Decimal(first['account']['equity'])==99986
    assert Decimal(first['account']['option_cash_collateral'])==collateral
    assert not first['account']['positions'] and ledger.sequence('sample')==3
