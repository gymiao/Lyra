"""Physical split facts change units, never economic targets or cash histories."""
from copy import deepcopy
import pandas as pd
import pytest
from personal_quant.common import QuantError,decimal as D,canonical,digest
from personal_quant.hedging.stock_repricing import save as rebase
from personal_quant.hedging.stock_units import stage_quantities
from personal_quant.hedging.groups import history,progress
from personal_quant.hedging.group_revisions import save as revise,heads
from personal_quant.hedging.allocation_store import resources
from personal_quant.hedging.stock_plans import validate_references
from personal_quant.execution.simulator import simulate
from test_hedging_stock_repricing_v19 import prepare,repriced
from test_hedging_archive_v19 import frozen_risk
from test_hedging_exposure_v19 import risk_market
from conftest import event


def split_state(fixture,*,completed=False,ratio='2'):
    state=list(prepare(fixture))
    book,config,store,query,frame,calendar,group,opening,closing,service,phase,reconcile,activation=state
    amount=40 if completed else 20
    book.import_events('sample',[event('original-sale','SELL',plan_id=opening['plan_id'],symbol='SPY',quantity=amount,price=100,fee=str(D(amount)*D('.07')),
        effective_at='2025-01-16T21:00:00Z',settlement_at='2025-01-17T21:00:00Z'),
        event('split-two','SPLIT',symbol='SPY',ratio=ratio,effective_at='2025-01-17T14:30:00Z')])
    if not completed:service.cancel(opening['plan_id'])
    service.cancel(closing['plan_id'])
    selected=(frame.symbol=='SPY')&(frame.session_date>=pd.Timestamp('2025-01-17'))
    frame=frame.copy();frame['split_ratio']=frame.split_ratio.astype(float)
    for column in ('open','high','low','close'):frame.loc[selected,column]/=float(ratio)
    frame.loc[(frame.symbol=='SPY')&(frame.session_date==pd.Timestamp('2025-01-17')),'split_ratio']=float(ratio)
    snapshot=store.save(frame,calendar)['snapshot_id'];query.update(valuation_snapshot_id=snapshot,return_snapshot_id=snapshot)
    state[4]=frame
    shares=D(100-amount)*D(ratio);cash=D(20000)+D(amount)*D(100)-D(amount)*D('.07');price=D(110)/D(ratio)
    reconcile('2025-01-17T21:30:00Z',str(cash),str(shares),str(cash+shares*price),str(price))
    return state


def request_for(state,old,node,execution='2025-01-21'):
    book,config,*_=state;clock='2025-01-17T21:30:00Z';check=state[10](node,clock)
    group=heads(history(book,'sample'))[0];body=state[9].get(old)['payload']
    stage=next(s for s in group['stages'] if s['stage_id']==node)
    proofs=stage_quantities(book.active_events('sample',clock),old,stage['lines'],body['as_of'],clock,origin_seq=body['snapshot']['ledger_seq'])['actions']
    return dict(schema_version=1,request_id='units-'+old,plan_id=old,group_id=group['group_id'],expected_group_hash=group['record_hash'],
        expected_resource_hash=resources(book,'sample'),exposure_id=check['exposure_id'],as_of=clock,execution_session=execution,
        reason='Explicit supplied split, exact remaining economic obligation',unit_actions=proofs)


def replacement(state,old,node,execution='2025-01-21'):
    book,config,*_=state;request=request_for(state,old,node,execution)
    facts=book.sequence('sample');before=resources(book,'sample')
    preview=rebase(book,config,'sample',request,unit_mode=True)
    assert resources(book,'sample')==before and book.sequence('sample')==facts
    new=rebase(book,config,'sample',request,unit_mode=True,commit=True)
    assert new['plan_id']==preview['plan_id'] and rebase(book,config,'sample',request,unit_mode=True,commit=True)==new
    assert book.sequence('sample')==facts and state[9].get(new['plan_id'])['execution_status']=='DRAFT'
    return new


def apply(state,replacements):
    book=state[0];group=heads(history(book,'sample'))[0]
    return revise(book,'sample',dict(schema_version=1,request_id='group-unit-rebase',previous_group_id=group['group_id'],
        expected_group_hash=group['record_hash'],expected_resource_hash=resources(book,'sample'),as_of='2025-01-17T21:30:00Z',
        replacements=replacements,reason='All physical stock obligations in same split basis'),commit=True)


def test_partial_sale_split_rebases_all_directions_and_roundtrip(frozen_risk):
    state=split_state(frozen_risk);book,config,store,query,frame,calendar,group,opening,closing,service,phase,reconcile,activation=state
    before=progress(book,'sample',group,'2025-01-17T21:30:00Z')
    assert before['status']=='BLOCKED' and before['stages'][0]['remaining']=={str(('SPY',None,'SELL')):'40'}
    sale=replacement(state,opening['plan_id'],'sale');close=replacement(state,closing['plan_id'],'restore','2025-01-23')
    # A changed order alone must never authorize the still-stale exit obligation.
    with pytest.raises(QuantError) as exc:apply(state,{'sale':sale['plan_id']})
    assert exc.value.code=='INCOMPLETE_STOCK_UNIT_REVISION'
    current=apply(state,{'sale':sale['plan_id'],'restore':close['plan_id']})
    assert [D(s['lines'][0]['quantity']) if s['lines'] else 0 for s in current['stages']]==[40,40,0,80]
    assert current['stages'][0]['native_lines'][0]['quantity']=='40'
    assert current['stages'][-1]['depends_on']==['sale','sale__retired_r2']
    activation(sale['plan_id'],'sale','2025-01-17T21:30:00Z')
    simulate(service,sale['plan_id'],frame,calendar,'2025-01-21T21:30:00Z',hedge_stage_check=phase('sale','2025-01-21T21:30:00Z'))
    service.cancel(close['plan_id']);reconcile('2025-01-22T21:30:00Z','24197.06',120,'31397.06',60)
    last,current=repriced(state,close['plan_id'],'restore','2025-01-22T21:30:00Z','2025-01-23')
    activation(last['plan_id'],'restore','2025-01-22T21:30:00Z')
    result=simulate(service,last['plan_id'],frame,calendar,'2025-01-23T21:30:00Z',hedge_stage_check=phase('restore','2025-01-23T21:30:00Z'))
    assert result['status']=='SUCCESS'
    final=book.snapshot('sample','2025-01-24T21:30:00Z',{'SPY':60})
    assert final['positions']=={'SPY':'200'} and D(final['settled_cash'])==D('19393.70') and D(final['equity'])==D('31393.70')
    assert progress(book,'sample',current,'2025-01-24T21:30:00Z')['status']=='COMPLETE'
    assert simulate(service,last['plan_id'],frame,calendar,'2025-01-23T21:30:00Z')['status']=='NO_ACTION'
    validate_references(book)


def test_fully_filled_open_converts_historical_units_without_reopening(frozen_risk):
    state=split_state(frozen_risk,completed=True)
    book,config,store,query,frame,calendar,group,opening,closing,service,phase,reconcile,activation=state
    close=replacement(state,closing['plan_id'],'restore')
    current=apply(state,{'restore':close['plan_id']})
    assert current['stages'][0]['plan_id']==opening['plan_id'] and D(current['stages'][0]['lines'][0]['quantity'])==80
    assert progress(book,'sample',current,'2025-01-17T21:30:00Z')['stages'][0]['status']=='COMPLETE'
    activation(close['plan_id'],'restore','2025-01-17T21:30:00Z')
    simulate(service,close['plan_id'],frame,calendar,'2025-01-21T21:30:00Z',hedge_stage_check=phase('restore','2025-01-21T21:30:00Z'))
    final=book.snapshot('sample','2025-01-22T21:30:00Z',{'SPY':55})
    assert final['positions']=={'SPY':'200'} and D(final['settled_cash'])==D('19594.12')
    assert progress(book,'sample',current,'2025-01-22T21:30:00Z')['status']=='COMPLETE'


@pytest.mark.parametrize('problem,code',[('proof','STOCK_UNIT_ACTION_MISMATCH'),('ordinary','INVALID_HEDGE_STOCK_REPRICE'),('price','STOCK_UNIT_PRICE_ACTION_MISMATCH'),('undeclared','STOCK_UNIT_PRICE_ACTION_MISMATCH')])
def test_no_implicit_or_unmatched_unit_authorization(frozen_risk,problem,code):
    state=split_state(frozen_risk);book,config,store,query,frame,*_=state;request=request_for(state,state[7]['plan_id'],'sale')
    if problem=='proof':request['unit_actions'][0]['content_hash']='0'*64
    if problem=='price':
        frame=frame.copy();frame['split_ratio']=1
        selected=(frame.symbol=='SPY')&(frame.session_date==pd.Timestamp('2025-01-17'))
        for column in ('open','high','low','close'):frame.loc[selected,column]=110
        snapshot=store.save(frame,state[5])['snapshot_id'];query.update(valuation_snapshot_id=snapshot,return_snapshot_id=snapshot)
        request=request_for(state,state[7]['plan_id'],'sale')
    if problem=='undeclared':
        frame=frame.copy();frame.loc[(frame.symbol=='SPY')&(frame.session_date==pd.Timestamp('2025-01-16')),'split_ratio']=2
        snapshot=store.save(frame,state[5])['snapshot_id'];query.update(valuation_snapshot_id=snapshot,return_snapshot_id=snapshot)
        request=request_for(state,state[7]['plan_id'],'sale')
    before=resources(book,'sample');seq=book.sequence('sample')
    with pytest.raises(QuantError) as exc:rebase(book,config,'sample',request,unit_mode=problem!='ordinary',commit=True)
    assert exc.value.code==code and resources(book,'sample')==before and book.sequence('sample')==seq


def test_reverse_split_fractional_remaining_is_not_rounded_into_order(frozen_risk):
    state=split_state(frozen_risk,ratio='.51');book,config,*_=state
    request=request_for(state,state[7]['plan_id'],'sale')
    original=book.snapshot('sample',request['as_of'],{'SPY':str(D(110)/D('.51'))})
    assert D(original['positions']['SPY'])==D('40.8')
    before=resources(book,'sample')
    with pytest.raises(QuantError) as exc:rebase(book,config,'sample',request,unit_mode=True,commit=True)
    assert exc.value.code=='HEDGE_PRICE_OR_UNIT_CHANGED' and resources(book,'sample')==before
    assert D(book.snapshot('sample',request['as_of'],original['prices'])['positions']['SPY'])==D('40.8')


def test_resealed_unit_basis_cannot_hide_original_receipt_slice(frozen_risk):
    state=split_state(frozen_risk);book=state[0]
    sale=replacement(state,state[7]['plan_id'],'sale');close=replacement(state,state[8]['plan_id'],'restore')
    current=apply(state,{'sale':sale['plan_id'],'restore':close['plan_id']})
    row=book.connection.execute("SELECT task_id,details FROM tasks WHERE task_id LIKE 'hedge-group-revision:%'").fetchone()
    forged=deepcopy(current)
    # Aggregate 80 remains unchanged; actual original receipt was 20 old shares,
    # hence 40 new shares. A 41/39 slice is a different economic obligation.
    for stage in forged['stages']:
        if stage['stage_id']=='sale__retired_r2':stage['lines'][0]['quantity']='41'
        if stage['stage_id']=='sale':stage['lines'][0]['quantity']='39'
    forged['group_basis']['stages']=forged['stages'];forged['group_id']=digest(forged['group_basis'])
    forged['record_hash']=digest({k:v for k,v in forged.items() if k!='record_hash'})
    book.connection.execute('UPDATE tasks SET details=? WHERE task_id=?',(canonical(forged),row['task_id']))
    with pytest.raises(QuantError) as exc:history(book,'sample')
    assert exc.value.code=='CORRUPT_HEDGE_GROUP_REVISION' and str(exc.value.__cause__)=='stock slices'
