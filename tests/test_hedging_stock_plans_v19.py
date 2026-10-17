import json
import pytest
from personal_quant.common import QuantError, canonical, digest, decimal as D
from personal_quant.hedging.stock_plans import save, validate_references
from personal_quant.hedging.intents import save as parent_save
from personal_quant.hedging.allocation_store import resources
from personal_quant.execution.plans import PlanService
from personal_quant.execution.review import execution_review
from test_hedging_archive_v19 import frozen_risk
from test_hedging_exposure_v19 import risk_market
from test_hedging_intents_v19 import parent


def draft_request(fixture):
    book,config,store,risk,calendar=fixture
    frozen=parent_save(book,'sample',parent(fixture),commit=True)
    return dict(schema_version=1,request_id='stock-draft-one',hedge_id=frozen['hedge_id'],
        parent_version=frozen['version_hash'],expected_resource_hash=resources(book,'sample'),
        as_of=frozen['decision_at'],snapshot_id=risk['valuation_snapshot_id'],reason='explicit reduction, not monthly strategy')


def test_hedge_stock_draft_has_exact_parent_quantity_no_fake_signal_or_reservation(frozen_risk):
    book,config,*_=frozen_risk;request=draft_request(frozen_risk)
    before=resources(book,'sample');preview=save(book,config,'sample',request)
    assert resources(book,'sample')==before and book.sequence('sample')==2
    assert preview['payload']['purpose']=='hedge_stage' and 'signal' not in preview['payload']
    line=preview['payload']['sizing']['lines'][0]
    assert line['side']=='SELL' and D(line['quantity'])==40 and D(line['price'])==100
    assert D(line['estimated_fee'])==D('2.8')
    original=save(book,config,'sample',request,commit=True)
    assert save(book,config,'sample',request,commit=True)==original
    plan=PlanService(book,config).get(original['plan_id'])
    assert plan['execution_status']=='DRAFT' and D(plan['reserved_cash'])==0 and plan['reserved_positions']=={}
    assert book.sequence('sample')==2 and book.snapshot('sample',request['as_of'])['positions']=={'SPY':'100'}
    validate_references(book)
    reviewed=execution_review(book,config,original['plan_id'],request['as_of'])
    assert reviewed['target_weights']=={} and D(reviewed['lines'][0]['remaining_quantity'])==40
    with pytest.raises(QuantError) as exc:
        PlanService(book,config).revise(original['plan_id'],None,None,None,request['as_of'])
    assert exc.value.code=='EXPLICIT_HEDGE_REVISION_REQUIRED'


@pytest.mark.parametrize('changes,code',[
    ({'parent_version':'old'},'STALE_HEDGE_INTENT_VERSION'),
    ({'expected_resource_hash':'old'},'STALE_HEDGE_RESOURCES'),
    ({'as_of':'2025-02-03T21:30:00Z'},'HEDGE_INTENT_CLOSED'),
    ({'snapshot_id':'other'},'HEDGE_PRICE_BASIS_CHANGED')])
def test_invalid_stock_draft_does_not_publish(frozen_risk,changes,code):
    book,config,*_=frozen_risk;request=draft_request(frozen_risk);before=resources(book,'sample')
    with pytest.raises(QuantError) as exc:save(book,config,'sample',dict(request,**changes),commit=True)
    assert exc.value.code==code and resources(book,'sample')==before
    assert book.connection.execute('SELECT count(*) FROM plans').fetchone()[0]==0


def test_rehashed_stock_quantity_cannot_change_frozen_parent(frozen_risk):
    book,config,*_=frozen_risk;request=draft_request(frozen_risk)
    result=save(book,config,'sample',request,commit=True)
    row=book.connection.execute('SELECT payload FROM plans WHERE plan_id=?',(result['plan_id'],)).fetchone()
    body=json.loads(row[0]);body['sizing']['lines'][0]['quantity']='39'
    from personal_quant.hedging.stock_plans import FROZEN
    body['draft_basis_hash']=digest({k:body[k] for k in FROZEN})
    book.connection.execute('UPDATE plans SET payload=? WHERE plan_id=?',(canonical(body),result['plan_id']))
    result['draft_basis_hash']=body['draft_basis_hash'];result['record_hash']=digest({k:v for k,v in result.items() if k!='record_hash'})
    book.connection.execute('UPDATE tasks SET details=? WHERE task_id LIKE ?',(canonical(result),'hedge-stock-draft:%'))
    with pytest.raises(QuantError) as exc:validate_references(book)
    assert exc.value.code=='CORRUPT_HEDGE_STOCK_PLAN'


def stock_stage(fixture, plan_id):
    from personal_quant.hedging.groups import save as group_save
    from personal_quant.hedging.archive import publish
    from personal_quant.hedging.intents import records
    book,config,store,query,_=fixture;parent_record=records(book,'sample')[0]
    group=group_save(book,'sample',dict(schema_version=1,request_id='typed-stock-group',hedge_id=parent_record['hedge_id'],
        parent_version=parent_record['version_hash'],expected_resource_hash=resources(book,'sample'),
        stages=[dict(stage_id='sale',plan_kind='stock',plan_id=plan_id,action='OPEN',depends_on=[])],reason='typed native stock'),commit=True)
    risk=publish(book,config,store,'sample',query)
    return dict(group_id=group['group_id'],expected_group_hash=group['record_hash'],
        expected_resource_hash=resources(book,'sample'),stage_id='sale',exposure_id=risk['exposure_id'],
        option_snapshot_id=None,quote_limits=dict(max_age_seconds=3600,max_underlying_skew_seconds=120,
            max_spread_fraction=.2,max_leg_skew_seconds=10,max_underlying_price_fraction=.01),
        stress=dict(scenarios=[dict(name='down',horizon_date='2025-01-15',benchmark_return=-.2,
            beta_multiplier=1,residual_returns={'SPY':0},volatility_multiplier=1)],models={},
            limits=dict(stock_cost_bps=7,option_fee_per_contract=2,adverse_slippage_fraction=0,
                cash_buffer=0,minimum_sample_equity=0,maximum_sample_loss=10000)))


def test_stock_activation_partial_facts_refresh_and_full_backup_without_strategy_signal(frozen_risk,tmp_path):
    from personal_quant.hedging.stock_activation import save as activate,validate_references as validate_activation
    from personal_quant.portfolio.reconciliation import ReconciliationRules
    from personal_quant.portfolio.backup import create_bundle,verify_bundle,restore_bundle
    from personal_quant.portfolio import Ledger
    from conftest import event
    book,config,*_=frozen_risk;draft_req=draft_request(frozen_risk)
    draft=save(book,config,'sample',draft_req,commit=True);stage=stock_stage(frozen_risk,draft['plan_id'])
    clock=draft_req['as_of']
    book.reconcile('sample',dict(account_id='sample',currency='USD',as_of=clock,cash_basis='settled',cash=20000,positions={'SPY':100},equity=30000),
                   {'SPY':100},rules=ReconciliationRules.from_config(config))
    # Reconciliation changes the resource CAS; refresh the phase request explicitly.
    stage['expected_resource_hash']=resources(book,'sample')
    req=dict(schema_version=1,request_id='stock-activate-one',plan_id=draft['plan_id'],as_of=clock,
             expected_resource_hash=resources(book,'sample'),hedge_stage_check=stage)
    before=resources(book,'sample');preview=activate(book,'sample',req)
    assert preview['status']=='PREVIEW' and resources(book,'sample')==before
    first=activate(book,'sample',req,commit=True)
    assert first['status']=='READY' and first['reserved_positions']=={'SPY':'40'} and D(first['reserved_cash'])==0
    assert activate(book,'sample',req,commit=True)==first and book.sequence('sample')==2
    service=PlanService(book,config)
    book.import_events('sample',[event('partial-sale','SELL',plan_id=draft['plan_id'],symbol='SPY',quantity=20,
        price=100,fee='1.4',effective_at='2025-01-16T21:00:00Z',settlement_at='2025-01-17T21:00:00Z')])
    plan=service.refresh(draft['plan_id'],'2025-01-16T21:00:00Z')
    assert plan['execution_status']=='PARTIAL' and plan['reserved_positions']=={'SPY':'20'}
    assert 'signal' not in plan['payload']
    book.import_events('sample',[event('final-sale','SELL',plan_id=draft['plan_id'],symbol='SPY',quantity=20,
        price=100,fee='1.4',effective_at='2025-01-16T21:00:00Z',settlement_at='2025-01-17T21:00:00Z')])
    final=service.get(draft['plan_id'])
    assert final['execution_status']=='FILLED' and final['reserved_positions']=={}
    state=book.snapshot('sample','2025-01-17T21:00:00Z',{'SPY':100})
    assert D(state['settled_cash'])==D('23997.2') and state['positions']=={'SPY':'60'}
    assert D(state['equity'])==D('29997.2')
    validate_activation(book)
    from pathlib import Path
    config_path=tmp_path/'demo.toml';config_path.write_bytes((Path(__file__).resolve().parents[1]/'configs/demo.toml').read_bytes())
    bundle=tmp_path/'typed-stock-backup';create_bundle(book.path.parent,config_path,bundle);verify_bundle(bundle,'demo')
    restore_bundle(bundle,tmp_path/'typed-stock-restored','demo')
    restored=Ledger(tmp_path/'typed-stock-restored/runtime/demo/account.sqlite','demo')
    try:validate_references(restored);validate_activation(restored)
    finally:restored.close()


def test_zero_cash_sale_can_activate_without_spending_unsettled_sale_proceeds(frozen_risk):
    from conftest import event
    from personal_quant.hedging.stock_activation import save as activate
    from personal_quant.portfolio.reconciliation import ReconciliationRules
    book,config,*_=frozen_risk
    book.import_events('sample',[event('withdraw-before-decision','WITHDRAWAL',amount=20000)])
    frozen_risk[3]['ledger_seq']=book.sequence('sample')
    request=draft_request(frozen_risk);draft=save(book,config,'sample',request,commit=True)
    assert D(draft_request_quantity(book,draft['plan_id']))==80
    book.reconcile('sample',dict(account_id='sample',currency='USD',as_of=request['as_of'],cash_basis='settled',
        cash=0,positions={'SPY':100},equity=10000),{'SPY':100},rules=ReconciliationRules.from_config(config))
    stage=stock_stage(frozen_risk,draft['plan_id'])
    req=dict(schema_version=1,request_id='zero-cash-sale',plan_id=draft['plan_id'],as_of=request['as_of'],
        expected_resource_hash=resources(book,'sample'),hedge_stage_check=stage)
    result=activate(book,'sample',req,commit=True)
    assert result['status']=='READY' and D(result['reserved_cash'])==0
    assert result['reserved_positions']=={'SPY':'80'} and book.sequence('sample')==3
    assert D(book.snapshot('sample',request['as_of'])['available_cash'])==0


def draft_request_quantity(book,plan_id):
    return json.loads(book.connection.execute('SELECT payload FROM plans WHERE plan_id=?',(plan_id,)).fetchone()[0])['sizing']['lines'][0]['quantity']


@pytest.mark.parametrize('late',[False,True])
@pytest.mark.parametrize('zero_cash',[False,True])
def test_typed_stock_plan_simulates_frozen_quantity_next_session_once(frozen_risk,late,zero_cash,monkeypatch):
    import pandas as pd
    from personal_quant.data.calendar import Calendar
    from personal_quant.hedging.archive import publish
    from personal_quant.hedging.stock_activation import save as activate
    from personal_quant.portfolio.reconciliation import ReconciliationRules
    from personal_quant.execution.simulator import simulate
    book,config,store,query,calendar=frozen_risk
    if zero_cash:
        from conftest import event
        book.import_events('sample',[event('withdraw-before-decision','WITHDRAWAL',amount=20000)])
        query['ledger_seq']=book.sequence('sample')
    initial_sequence=book.sequence('sample');cash=0 if zero_cash else 20000
    quantity=80 if zero_cash else 40;fee=D('5.6') if zero_cash else D('2.8')
    req=draft_request(frozen_risk);draft=save(book,config,'sample',req,commit=True)
    book.reconcile('sample',dict(account_id='sample',currency='USD',as_of=req['as_of'],cash_basis='settled',
        cash=cash,positions={'SPY':100},equity=10000+cash),{'SPY':100},rules=ReconciliationRules.from_config(config))
    stage=stock_stage(frozen_risk,draft['plan_id'])
    activate(book,'sample',dict(schema_version=1,request_id='simulation-activation',plan_id=draft['plan_id'],
        as_of=req['as_of'],expected_resource_hash=resources(book,'sample'),hedge_stage_check=stage),commit=True)
    frame,_,_=store.load(req['snapshot_id'])
    future=frame.loc[frame.session_date==calendar.sessions[-1]].copy()
    future['session_date']=pd.Timestamp('2025-01-16')
    processing='2025-01-20T21:30:00Z' if late else '2025-01-16T21:30:00Z'
    future['available_at']=pd.Timestamp(processing)
    frame=pd.concat([frame,future],ignore_index=True)
    if late:
        later=future.copy();later['session_date']=pd.Timestamp('2025-01-17');later['available_at']=pd.Timestamp('2025-01-17T21:30:00Z')
        for column in ('open','high','low','close','adj_close'):later.loc[later.symbol=='SPY',column]=200
        frame=pd.concat([frame,later],ignore_index=True)
    schedule=pd.concat([calendar.schedule,pd.DataFrame({'close_time':[pd.Timestamp('2025-01-16T21:00:00Z'),
        pd.Timestamp('2025-01-17T21:00:00Z')]},index=pd.to_datetime(['2025-01-16','2025-01-17']))])
    calendar=Calendar(schedule,calendar.kind);metadata=store.save(frame,calendar)
    clock='2025-01-16T21:00:00Z' if late else processing
    exposure_request=dict(query,as_of=clock,knowledge_cutoff=processing,
        valuation_snapshot_id=metadata['snapshot_id'],return_snapshot_id=metadata['snapshot_id'])
    if late:exposure_request['execution_replay']=dict(plan_kind='stock',plan_id=draft['plan_id'],execution_at=clock,processing_at=processing)
    if late:
        changed=calendar.schedule.copy();changed.loc[pd.Timestamp('2025-01-16'),'close_time']=pd.Timestamp('2025-01-16T22:00:00Z')
        bad_calendar=Calendar(changed,calendar.kind);bad=store.save(frame,bad_calendar)
        bad_request=dict(exposure_request,valuation_snapshot_id=bad['snapshot_id'],return_snapshot_id=bad['snapshot_id'])
        with pytest.raises(QuantError) as exc:publish(book,config,store,'sample',bad_request)
        assert exc.value.code=='HEDGE_REPLAY_CALENDAR_MISMATCH'
    risk=publish(book,config,store,'sample',exposure_request)
    if late:
        from personal_quant.hedging.archive import load
        original=load(book.path.parent/'hedging/exposures',risk['exposure_id'])
        assert original['purpose']=='frozen_execution_replay' and original['valuation']['prices']['SPY']==100
        assert original['as_of']==clock.replace('Z','+00:00') and original['knowledge_cutoff']==processing.replace('Z','+00:00')
    fresh=dict(stage,exposure_id=risk['exposure_id'],expected_resource_hash=resources(book,'sample'))
    fresh['stress']=dict(stage['stress'],scenarios=[dict(stage['stress']['scenarios'][0],horizon_date='2025-01-16')])
    service=PlanService(book,config)
    if late:
        before=resources(book,'sample')
        with pytest.raises(QuantError) as exc:simulate(service,draft['plan_id'],frame,calendar,processing,hedge_stage_check=fresh)
        assert exc.value.code=='HEDGE_REPLAY_STATE_REQUIRED' and resources(book,'sample')==before
        original_record=book.record_task
        def fail_audit(task_id,*args):
            if task_id.startswith('hedge-stock-simulation:'):raise QuantError('INJECTED_FAILURE','audit failed before commit')
            return original_record(task_id,*args)
        monkeypatch.setattr(book,'record_task',fail_audit)
        with pytest.raises(QuantError) as exc:
            simulate(service,draft['plan_id'],frame,calendar,processing,state_as_of=clock,hedge_stage_check=fresh)
        assert exc.value.code=='INJECTED_FAILURE' and book.sequence('sample')==initial_sequence and resources(book,'sample')==before
        monkeypatch.setattr(book,'record_task',original_record)
    result=simulate(service,draft['plan_id'],frame,calendar,processing,state_as_of=clock if late else None,hedge_stage_check=fresh)
    assert result['status']=='SUCCESS' and result['execution_status']=='FILLED'
    assert result['late_processing'] is late
    from personal_quant.hedging.stock_simulation_audit import validate_references as validate_simulation
    validate_simulation(book)
    assert book.connection.execute("SELECT count(*) FROM tasks WHERE task_id LIKE 'hedge-stock-simulation:%'").fetchone()[0]==1
    assert result['execution_session']=='2025-01-16' and book.sequence('sample')==initial_sequence+1
    state=book.snapshot('sample',clock,{'SPY':100})
    assert state['positions']=={'SPY':str(100-quantity)} and D(state['receivables'])==quantity*100-fee
    assert D(state['settled_cash'])==cash and D(state['equity'])==10000+cash-fee
    assert simulate(service,draft['plan_id'],frame,calendar,processing,state_as_of=clock if late else None,hedge_stage_check=fresh)['status']=='NO_ACTION'
    assert book.sequence('sample')==initial_sequence+1
    # Matching rehashed receipt/audit edits still cannot change frozen quantities or fees.
    task=book.connection.execute("SELECT task_id,details FROM tasks WHERE task_id LIKE 'hedge-stock-simulation:%'").fetchone()
    audit=json.loads(task['details']);field='quantity' if zero_cash else 'fee'
    audit['events'][0][field]=str(D(audit['events'][0][field])+1)
    audit['record_hash']=digest({k:v for k,v in audit.items() if k!='record_hash'})
    raw=book.connection.execute('SELECT payload FROM events WHERE event_id=?',(audit['events'][0]['event_id'],)).fetchone()
    fact=json.loads(raw['payload']);fact[field]=audit['events'][0][field]
    book.connection.execute('UPDATE events SET payload=?,content_hash=? WHERE event_id=?',(canonical(fact),digest(fact),fact['event_id']))
    book.connection.execute('UPDATE tasks SET details=? WHERE task_id=?',(canonical(audit),task['task_id']))
    with pytest.raises(QuantError) as exc:validate_simulation(book)
    assert exc.value.code=='CORRUPT_HEDGE_STOCK_SIMULATION'
    from personal_quant.hedging.monitor import monitor
    blocked=monitor(book,'sample',processing)
    assert blocked['status']=='BLOCKED' and blocked['checks'][0]['code']=='CORRUPT_HEDGE_STOCK_SIMULATION'


def test_late_risk_without_frozen_plan_cannot_change_normal_decision_clock(frozen_risk):
    from personal_quant.hedging.archive import publish
    book,config,store,query,_=frozen_risk
    late_query=dict(query,knowledge_cutoff='2025-01-20T21:30:00Z')
    with pytest.raises(QuantError) as exc:publish(book,config,store,'sample',late_query)
    assert exc.value.code=='INVALID_EXPOSURE_TIME'
    request=draft_request(frozen_risk);draft=save(book,config,'sample',request,commit=True)
    late_query.update(as_of='2025-01-16T21:00:00Z',execution_replay=dict(plan_kind='stock',plan_id=draft['plan_id'],
        execution_at='2025-01-16T21:00:00Z',processing_at='2025-01-20T21:30:00Z'))
    with pytest.raises(QuantError) as exc:publish(book,config,store,'sample',late_query)
    assert exc.value.code=='UNFROZEN_HEDGE_EXECUTION' and book.sequence('sample')==2


def test_legacy_stock_activation_archive_remains_valid_after_explicit_v19_migration(frozen_risk,tmp_path):
    from pathlib import Path
    from personal_quant.portfolio.upgrade import enable_v19
    from personal_quant.hedging.stock_activation import save as activate,validate_references as validate_activations
    from personal_quant.portfolio.reconciliation import ReconciliationRules
    from personal_quant.hedging.archive import load
    book,config,*_=frozen_risk;request=draft_request(frozen_risk);draft=save(book,config,'sample',request,commit=True)
    book.reconcile('sample',dict(account_id='sample',currency='USD',as_of=request['as_of'],cash_basis='settled',
        cash=20000,positions={'SPY':100},equity=30000),{'SPY':100},rules=ReconciliationRules.from_config(config))
    phase=stock_stage(frozen_risk,draft['plan_id'])
    activation=activate(book,'sample',dict(schema_version=1,request_id='legacy-activation',plan_id=draft['plan_id'],
        as_of=request['as_of'],expected_resource_hash=resources(book,'sample'),hedge_stage_check=phase),commit=True)
    original=load(book.path.parent/'hedging/exposures',phase['exposure_id'])
    assert 'option_positions' not in original['account']
    config_path=tmp_path/'demo.toml';config_path.write_bytes((Path(__file__).resolve().parents[1]/'configs/demo.toml').read_bytes())
    assert enable_v19(book,config_path)['schema_version']==5
    validate_activations(book)
    assert activate(book,'sample',activation['request'],commit=True)==activation and book.sequence('sample')==2
    assert book.snapshot('sample',request['as_of'])['option_positions']=={}
    assert load(book.path.parent/'hedging/exposures',phase['exposure_id'])==original


@pytest.mark.parametrize('exit_session',['2025-01-21','2025-02-03'])
def test_frozen_stock_close_waits_for_open_settlement_then_reverses_once(frozen_risk,tmp_path,exit_session):
    import pandas as pd
    from copy import deepcopy
    from personal_quant.data.calendar import Calendar
    from personal_quant.hedging.archive import publish
    from personal_quant.hedging.intents import records
    from personal_quant.hedging.groups import save as bind,progress
    from personal_quant.hedging.stock_activation import save as activate,validate_references as check_activation
    from personal_quant.execution.simulator import simulate
    from personal_quant.portfolio.reconciliation import ReconciliationRules
    book,config,store,query,calendar=frozen_risk
    request=draft_request(frozen_risk);opening=save(book,config,'sample',request,commit=True)
    exit_request=dict(request,request_id='close-draft',reason='Explicit reverse after funding settlement',
        expected_resource_hash=resources(book,'sample'),exit=dict(opening_plan_id=opening['plan_id'],execution_session=exit_session))
    closing=save(book,config,'sample',exit_request,commit=True)
    assert closing['plan_id']!=opening['plan_id'] and book.sequence('sample')==2
    assert save(book,config,'sample',exit_request,commit=True)==closing
    closed_body=PlanService(book,config).get(closing['plan_id'])['payload']
    assert closed_body['sizing']['lines'][0]['side']=='BUY' and D(closed_body['sizing']['lines'][0]['quantity'])==40
    assert 'signal' not in closed_body and closed_body['hedge_context']['action']=='CLOSE'
    with pytest.raises(QuantError) as exc:save(book,config,'sample',dict(exit_request,request_id='second-exit',expected_resource_hash=resources(book,'sample')),commit=True)
    assert exc.value.code=='DUPLICATE_HEDGE_STOCK_EXIT'
    parent_record=records(book,'sample')[0]
    group=bind(book,'sample',dict(schema_version=1,request_id='open-close-group',hedge_id=parent_record['hedge_id'],
        parent_version=parent_record['version_hash'],expected_resource_hash=resources(book,'sample'),
        stages=[dict(stage_id='sale',plan_kind='stock',plan_id=opening['plan_id'],action='OPEN',depends_on=[]),
                dict(stage_id='restore',plan_kind='stock',plan_id=closing['plan_id'],action='CLOSE',depends_on=['sale'])],reason='Frozen native round trip'),commit=True)
    frame,_,_=store.load(request['snapshot_id']);last=frame.loc[frame.session_date==calendar.sessions[-1]]
    future_calendar=Calendar.market('2025-01-16',str((pd.Timestamp(exit_session)+pd.Timedelta(days=3)).date()))
    extra=[]
    for day in future_calendar.sessions:
        rows=last.copy();rows['session_date']=day;rows['available_at']=future_calendar.close(day)+pd.Timedelta(minutes=30);extra.append(rows)
    frame=pd.concat([frame,*extra],ignore_index=True)
    calendar=Calendar(pd.concat([calendar.schedule,future_calendar.schedule]),calendar.kind)
    snapshot=store.save(frame,calendar)['snapshot_id']
    query.update(valuation_snapshot_id=snapshot,return_snapshot_id=snapshot)
    def phase(stage_id,clock):
        risk=publish(book,config,store,'sample',dict(query,ledger_seq=book.sequence('sample'),as_of=clock,knowledge_cutoff=clock))
        return dict(group_id=group['group_id'],expected_group_hash=group['record_hash'],expected_resource_hash=resources(book,'sample'),
            stage_id=stage_id,exposure_id=risk['exposure_id'],option_snapshot_id=None,
            quote_limits=dict(max_age_seconds=3600,max_underlying_skew_seconds=120,max_spread_fraction=.2,max_leg_skew_seconds=10,max_underlying_price_fraction=.01),
            stress=dict(scenarios=[dict(name='down',horizon_date=clock[:10],benchmark_return=-.2,beta_multiplier=1,residual_returns={'SPY':0},volatility_multiplier=1)],models={},
                limits=dict(stock_cost_bps=7,option_fee_per_contract=2,adverse_slippage_fraction=0,cash_buffer=0,minimum_sample_equity=0,maximum_sample_loss=10000)))
    book.reconcile('sample',dict(account_id='sample',currency='USD',as_of=request['as_of'],cash_basis='settled',cash=20000,positions={'SPY':100},equity=30000),{'SPY':100},rules=ReconciliationRules.from_config(config))
    def activation(plan_id,name,clock):
        return dict(schema_version=1,request_id=name,plan_id=plan_id,as_of=clock,expected_resource_hash=resources(book,'sample'),hedge_stage_check=phase('sale' if plan_id==opening['plan_id'] else 'restore',clock))
    early=activation(closing['plan_id'],'early-close',request['as_of'])
    with pytest.raises(QuantError) as exc:activate(book,'sample',early,commit=True)
    assert exc.value.code=='UNRESOLVED_HEDGE_EXECUTION' and book.sequence('sample')==2
    activate(book,'sample',activation(opening['plan_id'],'open',request['as_of']),commit=True)
    service=PlanService(book,config)
    assert simulate(service,opening['plan_id'],frame,calendar,'2025-01-16T21:30:00Z',hedge_stage_check=phase('sale','2025-01-16T21:30:00Z'))['status']=='SUCCESS'
    unsettled=activation(closing['plan_id'],'unsettled-close','2025-01-16T21:30:00Z')
    with pytest.raises(QuantError) as exc:activate(book,'sample',unsettled,commit=True)
    assert exc.value.code=='UNRESOLVED_HEDGE_EXECUTION'
    ready=activation(closing['plan_id'],'settled-close','2025-01-17T21:30:00Z')
    assert activate(book,'sample',ready,commit=True)['status']=='READY'
    check_activation(book)
    assert service.get(closing['plan_id'])['payload']['execution_basis_sequence']==3
    if exit_session=='2025-02-03':
        book.reconcile('sample',dict(account_id='sample',currency='USD',as_of='2025-01-31T21:30:00Z',cash_basis='settled',
            cash='23997.2',positions={'SPY':60},equity='29997.2'),{'SPY':100},rules=ReconciliationRules.from_config(config))
    processing=exit_session+'T21:30:00Z';finished=(calendar.close(calendar.next(exit_session))+pd.Timedelta(minutes=30)).isoformat()
    result=simulate(service,closing['plan_id'],frame,calendar,processing,hedge_stage_check=phase('restore',processing))
    assert result['status']=='SUCCESS' and result['execution_status']=='FILLED'
    assert simulate(service,closing['plan_id'],frame,calendar,processing)['status']=='NO_ACTION'
    state=book.snapshot('sample',finished,{'SPY':100})
    assert book.sequence('sample')==4 and state['positions']=={'SPY':'100'}
    assert D(state['settled_cash'])==D('19994.4') and D(state['equity'])==D('29994.4')
    assert progress(book,'sample',group,finished)['status']=='COMPLETE'
    from pathlib import Path
    from personal_quant.portfolio.backup import create_bundle,verify_bundle,restore_bundle
    from personal_quant.portfolio import Ledger
    cfg=tmp_path/'close-demo.toml';cfg.write_bytes((Path(__file__).resolve().parents[1]/'configs/demo.toml').read_bytes())
    bundle=tmp_path/'close-backup';create_bundle(book.path.parent,cfg,bundle);verify_bundle(bundle,'demo')
    restored_root=tmp_path/'close-restored';restore_bundle(bundle,restored_root,'demo')
    restored=Ledger(restored_root/'runtime/demo/account.sqlite','demo')
    try:
        validate_references(restored);check_activation(restored)
        from personal_quant.hedging.stock_simulation_audit import validate_references as check_simulations
        check_simulations(restored)
        assert restored.snapshot('sample',finished,{'SPY':100})['positions']=={'SPY':'100'}
    finally:restored.close()
