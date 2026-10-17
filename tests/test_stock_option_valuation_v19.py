from dataclasses import replace
import pandas as pd
import pytest
from personal_quant.common import QuantError,decimal as D
from personal_quant.data.catalog import DataCatalog
from personal_quant.data.store import DataStore
from personal_quant.execution.daily import DailyRunner
from personal_quant.execution.plans import PlanService
from personal_quant.execution.simulator import simulate
from personal_quant.options.data import OptionDataStore
from personal_quant.options.ledger import register_contract
from personal_quant.options.valuation import planning_marks
from personal_quant.portfolio import Ledger
from personal_quant.portfolio.reconciliation import ReconciliationRules
from personal_quant.portfolio.schema import apply_workbench_schema,apply_v18_schema,apply_v19_schema
from personal_quant.strategies import signal
from test_options_data_v19 import sample
from conftest import event

AS_OF='2024-07-31T21:00:00Z'
LIMITS={'max_age_seconds':7200,'max_underlying_skew_seconds':10,'max_spread_fraction':.2,'max_leg_skew_seconds':10}


@pytest.fixture
def combined(tmp_path,monkeypatch,market,config):
    monkeypatch.chdir(tmp_path)
    book=Ledger(tmp_path/'runtime/demo/account.sqlite','demo');book.account('sample')
    with book.transaction():
        apply_workbench_schema(book.connection);apply_v18_schema(book.connection);apply_v19_schema(book.connection)
    _,frame,_,calendar=market;frame=frame.copy()
    frame[['open','high','low','close','adj_close']]=100.0
    stock=DataStore(book.path.parent/'data');meta=stock.save(frame,calendar)
    for role in ('signal','execution','valuation'):
        DataCatalog(book).bind(role,meta['snapshot_id'],expected_revision=0)
    cfg=replace(config,symbols=('SPY',),weights=(.5,),active_strategy='fixed',max_weight=1,
                cash_buffer=0,commission_bps=0,slippage_bps=0,fixed_fee=0)
    c,q,m=sample();body=c.content();body.update(right='PUT',listed_at='2024-01-01T00:00:00Z')
    c=register_contract(book,body)
    book.import_events('sample',[event('fund','DEPOSIT',amount=1000),
        event('put','OPTION_TRADE',contract_version=c.version_hash,quantity=1,action='OPEN',trade_side='BUY',price=2,
              effective_at='2024-07-31T20:00:00Z',settlement_at='2024-07-31T20:00:00Z')])
    q.update(contract_version=c.version_hash,exchange_timestamp='2024-07-31T20:00:00Z',
             available_at='2024-07-31T20:00:02Z',received_at='2024-07-31T20:00:04Z',
             last_timestamp='2024-07-31T20:00:00Z',underlying_timestamp='2024-07-31T20:00:00Z',
             open_interest_available_at='2024-07-31T12:00:00Z')
    options=OptionDataStore(book.path.parent/'options/chains')
    sid=options.save([c],pd.DataFrame([q]),m)['snapshot_id']
    request={'snapshot_id':sid,'limits':LIMITS}
    book.reconcile('sample',{'account_id':'sample','currency':'USD','as_of':AS_OF,'cash_basis':'settled',
                   'cash':800,'positions':{},'option_positions':{c.contract_id:1},'equity':1005},
                   {c.contract_id:2.05},rules=ReconciliationRules.from_config(cfg))
    value=signal(frame,calendar,cfg,'2024-07-31','fixed',meta['snapshot_id'])
    try:yield book,cfg,stock,frame,meta,calendar,c,q,m,options,request,value
    finally:book.close()


def create(combined,request):
    book,cfg,_,frame,meta,calendar,*_=combined
    return PlanService(book,cfg).create('sample',combined[-1],frame,meta,calendar,AS_OF,option_valuation=request)


def test_actual_stock_plan_includes_option_value_without_second_premium(combined):
    plan=create(combined,combined[-2]);body=plan['payload']
    assert plan['check_status']=='PASSED',body['checks']
    assert D(body['snapshot']['equity'])==D(1005)
    assert D(body['snapshot']['settled_cash'])==800
    assert D(body['sizing']['lines'][0]['quantity'])==5 # floor(50% * 1005 / 100)
    assert body['option_valuation']['prices']=={combined[6].contract_id:'2.05'}
    assert combined[0].sequence('sample')==2


@pytest.mark.parametrize('problem',['missing','future','stale','misaligned'])
def test_bad_combined_marks_block_actual_plan_without_reservation(combined,problem):
    book,_,_,_,_,_,c,q,m,store,request,_=combined
    if problem=='missing':request=None
    else:
        q=dict(q)
        if problem=='future':q['received_at']='2024-07-31T21:00:01Z'
        if problem=='stale':request={**request,'limits':{**LIMITS,'max_age_seconds':60}}
        if problem=='misaligned':
            q.update(exchange_timestamp='2024-07-31T19:45:00Z',underlying_timestamp='2024-07-31T19:45:00Z')
        if problem!='stale':request={**request,'snapshot_id':store.save([c],pd.DataFrame([q]),m)['snapshot_id']}
    plan=create(combined,request)
    assert plan['check_status']=='BLOCKED' and plan['reserved_cash']=='0'
    assert book.sequence('sample')==2


def test_revision_requires_explicit_new_marks(combined):
    book,cfg,_,frame,meta,calendar,*_=combined
    service=PlanService(book,cfg);blocked=create(combined,None)
    ready=service.revise(blocked['plan_id'],frame,meta,calendar,AS_OF,option_valuation=combined[-2])
    assert ready['check_status']=='PASSED'
    missing=service.revise(ready['plan_id'],frame,meta,calendar,AS_OF)
    assert missing['check_status']=='BLOCKED'
    assert missing['payload']['checks'][0]['code']=='OPTION_VALUATION_REQUEST_REQUIRED'


def test_daily_uses_explicit_marks_to_make_same_stock_plan(combined):
    book,cfg,stock,*_=combined
    result=DailyRunner(book,cfg,stock).run('sample',as_of=AS_OF,option_valuation=combined[-2])
    assert result['planning']['status']=='SUCCESS',result['planning']
    body=PlanService(book,cfg).get(result['planning']['plan_id'])['payload']
    assert D(body['snapshot']['equity'])==1005 and D(body['sizing']['lines'][0]['quantity'])==5


def test_simulation_rechecks_fill_day_marks_and_preserves_option_position(combined):
    book,cfg,_,frame,_,calendar,c,q,m,store,_,_=combined
    service=PlanService(book,cfg);plan=create(combined,combined[-2])
    with pytest.raises(QuantError) as exc:simulate(service,plan['plan_id'],frame,calendar,'2024-08-01T21:00:00Z')
    assert exc.value.code=='OPTION_VALUATION_REQUEST_REQUIRED' and book.sequence('sample')==2
    q=dict(q)
    for key in ('exchange_timestamp','available_at','received_at','last_timestamp','underlying_timestamp','open_interest_available_at'):
        q[key]=q[key].replace('2024-07-31','2024-08-01')
    request={'snapshot_id':store.save([c],pd.DataFrame([q]),m)['snapshot_id'],'limits':LIMITS}
    result=simulate(service,plan['plan_id'],frame,calendar,'2024-08-01T21:00:00Z',
                    state_as_of='2024-08-01T20:00:00Z',option_valuation=request)
    assert result['status']=='SUCCESS'
    assert result['option_valuation']['knowledge_cutoff']=='2024-08-01T21:00:00+00:00'
    state=book.snapshot('sample','2024-08-02T21:00:00Z',{'SPY':100,c.contract_id:2.05})
    assert {s:D(q) for s,q in state['positions'].items()}=={'SPY':D(5)} and state['option_positions']=={c.contract_id:'1'}
    assert D(state['settled_cash'])==300 and D(state['equity'])==1005
    assert book.sequence('sample')==3


def test_future_exchange_price_cannot_enter_delayed_close_marks(combined):
    book,_,_,_,_,_,c,q,m,store,_,_=combined
    q=dict(q);q.update(exchange_timestamp='2024-07-31T20:00:01Z',underlying_timestamp='2024-07-31T20:00:01Z')
    request={'snapshot_id':store.save([c],pd.DataFrame([q]),m)['snapshot_id'],'limits':LIMITS}
    with pytest.raises(QuantError) as exc:
        planning_marks(book,'sample',{'SPY':100},'2024-07-31T20:00:00Z',request,
                       '2024-07-31T20:00:00Z',knowledge_cutoff=AS_OF)
    assert exc.value.code=='INCOMPLETE_OPTION_VALUATION'


def test_synthetic_marks_cannot_qualify_paper_account(combined):
    book,*_=combined;book.environment='paper'
    with pytest.raises(QuantError) as exc:
        planning_marks(book,'sample',{'SPY':100},AS_OF,combined[-2],'2024-07-31T20:00:00Z')
    assert exc.value.code=='INCOMPLETE_OPTION_VALUATION'
