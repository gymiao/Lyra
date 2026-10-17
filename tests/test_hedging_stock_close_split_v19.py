"""A split after a real partial exit preserves one remaining close obligation."""
import pandas as pd
from personal_quant.common import decimal as D
from personal_quant.hedging.groups import history,progress
from personal_quant.hedging.group_revisions import heads,save as revise
from personal_quant.hedging.stock_repricing import save as rebase
from personal_quant.hedging.stock_units import stage_quantities
from personal_quant.hedging.stock_plans import validate_references
from personal_quant.hedging.allocation_store import resources
from personal_quant.execution.simulator import simulate
from test_hedging_stock_repricing_v19 import prepare,repriced
from test_hedging_archive_v19 import frozen_risk
from test_hedging_exposure_v19 import risk_market
from conftest import event


def test_split_after_partial_close_preserves_single_obligation(frozen_risk):
    state=list(prepare(frozen_risk));book,config,store,query,frame,calendar,group,opening,closing,service,phase,reconcile,activation=state
    simulate(service,opening['plan_id'],frame,calendar,'2025-01-16T21:30:00Z',hedge_stage_check=phase('sale','2025-01-16T21:30:00Z'))
    service.cancel(closing['plan_id']);reconcile('2025-01-17T21:30:00Z','23997.2',60,'30597.2',110)
    first,current=repriced(state,closing['plan_id'],'restore','2025-01-17T21:30:00Z','2025-01-21')
    activation(first['plan_id'],'restore','2025-01-17T21:30:00Z')
    book.import_events('sample',[event('actual-half-close','BUY',plan_id=first['plan_id'],symbol='SPY',quantity=20,price=110,fee='1.54',
        effective_at='2025-01-21T21:00:00Z',settlement_at='2025-01-22T21:00:00Z'),
        event('split-after-close','SPLIT',symbol='SPY',ratio=2,effective_at='2025-01-22T14:30:00Z')])
    service.cancel(first['plan_id'])
    frame=frame.copy();selected=(frame.symbol=='SPY')&(frame.session_date>=pd.Timestamp('2025-01-22'))
    for col in ('open','high','low','close'):frame.loc[selected,col]/=2
    frame.loc[(frame.symbol=='SPY')&(frame.session_date==pd.Timestamp('2025-01-22')),'split_ratio']=2
    snapshot=store.save(frame,calendar)['snapshot_id'];query.update(valuation_snapshot_id=snapshot,return_snapshot_id=snapshot)
    reconcile('2025-01-22T21:30:00Z','21795.66',160,'31395.66',60)
    clock='2025-01-22T21:30:00Z';check=phase('restore',clock);current=heads(history(book,'sample'))[0]
    old=service.get(first['plan_id'])['payload'];stage=next(s for s in current['stages'] if s['stage_id']=='restore')
    actions=stage_quantities(book.active_events('sample',clock),first['plan_id'],stage['lines'],old['as_of'],clock,origin_seq=old['snapshot']['ledger_seq'])['actions']
    request=dict(schema_version=1,request_id='partial-close-split',plan_id=first['plan_id'],group_id=current['group_id'],expected_group_hash=current['record_hash'],
        expected_resource_hash=resources(book,'sample'),exposure_id=check['exposure_id'],as_of=clock,execution_session='2025-01-23',
        reason='Actual split after 20 original close shares, now 40 new shares remain',unit_actions=actions)
    new=rebase(book,config,'sample',request,unit_mode=True,commit=True)
    assert D(service.get(new['plan_id'])['payload']['sizing']['lines'][0]['quantity'])==40
    current=revise(book,'sample',dict(schema_version=1,request_id='partial-close-split-group',previous_group_id=current['group_id'],
        expected_group_hash=current['record_hash'],expected_resource_hash=resources(book,'sample'),as_of=clock,
        replacements={'restore':new['plan_id']},reason='One root closing obligation, all slices in new units'),commit=True)
    assert {s.get('close_obligation_id','restore') for s in current['stages'] if s['action']=='CLOSE'}=={'restore'}
    activation(new['plan_id'],'restore',clock)
    assert simulate(service,new['plan_id'],frame,calendar,'2025-01-23T21:30:00Z',hedge_stage_check=phase('restore','2025-01-23T21:30:00Z'))['status']=='SUCCESS'
    final=book.snapshot('sample','2025-01-24T21:30:00Z',{'SPY':60})
    assert final['positions']=={'SPY':'200'} and D(final['settled_cash'])==D('19393.98') and D(final['equity'])==D('31393.98')
    assert progress(book,'sample',current,'2025-01-24T21:30:00Z')['status']=='COMPLETE'
    validate_references(book)
