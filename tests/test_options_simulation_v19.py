from native_tools import native_engine_root,native_dotnet
import json
import shutil
from pathlib import Path
import pandas as pd
import pytest
from personal_quant.common import QuantError
from personal_quant.options.activation import activate
from personal_quant.options.simulation import execute
from personal_quant.options.monthly_report import monthly_compare
from personal_quant.portfolio import Ledger
from personal_quant.portfolio.backup import create_bundle,verify_bundle,restore_bundle
from test_options_activation_v19 import setup,engine_evidence
from test_options_monthly_replay_v19 import ROOT


@pytest.mark.parametrize('template,shares,loss,collateral',[
    ('long_call',0,7,0),('long_put',0,7,0),('protective_put',100,7,0),
    ('covered_call',100,7,0),('cash_secured_put',0,7,9500),('collar',100,14,0),
    ('bull_call_debit_spread',0,14,10000),('bear_put_debit_spread',0,14,9500)])
def test_a8_simulation_uses_account_stock_once_and_actual_option_collateral(tmp_path,engine_evidence,template,shares,loss,collateral):
    root=tmp_path/'runtime';book=Ledger(root/'account.sqlite','demo');book.account('sample')
    try:
        store,plan,activation=setup(book,tmp_path/'inputs',engine_evidence,cash=100000,packages=1,template=template,shares=shares)
        activate(book,store,activation)
        signals=sorted((json.loads(p.read_text()) for p in (tmp_path/'inputs/monthly').glob('*.json')),key=lambda s:s['decision_at'])
        monthly_compare(native_engine_root(),native_dotnet(),root/'options/monthly-research/comparison',signals,
            initial_cash=100000,fee_per_contract=2,stock_commission_bps=2)
        quote=closing_quotes(store,activation)
        request={'plan_id':plan['plan_id'],'report_id':'comparison','execution_snapshot_id':quote,
            'as_of':'2024-11-01T20:01:00Z','expected_sequence':activation['expected_sequence']}
        result=execute(book,store,request)
        assert result['status']=='SIMULATED' and result['result']['status']=='FILLED'
        assert execute(book,store,request)==result
        state=result['account']
        assert float(state['equity'])==100000-loss
        assert float(state['reserved_cash'])==collateral and float(state['option_cash_collateral'])==collateral
        assert state['positions']==({'SPY':'100'} if shares else {})
        assert len(result['research_underlying_events_not_imported'])==(1 if shares else 0)
        assert book.sequence('sample')==activation['expected_sequence']+len(plan['sizing']['lines'])
        stock_events=[e for e in book.active_events('sample',request['as_of']) if e['kind'] in {'BUY','SELL'}]
        assert len(stock_events)==(1 if shares else 0)
    finally:book.close()


def closing_quotes(store,request,price_change=0):
    contracts,rows,metadata,_=store.load(request['quote_snapshot_id'])
    symbols={l['contract']['contract_id'] for l in request['monthly_signal']['selection']['legs']}
    for row in rows:
        if row['contract_id'] in symbols:
            row.update(exchange_timestamp='2024-11-01T20:00:00Z',underlying_timestamp='2024-11-01T20:00:00Z',
                available_at='2024-11-01T20:00:02Z',received_at='2024-11-01T20:00:04Z')
            row['bid']=str(float(row['bid'])+price_change);row['ask']=str(float(row['ask'])+price_change)
    return store.save(list(contracts.values()),pd.DataFrame(rows),metadata)['snapshot_id']


def test_engine_batch_is_atomic_idempotent_and_restores_settlement(tmp_path,monkeypatch,engine_evidence):
    monkeypatch.chdir(tmp_path)
    config=tmp_path/'demo.toml';config.write_bytes((ROOT/'configs/demo.toml').read_bytes())
    root=Path('runtime/demo');book=Ledger(root/'account.sqlite','demo');book.account('sample')
    try:
        store,plan,activation=setup(book,tmp_path/'inputs',engine_evidence,packages=1)
        activate(book,store,activation)
        signals=sorted((json.loads(p.read_text()) for p in (tmp_path/'inputs/monthly').glob('*.json')),key=lambda s:s['decision_at'])
        monthly_compare(native_engine_root(),native_dotnet(),root/'options/monthly-research/comparison',signals,
            initial_cash=100000,fee_per_contract=2,stock_commission_bps=2)
        quote=closing_quotes(store,activation)
        request={'plan_id':plan['plan_id'],'report_id':'comparison','execution_snapshot_id':quote,
            'as_of':'2024-11-01T21:01:00Z','expected_sequence':1}
        with pytest.raises(QuantError,match='尚未到达'):execute(book,store,{**request,'as_of':'2024-11-01T19:59:00Z'})
        with pytest.raises(QuantError,match='收盘报价'):execute(book,store,{**request,'execution_snapshot_id':activation['quote_snapshot_id']})
        wrong=closing_quotes(store,activation,.2)
        with pytest.raises(QuantError,match='偏离'):execute(book,store,{**request,'execution_snapshot_id':wrong})
        assert book.sequence('sample')==1
        result=execute(book,store,request)
        assert execute(book,store,request)==result and result['status']=='SIMULATED'
        assert result['result']['status']=='FILLED' and result['delayed_processing']
        state=result['account']
        # One short Put: 100 premium less 2 fee receivable; mark liability 105.
        assert float(state['settled_cash'])==22000 and float(state['receivables'])==98
        assert float(state['equity'])==21993 and float(state['reserved_cash'])==9500
        assert float(state['available_cash'])==12500 and book.sequence('sample')==2
        symbol=result['rows'][0]['contract_version']
        assert symbol==plan['selection']['legs'][0]['contract_version']
        # US DST ended Nov 3: Nov 4 closes at 21:00 UTC, not 20:00.
        unsettled=book.snapshot('sample','2024-11-04T20:01:00Z',{plan['selection']['legs'][0]['contract']['contract_id']:1.05})
        assert float(unsettled['receivables'])==98 and float(unsettled['settled_cash'])==22000
        settled=book.snapshot('sample','2024-11-04T21:01:00Z',{plan['selection']['legs'][0]['contract']['contract_id']:1.05})
        assert float(settled['settled_cash'])==22098 and float(settled['receivables'])==0
        assert float(settled['equity'])==21993
        with pytest.raises(QuantError,match='不能换输入'):execute(book,store,{**request,'as_of':'2024-11-01T20:02:00Z'})
        assert book.sequence('sample')==2
        shutil.copytree(store.root,root/'options/chains')
        create_bundle(root,config,tmp_path/'bundle');verify_bundle(tmp_path/'bundle','demo')
        restore_bundle(tmp_path/'bundle',tmp_path/'recovered','demo')
        recovered=Ledger(tmp_path/'recovered'/root/'account.sqlite','demo')
        try:
            after=recovered.snapshot('sample',request['as_of'],{plan['selection']['legs'][0]['contract']['contract_id']:1.05})
            assert float(after['equity'])==21993 and float(after['reserved_cash'])==9500
            assert recovered.sequence('sample')==2
        finally:recovered.close()
    finally:book.close()
