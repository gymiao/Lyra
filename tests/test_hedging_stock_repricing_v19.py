import json
from copy import deepcopy
from pathlib import Path
import pandas as pd
import pytest
from personal_quant.common import QuantError,decimal as D,canonical,digest
from personal_quant.data.calendar import Calendar
from personal_quant.hedging.stock_plans import save as draft,validate_references
from personal_quant.hedging.stock_repricing import save as reprice
from personal_quant.hedging.stock_activation import save as activate
from personal_quant.hedging.groups import save as bind,history,progress
from personal_quant.hedging.group_revisions import save as revise,heads
from personal_quant.hedging.archive import publish
from personal_quant.hedging.intents import records
from personal_quant.hedging.allocation_store import resources
from personal_quant.execution.plans import PlanService
from personal_quant.execution.simulator import simulate
from personal_quant.portfolio.reconciliation import ReconciliationRules
from test_hedging_stock_plans_v19 import draft_request
from test_hedging_archive_v19 import frozen_risk
from test_hedging_exposure_v19 import risk_market
from conftest import event


def prepare(fixture):
    book,config,store,query,calendar=fixture
    request=draft_request(fixture);opening=draft(book,config,'sample',request,commit=True)
    closing=draft(book,config,'sample',dict(request,request_id='close',expected_resource_hash=resources(book,'sample'),
        exit=dict(opening_plan_id=opening['plan_id'],execution_session='2025-01-21')),commit=True)
    parent=records(book,'sample')[0]
    group=bind(book,'sample',dict(schema_version=1,request_id='roundtrip',hedge_id=parent['hedge_id'],parent_version=parent['version_hash'],
        expected_resource_hash=resources(book,'sample'),stages=[dict(stage_id='sale',plan_kind='stock',plan_id=opening['plan_id'],action='OPEN',depends_on=[]),
            dict(stage_id='restore',plan_kind='stock',plan_id=closing['plan_id'],action='CLOSE',depends_on=['sale'])],reason='Synthetic price revisions'),commit=True)
    frame,_,_=store.load(request['snapshot_id']);last=frame.loc[frame.session_date==calendar.sessions[-1]]
    extra=[];future=Calendar.market('2025-01-16','2025-01-31')
    for day in future.sessions:
        rows=last.copy();rows['session_date']=day;rows['available_at']=future.close(day)+pd.Timedelta(minutes=30)
        price=100 if str(day.date())=='2025-01-16' else 110 if day<=pd.Timestamp('2025-01-21') else 120
        for f in ('open','high','low','close','adj_close'):rows.loc[rows.symbol=='SPY',f]=price
        extra.append(rows)
    frame=pd.concat([frame,*extra],ignore_index=True);calendar=Calendar(pd.concat([calendar.schedule,future.schedule]),calendar.kind)
    snapshot=store.save(frame,calendar)['snapshot_id']
    query.update(valuation_snapshot_id=snapshot,return_snapshot_id=snapshot,min_r2=0,max_standard_error=100)
    service=PlanService(book,config)
    def phase(node,clock):
        current=heads(history(book,'sample'))[0]
        risk=publish(book,config,store,'sample',dict(query,ledger_seq=book.sequence('sample'),as_of=clock,knowledge_cutoff=clock))
        return dict(group_id=current['group_id'],expected_group_hash=current['record_hash'],expected_resource_hash=resources(book,'sample'),
            stage_id=node,exposure_id=risk['exposure_id'],option_snapshot_id=None,
            quote_limits=dict(max_age_seconds=3600,max_underlying_skew_seconds=120,max_spread_fraction=.2,max_leg_skew_seconds=10,max_underlying_price_fraction=.01),
            stress=dict(scenarios=[dict(name='down',horizon_date=clock[:10],benchmark_return=-.2,beta_multiplier=1,residual_returns={'SPY':0},volatility_multiplier=1)],models={},
                limits=dict(stock_cost_bps=7,option_fee_per_contract=2,adverse_slippage_fraction=0,cash_buffer=0,minimum_sample_equity=0,maximum_sample_loss=10000)))
    def reconcile(clock,cash,shares,equity,price):
        book.reconcile('sample',dict(account_id='sample',currency='USD',as_of=clock,cash_basis='settled',cash=cash,positions={'SPY':shares},equity=equity),
            {'SPY':price},rules=ReconciliationRules.from_config(config))
    def activation(plan,node,clock):
        check=phase(node,clock)
        return activate(book,'sample',dict(schema_version=1,request_id='activate-'+plan,plan_id=plan,as_of=clock,
            expected_resource_hash=resources(book,'sample'),hedge_stage_check=check),commit=True)
    reconcile(request['as_of'],20000,100,30000,100)
    activation(opening['plan_id'],'sale',request['as_of'])
    return book,config,store,query,frame,calendar,group,opening,closing,service,phase,reconcile,activation


def repriced(state,old,node,clock,execution):
    book,config,*_=state;check=state[10](node,clock);group=heads(history(book,'sample'))[0]
    req=dict(schema_version=1,request_id='reprice-'+old,plan_id=old,group_id=group['group_id'],expected_group_hash=group['record_hash'],
        expected_resource_hash=resources(book,'sample'),exposure_id=check['exposure_id'],as_of=clock,execution_session=execution,reason='Explicit current quote, preserve remaining')
    before=resources(book,'sample');preview=reprice(book,config,'sample',req)
    assert resources(book,'sample')==before
    new=reprice(book,config,'sample',req,commit=True)
    assert new['plan_id']==preview['plan_id'] and reprice(book,config,'sample',req,commit=True)==new
    current=revise(book,'sample',dict(schema_version=1,request_id='revise-'+old,previous_group_id=group['group_id'],
        expected_group_hash=group['record_hash'],expected_resource_hash=resources(book,'sample'),as_of=clock,
        replacements={node:new['plan_id']},reason='Replace exact remaining native stock'),commit=True)
    return new,current


def test_partial_open_reprice_keeps_original_facts_and_close_dependency(frozen_risk,tmp_path):
    state=prepare(frozen_risk);book,config,store,query,frame,calendar,group,opening,closing,service,phase,reconcile,activation=state
    book.import_events('sample',[event('partial','SELL',plan_id=opening['plan_id'],symbol='SPY',quantity=20,price=100,fee='1.4',
        effective_at='2025-01-16T21:00:00Z',settlement_at='2025-01-17T21:00:00Z')])
    service.cancel(opening['plan_id'])
    reconcile('2025-01-17T21:30:00Z','21998.6',80,'30798.6',110)
    new,current=repriced(state,opening['plan_id'],'sale','2025-01-17T21:30:00Z','2025-01-21')
    line=service.get(new['plan_id'])['payload']['sizing']['lines'][0]
    assert D(line['quantity'])==20 and D(line['price'])==110 and D(line['estimated_fee'])==D('1.54')
    assert service.get(new['plan_id'])['revision']==2 and book.sequence('sample')==3
    assert current['stages'][-1]['depends_on']==['sale','sale__retired_r2']
    activation(new['plan_id'],'sale','2025-01-17T21:30:00Z')
    assert simulate(service,new['plan_id'],frame,calendar,'2025-01-21T21:30:00Z',hedge_stage_check=phase('sale','2025-01-21T21:30:00Z'))['status']=='SUCCESS'
    # The original exit now has a different reference price. Reprice it before
    # activation rather than silently changing its frozen basis.
    service.cancel(closing['plan_id'])
    reconcile('2025-01-22T21:30:00Z','24197.06',60,'31397.06',120)
    close,current=repriced(state,closing['plan_id'],'restore','2025-01-22T21:30:00Z','2025-01-23')
    activation(close['plan_id'],'restore','2025-01-22T21:30:00Z')
    result=simulate(service,close['plan_id'],frame,calendar,'2025-01-23T21:30:00Z',hedge_stage_check=phase('restore','2025-01-23T21:30:00Z'))
    assert result['status']=='SUCCESS'
    final=book.snapshot('sample','2025-01-24T21:30:00Z',{'SPY':120})
    assert final['positions']=={'SPY':'100'} and D(final['settled_cash'])==D('19393.70') and D(final['equity'])==D('31393.70')
    assert progress(book,'sample',current,'2025-01-24T21:30:00Z')['status']=='COMPLETE'
    validate_references(book)
    # Preserve aggregate 40 and reseal the archive, but change the old receipt
    # slice to 21 and the new target to 19. The real original receipt was 20.
    row=book.connection.execute("SELECT task_id,details FROM tasks WHERE task_id LIKE 'hedge-group-revision:%' ORDER BY rowid LIMIT 1").fetchone()
    forged=json.loads(row['details'])
    for stage in forged['stages']:
        if stage['stage_id']=='sale__retired_r2':stage['lines'][0]['quantity']='21'
        if stage['stage_id']=='sale':stage['lines'][0]['quantity']='19'
    forged['group_basis']['stages']=forged['stages'];forged['group_id']=digest(forged['group_basis'])
    forged['record_hash']=digest({k:v for k,v in forged.items() if k!='record_hash'})
    book.connection.execute('UPDATE tasks SET details=? WHERE task_id=?',(canonical(forged),row['task_id']))
    with pytest.raises(QuantError) as exc:history(book,'sample')
    assert exc.value.code=='CORRUPT_HEDGE_GROUP_REVISION' and str(exc.value.__cause__)=='stock slices'


def test_close_reprice_changes_quote_without_reopening_target(frozen_risk,tmp_path):
    state=prepare(frozen_risk);book,config,store,query,frame,calendar,group,opening,closing,service,phase,reconcile,activation=state
    simulate(service,opening['plan_id'],frame,calendar,'2025-01-16T21:30:00Z',hedge_stage_check=phase('sale','2025-01-16T21:30:00Z'))
    service.cancel(closing['plan_id'])
    reconcile('2025-01-17T21:30:00Z','23997.2',60,'30597.2',110)
    new,current=repriced(state,closing['plan_id'],'restore','2025-01-17T21:30:00Z','2025-01-21')
    line=service.get(new['plan_id'])['payload']['sizing']['lines'][0]
    assert D(line['quantity'])==40 and D(line['price'])==110 and D(line['estimated_fee'])==D('3.08')
    activation(new['plan_id'],'restore','2025-01-17T21:30:00Z')
    assert simulate(service,new['plan_id'],frame,calendar,'2025-01-21T21:30:00Z',hedge_stage_check=phase('restore','2025-01-21T21:30:00Z'))['status']=='SUCCESS'
    final=book.snapshot('sample','2025-01-22T21:30:00Z',{'SPY':110})
    assert D(final['settled_cash'])==D('19594.12') and D(final['equity'])==D('30594.12')
    assert final['positions']=={'SPY':'100'} and book.sequence('sample')==4
    assert simulate(service,new['plan_id'],frame,calendar,'2025-01-21T21:30:00Z')['status']=='NO_ACTION'
    assert progress(book,'sample',current,'2025-01-22T21:30:00Z')['status']=='COMPLETE'
    from personal_quant.portfolio.backup import create_bundle,verify_bundle,restore_bundle
    from personal_quant.portfolio import Ledger
    cfg=tmp_path/'reprice.toml';cfg.write_bytes((Path(__file__).resolve().parents[1]/'configs/demo.toml').read_bytes())
    create_bundle(book.path.parent,cfg,tmp_path/'bundle');verify_bundle(tmp_path/'bundle','demo');restore_bundle(tmp_path/'bundle',tmp_path/'restored','demo')
    restored=Ledger(tmp_path/'restored/runtime/demo/account.sqlite','demo')
    try:
        validate_references(restored)
        assert restored.snapshot('sample','2025-01-22T21:30:00Z',{'SPY':110})['settled_cash']==final['settled_cash']
    finally:restored.close()


def test_partial_close_reprice_retains_one_exit_and_fixed_window(frozen_risk):
    state=prepare(frozen_risk);book,config,store,query,frame,calendar,group,opening,closing,service,phase,reconcile,activation=state
    simulate(service,opening['plan_id'],frame,calendar,'2025-01-16T21:30:00Z',hedge_stage_check=phase('sale','2025-01-16T21:30:00Z'))
    service.cancel(closing['plan_id']);reconcile('2025-01-17T21:30:00Z','23997.2',60,'30597.2',110)
    first,current=repriced(state,closing['plan_id'],'restore','2025-01-17T21:30:00Z','2025-01-21')
    activation(first['plan_id'],'restore','2025-01-17T21:30:00Z')
    book.import_events('sample',[event('half-restore','BUY',plan_id=first['plan_id'],symbol='SPY',quantity=20,price=110,fee='1.54',
        effective_at='2025-01-21T21:00:00Z',settlement_at='2025-01-22T21:00:00Z')])
    service.cancel(first['plan_id']);reconcile('2025-01-22T21:30:00Z','21795.66',80,'31395.66',120)
    check=phase('restore','2025-01-22T21:30:00Z');before=resources(book,'sample')
    bad=dict(schema_version=1,request_id='extend-window',plan_id=first['plan_id'],group_id=current['group_id'],expected_group_hash=current['record_hash'],
        expected_resource_hash=before,exposure_id=check['exposure_id'],as_of='2025-01-22T21:30:00Z',execution_session='2025-01-28',reason='Forbidden rolling window')
    with pytest.raises(QuantError) as exc:reprice(book,config,'sample',bad,commit=True)
    assert exc.value.code=='HEDGE_CLOSE_WINDOW_EXPIRED' and resources(book,'sample')==before
    second,current=repriced(state,first['plan_id'],'restore','2025-01-22T21:30:00Z','2025-01-23')
    body=service.get(second['plan_id'])['payload'];line=body['sizing']['lines'][0]
    assert D(line['quantity'])==20 and D(line['price'])==120 and D(line['estimated_fee'])==D('1.68')
    assert body['hedge_context']['reprice_close_valid_through_session']=='2025-01-27'
    assert body['revision']==3 and [s['lines'][0]['quantity'] if s['lines'] else '0' for s in current['stages'] if s['action']=='CLOSE']==['0','20','20']
    activation(second['plan_id'],'restore','2025-01-22T21:30:00Z')
    assert simulate(service,second['plan_id'],frame,calendar,'2025-01-23T21:30:00Z',hedge_stage_check=phase('restore','2025-01-23T21:30:00Z'))['status']=='SUCCESS'
    final=book.snapshot('sample','2025-01-24T21:30:00Z',{'SPY':120})
    assert final['positions']=={'SPY':'100'} and D(final['settled_cash'])==D('19393.98') and D(final['equity'])==D('31393.98')
    assert book.sequence('sample')==5 and progress(book,'sample',current,'2025-01-24T21:30:00Z')['status']=='COMPLETE'
    validate_references(book)


@pytest.mark.parametrize('problem,code',[('unreleased','NATIVE_PLAN_NOT_RELEASED'),('resource','STALE_HEDGE_RESOURCES'),
    ('cashflow','ACCOUNT_CHANGED'),('future','INVALID_REPRICE_EXECUTION')])
def test_reprice_rejects_inconsistent_basis_without_writes(frozen_risk,problem,code):
    state=prepare(frozen_risk);book,config,store,query,frame,calendar,group,opening,closing,service,phase,reconcile,activation=state
    old=opening['plan_id'];clock='2025-01-15T21:30:00Z'
    if problem!='unreleased':service.cancel(old)
    if problem=='cashflow':book.import_events('sample',[event('new-money','DEPOSIT',amount=100,effective_at='2025-01-15T21:10:00Z')])
    check=phase('sale',clock)
    req=dict(schema_version=1,request_id='refusal',plan_id=old,group_id=group['group_id'],expected_group_hash=group['record_hash'],
        expected_resource_hash=resources(book,'sample'),exposure_id=check['exposure_id'],as_of=clock,execution_session='2025-01-16',reason='Invalid basis')
    if problem=='resource':req['expected_resource_hash']='old'
    if problem=='future':req['execution_session']='2025-01-15'
    before=resources(book,'sample');sequence=book.sequence('sample')
    with pytest.raises(QuantError) as exc:reprice(book,config,'sample',req,commit=True)
    assert exc.value.code==code and resources(book,'sample')==before and book.sequence('sample')==sequence


def test_internal_dividend_payment_and_fee_keep_exact_remaining(frozen_risk):
    state=prepare(frozen_risk)
    book,config,store,query,frame,calendar,group,opening,closing,service,phase,reconcile,activation=state
    service.cancel(opening['plan_id'])
    book.import_events('sample',[
        event('dividend-due','DIVIDEND_ACCRUAL',amount=10,symbol='SPY',effective_at='2025-01-16T21:00:00Z'),
        event('dividend-paid','DIVIDEND_PAYMENT',amount=10,reference_event_id='dividend-due',effective_at='2025-01-17T21:00:00Z'),
        event('account-fee','FEE',amount=3,effective_at='2025-01-17T21:00:00Z')])
    reconcile('2025-01-17T21:30:00Z','20007',100,'31007',110)
    new,current=repriced(state,opening['plan_id'],'sale','2025-01-17T21:30:00Z','2025-01-21')
    body=service.get(new['plan_id'])['payload']
    assert book.sequence('sample')==5
    assert D(body['snapshot']['settled_cash'])==D('20007')
    assert D(body['snapshot']['receivables'])==0
    assert D(body['snapshot']['net_contributions'])==30000
    assert D(body['snapshot']['investment_pnl'])==1007
    assert [(l['side'],D(l['quantity']),D(l['estimated_fee'])) for l in body['sizing']['lines']]==[('SELL',D(40),D('3.08'))]
    validate_references(book)


@pytest.mark.parametrize('late',['plan','group','parent','data'])
def test_forward_reprice_rejects_artifacts_received_after_decision(late):
    from personal_quant.common import utc
    from personal_quant.hedging.stock_repricing import _forward_basis
    old={'created_at':'2026-10-12T00:00:00Z'}
    group={'recorded_at':'2026-10-12T00:00:00Z'}
    parent={'generated_at':'2026-10-12T00:00:00Z'}
    metadata={'acquired_at':'2026-10-12T00:00:00Z'}
    clock=utc('2026-10-12T00:00:01Z')
    _forward_basis('real',old,group,parent,metadata,clock)
    target,key={'plan':(old,'created_at'),'group':(group,'recorded_at'),'parent':(parent,'generated_at'),'data':(metadata,'acquired_at')}[late]
    target[key]='2026-10-12T00:00:02Z'
    with pytest.raises(QuantError) as exc:_forward_basis('real',old,group,parent,metadata,clock)
    assert exc.value.code=='LOOKAHEAD_REPRICE'
