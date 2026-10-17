from native_tools import native_engine_root,native_dotnet
from decimal import Decimal
import pytest
from test_options_activation_v19 import setup
from personal_quant.options.activation import activate
from personal_quant.options.lifecycle import review
from personal_quant.options.ledger import register_contract


@pytest.mark.parametrize('name,reserve,spent',[('long_straddle',434,212),('long_strangle',234,112)])
def test_long_vol_two_legs_are_budgeted_and_partial_receipts_release_only_filled_resources(ledger,tmp_path,vol_evidence,name,reserve,spent):
    store,plan,request=setup(ledger,tmp_path,vol_evidence,cash=100000,packages=1,template=name)
    audit=activate(ledger,store,request)
    assert audit['status']=='ACTIVATED' and activate(ledger,store,request)==audit
    assert Decimal(ledger.snapshot('sample',request['as_of'])['reserved_cash'])==reserve
    rows=[]
    for i,leg in enumerate(plan['selection']['legs']):
        c=register_contract(ledger,leg['contract'])
        rows.append({'event_id':f'vol-fill-{i}','source':'explicit_test_statement','evidence_type':'test',
            'kind':'OPTION_TRADE','contract_version':c.version_hash,'plan_id':plan['plan_id'],'action':'OPEN','trade_side':'BUY',
            'effective_at':'2024-11-01T19:41:00Z','settlement_at':'2024-11-01T19:41:00Z',
            'quantity':1,'price':leg['reference_price'],'fee':2})
    ledger.import_events('sample',rows[:1])
    partial=review(ledger,plan['plan_id'],'2024-11-01T19:42:00Z')
    assert partial['status']=='PARTIAL' and Decimal(partial['active_reservation']['reserved_cash'])==reserve-spent
    ledger.import_events('sample',rows[1:]);filled=review(ledger,plan['plan_id'],'2024-11-01T19:42:00Z')
    assert filled['status']=='FILLED' and Decimal(filled['active_reservation']['reserved_cash'])==0
    marks={leg['contract']['contract_id']:(Decimal(leg['reference_quote']['bid'])+Decimal(leg['reference_quote']['ask']))/2 for leg in plan['selection']['legs']}
    state=ledger.snapshot('sample','2024-11-01T19:42:00Z',marks)
    assert Decimal(state['equity'])==99986 and not state['anomalies']
    assert ledger.import_events('sample',rows)['duplicates']==2 and ledger.sequence('sample')==3


def test_long_vol_over_budget_remains_blocked_without_one_leg_only_fallback(ledger,tmp_path,vol_evidence):
    store,plan,request=setup(ledger,tmp_path,vol_evidence,cash=300,packages=1,template='long_straddle')
    audit=activate(ledger,store,request)
    assert audit['status']=='BLOCKED' and 'INSUFFICIENT_SETTLED_CASH' in audit['checks']
    assert ledger.sequence('sample')==1 and Decimal(ledger.snapshot('sample',request['as_of'])['reserved_cash'])==0


@pytest.mark.parametrize('name',['long_straddle','long_strangle'])
def test_long_vol_native_report_import_matches_plan_and_does_not_repeat(ledger,tmp_path,vol_evidence,name):
    import json
    from test_options_simulation_v19 import closing_quotes
    from test_options_monthly_replay_v19 import ROOT
    from personal_quant.options.monthly_report import monthly_compare
    from personal_quant.options.simulation import execute
    store,plan,activation=setup(ledger,tmp_path/'inputs',vol_evidence,cash=100000,packages=1,template=name)
    assert activate(ledger,store,activation)['status']=='ACTIVATED'
    signals=sorted((json.loads(p.read_text()) for p in (tmp_path/'inputs/monthly').glob('*.json')),key=lambda s:s['decision_at'])
    monthly_compare(native_engine_root(),native_dotnet(),ledger.path.parent/'options/monthly-research/comparison',signals,
                    initial_cash=100000,fee_per_contract=2,stock_commission_bps=2)
    request={'plan_id':plan['plan_id'],'report_id':'comparison','execution_snapshot_id':closing_quotes(store,activation),
             'as_of':'2024-11-01T20:01:00Z','expected_sequence':activation['expected_sequence']}
    result=execute(ledger,store,request)
    assert result['status']=='SIMULATED' and result['result']['status']=='FILLED'
    assert execute(ledger,store,request)==result
    assert Decimal(result['account']['equity'])==99986
    assert len(result['account']['option_positions'])==2 and not result['account']['positions']
    assert Decimal(result['account']['reserved_cash'])==0 and ledger.sequence('sample')==3
