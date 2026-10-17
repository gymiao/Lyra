"""Necessary CLOSE has complete accounting despite an unidentifiable portfolio Beta."""
from pathlib import Path
import pandas as pd
from personal_quant.common import decimal as D
from personal_quant.data.calendar import Calendar
from personal_quant.hedging.archive import publish,load
from personal_quant.hedging.allocation_store import resources
from personal_quant.hedging.groups import save,progress
from personal_quant.hedging.stage_assessment import analyze
from personal_quant.hedging.stage_gate import validate_record
from personal_quant.portfolio.backup import create_bundle,verify_bundle,restore_bundle
from personal_quant.portfolio import Ledger
from test_hedging_groups_v19 import request,native_stock,fill
from test_hedging_archive_v19 import frozen_risk
from test_hedging_exposure_v19 import risk_market
from conftest import event


def test_actual_group_closure_and_restore_do_not_need_a_fabricated_beta(frozen_risk,tmp_path):
    book,config,store,query,calendar=frozen_risk;parent,group_request=request(frozen_risk)
    native_stock(book,'native-close',side='BUY',quantity=40)
    group_request['stages'].append(dict(stage_id='restore',plan_kind='stock',plan_id='native-close',action='CLOSE',depends_on=['sale']))
    group_request['expected_resource_hash']=resources(book,'sample');group=save(book,'sample',group_request,commit=True)
    fill(book,parent) # 40 sold @100, with separate next-day settlement
    clock='2025-01-17T21:30:00Z'
    frame,_,_=store.load(query['valuation_snapshot_id']);last=frame.loc[frame.session_date==calendar.sessions[-1]]
    extra_calendar=Calendar.market('2025-01-16','2025-01-17');extra=[]
    for day in extra_calendar.sessions:
        rows=last.copy();rows['session_date']=day;rows['available_at']=extra_calendar.close(day)+pd.Timedelta(minutes=30);extra.append(rows)
    frame=pd.concat([frame,*extra],ignore_index=True);calendar=Calendar(pd.concat([calendar.schedule,extra_calendar.schedule]),calendar.kind)
    raw_id=store.save(frame,calendar)['snapshot_id'];returns=frame.copy();returns.loc[returns.symbol=='GLD','adj_close']=100
    history_id=store.save(returns,calendar)['snapshot_id']
    risk=publish(book,config,store,'sample',dict(query,as_of=clock,knowledge_cutoff=clock,ledger_seq=3,
        valuation_snapshot_id=raw_id,return_snapshot_id=history_id))
    archive=load(book.path.parent/'hedging/exposures',risk['exposure_id'])
    assert archive['status']=='INCOMPLETE' and archive['risk']['beta_amount'] is None
    assert 'ZERO_BENCHMARK_VARIANCE' in archive['checks']
    phase=dict(group_id=group['group_id'],expected_group_hash=group['record_hash'],expected_resource_hash=resources(book,'sample'),
        stage_id='restore',exposure_id=risk['exposure_id'],option_snapshot_id=None,
        quote_limits=dict(max_age_seconds=3600,max_underlying_skew_seconds=120,max_spread_fraction=.2,max_leg_skew_seconds=10,max_underlying_price_fraction=.01),
        stress=dict(scenarios=[dict(name='direct_decline',horizon_date='2025-01-17',benchmark_return=0,beta_multiplier=1,
            residual_returns={'SPY':-.2},volatility_multiplier=1)],models={},limits=dict(stock_cost_bps=7,option_fee_per_contract=2,
            adverse_slippage_fraction=0,cash_buffer=0,minimum_sample_equity=0,maximum_sample_loss=10000)))
    assessment=analyze(book,'sample',phase)
    assert assessment['status']=='CHECKED' and not assessment['executable']
    assert D(assessment['vertices'][1]['required_settled_cash'])==D('4002.8')
    assert D(assessment['vertices'][0]['minimum_sample_equity'])==28800
    assert D(assessment['vertices'][1]['minimum_sample_equity'])==D('27997.2')
    validate_record(book,'sample','native-close','CLOSE',phase,assessment)
    book.import_events('sample',[event('actual-close','BUY',plan_id='native-close',symbol='SPY',quantity=40,price=100,fee='2.8',
        effective_at=clock,settlement_at='2025-01-21T21:00:00Z')])
    finished='2025-01-21T21:30:00Z';state=book.snapshot('sample',finished,{'SPY':100})
    assert state['positions']=={'SPY':'100'} and D(state['settled_cash'])==D('19997.2')
    assert D(state['equity'])==D('29997.2') and book.sequence('sample')==4
    assert progress(book,'sample',group,finished)['status']=='COMPLETE'
    validate_record(book,'sample','native-close','CLOSE',phase,assessment)
    cfg=tmp_path/'demo.toml';cfg.write_bytes((Path(__file__).resolve().parents[1]/'configs/demo.toml').read_bytes())
    create_bundle(book.path.parent,cfg,tmp_path/'bundle');verify_bundle(tmp_path/'bundle','demo');restore_bundle(tmp_path/'bundle',tmp_path/'restored','demo')
    recovered=Ledger(tmp_path/'restored/runtime/demo/account.sqlite','demo')
    try:
        validate_record(recovered,'sample','native-close','CLOSE',phase,assessment)
        assert recovered.snapshot('sample',finished,{'SPY':100})==state
    finally:recovered.close()
