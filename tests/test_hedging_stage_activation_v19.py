from native_tools import native_engine_root,native_dotnet
"""A real native-format monthly plan reaches activation with a frozen hedge parent."""
import pandas as pd
import pytest
from personal_quant.common import decimal as D,now_utc
from personal_quant.data.store import DataStore
from personal_quant.hedging.archive import publish
from personal_quant.hedging.intents import save as parent_save
from personal_quant.hedging.groups import save as group_save
from personal_quant.hedging.allocation_store import resources
from personal_quant.hedging.securities import register
from personal_quant.options.activation import activate
from test_options_activation_v19 import setup,engine_evidence
from test_hedging_exposure_v19 import risk_market
from test_hedging_securities_v19 import identity
from test_hedging_sizing_v19 import policy


@pytest.mark.parametrize('late',[False,True])
def test_bound_monthly_protective_put_activates_with_current_stage_pressure(ledger,config,risk_market,monkeypatch,late,engine_evidence):
    # Generate qualified native evidence when no archive was supplied.
    evidence=engine_evidence
    book=ledger;store,plan,activation=setup(book,book.path.parent/'options',evidence,cash=100000,packages=1,template='protective_put',shares=100)
    _,frame,_,calendar=risk_market;frame=frame.copy()
    day=pd.Timestamp('2024-10-31');scale=100/frame.loc[(frame.symbol=='SPY')&(frame.session_date==day),'close'].iloc[0]
    for field in ('open','high','low','close','adj_close'):frame.loc[frame.symbol=='SPY',field]*=scale
    data=DataStore(book.path.parent/'data');snapshot=data.save(frame,calendar)['snapshot_id']
    monthly=activation['monthly_signal'];selection=monthly['input']['request'];clock=monthly['decision_at']
    query=dict(schema_version=1,as_of=clock,knowledge_cutoff=clock,ledger_seq=2,ledger_view='restated',
        valuation_snapshot_id=snapshot,return_snapshot_id=snapshot,benchmark='GLD',window=60,min_r2=.9,
        max_standard_error=.1,max_mark_skew_seconds=86400,max_greek_age_seconds=3600,greeks=[],option_valuation=None)
    risk=publish(book,config,data,'sample',query)
    security=register(book.path.parent,'demo',identity())
    spec=policy(scope=['SPY'],benchmark='GLD',mode='share_protection',target_beta=None,protection_fraction=1,
                tools=['protective_put'],max_days_to_expiry=80)
    option=dict(snapshot_id=monthly['input']['snapshot_id'],selection_request=selection,
        coverage_request=dict(schema_version=1,as_of=clock,knowledge_cutoff=now_utc(),ledger_seq=2,ledger_view='restated',
            security_ids={'SPY':'security-us-spy'},allocations=[],inflight_plan_ids=[]),greeks=[],funding_quote=None,
        limits=dict(adverse_slippage_fraction=0,early_assignment_cash_reserve=0,max_greek_age_seconds=3600,
            max_mark_skew_seconds=86400,proxy_exit_policy='sell_before_expiry',failed_exit_policy='block_and_require_verified_resolution'))
    parent=parent_save(book,'sample',dict(schema_version=1,request_id='native-stage-parent',expected_version=None,
        expected_resource_hash=resources(book,'sample'),preview_request=dict(exposure_id=risk['exposure_id'],spec=spec,method='protective_put',option=option),
        security_ids={'SPY':'security-us-spy'},security_versions={'SPY':security['record']['version_hash']},decision_at=clock,
        knowledge_cutoff=now_utc(),valid_until='2024-11-05T21:00:00Z',trigger='synthetic_monthly',
        base_strategy_version='MANUAL_HOLDINGS',timing='historical_research',reason='Synthetic native monthly integration'),commit=True)
    assert parent['candidate']['planned_total_packages']=='1'
    from personal_quant.hedging.native_plans import save as native_save
    book.connection.execute('DELETE FROM option_plans WHERE plan_id=?',(plan['plan_id'],))
    generation=dict(schema_version=1,request_id='native-generation',hedge_id=parent['hedge_id'],
        parent_version=parent['version_hash'],expected_resource_hash=resources(book,'sample'),as_of=activation['as_of'],
        option_risk=plan['request']['risk'],stock_stages=[],include_option_close=True,reason='Native monthly draft generation')
    preview=native_save(book,'sample',generation)
    assert preview['status']=='PREVIEW' and book.connection.execute('SELECT count(*) FROM option_plans').fetchone()[0]==0
    generated=native_save(book,'sample',generation,commit=True)
    assert generated['option_plan_id']==plan['plan_id'] and not generated['creates_reservations']
    assert native_save(book,'sample',generation,commit=True)==generated
    group=generated['group']
    current=publish(book,config,data,'sample',{**query,'as_of':activation['as_of'],'knowledge_cutoff':activation['as_of']})
    terms=plan['selection']['legs'][0]['contract_version']
    check=dict(group_id=group['group_id'],expected_group_hash=group['record_hash'],expected_resource_hash=resources(book,'sample'),
        stage_id='option-open',exposure_id=current['exposure_id'],option_snapshot_id=activation['quote_snapshot_id'],
        quote_limits=dict(max_age_seconds=900,max_underlying_skew_seconds=120,max_spread_fraction=.25,
                          max_leg_skew_seconds=10,max_underlying_price_fraction=.01),
        stress=dict(scenarios=[dict(name='down',horizon_date='2024-12-18',benchmark_return=-.2,beta_multiplier=1,
            residual_returns={'SPY':0},volatility_multiplier=1)],models={terms:dict(volatility=.2,rate=0,dividend_yield=0)},
            limits=dict(stock_cost_bps=0,option_fee_per_contract=2,adverse_slippage_fraction=0,
                        cash_buffer=0,minimum_sample_equity=0,maximum_sample_loss=100000)))
    audit=activate(book,store,{**activation,'hedge_stage_check':check})
    assert audit['status']=='ACTIVATED' and audit['hedge_stage_check']['status']=='CHECKED'
    assert D(audit['result']['active_reservation']['reserved_cash'])==122
    assert book.sequence('sample')==2
    assert activate(book,store,{**activation,'hedge_stage_check':check})==audit
    from personal_quant.hedging.stage_gate import validate_record
    validate_record(book,'sample',plan['plan_id'],'OPEN',check,audit['hedge_stage_check'])
    if late:
        import pytest
        from personal_quant.common import QuantError
        from personal_quant.options.monthly_report import monthly_compare
        from personal_quant.options.simulation import execute
        from test_options_simulation_v19 import closing_quotes
        from test_options_monthly_replay_v19 import ROOT
        import json
        signals=sorted((json.loads(p.read_text()) for p in (book.path.parent/'options/monthly').glob('*.json')),key=lambda s:s['decision_at'])
        monthly_compare(native_engine_root(),native_dotnet(),book.path.parent/'options/monthly-research/late-bound',signals,
            initial_cash=100000,fee_per_contract=2,stock_commission_bps=2)
        closing=closing_quotes(store,activation)
        contracts,rows,metadata,_=store.load(closing)
        for row in rows:
            if row['contract_id'] in {l['contract']['contract_id'] for l in plan['selection']['legs']}:
                row.update(available_at='2024-11-04T21:00:00Z',received_at='2024-11-04T21:00:00Z')
        closing=store.save(list(contracts.values()),pd.DataFrame(rows),metadata)['snapshot_id']
        processing='2024-11-04T21:30:00Z';execution=activation['valid_until']
        replay=dict(plan_kind='option',plan_id=plan['plan_id'],execution_at=execution,processing_at=processing)
        frozen=publish(book,config,data,'sample',dict(query,as_of=execution,knowledge_cutoff=processing,execution_replay=replay))
        fresh={**check,'exposure_id':frozen['exposure_id'],'option_snapshot_id':closing,'expected_resource_hash':resources(book,'sample')}
        book.reconcile('sample',dict(account_id='sample',currency='USD',as_of=processing,cash_basis='settled',
            cash=90000,positions={'SPY':100},equity=100000),{'SPY':100})
        request=dict(plan_id=plan['plan_id'],report_id='late-bound',execution_snapshot_id=closing,
            as_of=processing,expected_sequence=2,state_as_of=execution,hedge_stage_check=fresh)
        before=resources(book,'sample')
        missing={k:v for k,v in request.items() if k!='state_as_of'}
        with pytest.raises(QuantError) as exc:execute(book,store,missing)
        assert exc.value.code=='HEDGE_REPLAY_STATE_REQUIRED' and resources(book,'sample')==before
        with pytest.raises(QuantError) as exc:execute(book,store,dict(request,state_as_of='2024-11-01T20:01:00Z'))
        assert exc.value.code=='INVALID_SIMULATION_STATE_TIME' and book.sequence('sample')==2
        original_record=book.record_task
        def fail_audit(task_id,*args):
            if task_id.startswith('option-simulation:'):raise QuantError('INJECTED_FAILURE','option audit failed')
            return original_record(task_id,*args)
        monkeypatch.setattr(book,'record_task',fail_audit)
        with pytest.raises(QuantError) as exc:execute(book,store,request)
        assert exc.value.code=='INJECTED_FAILURE' and resources(book,'sample')==before and book.sequence('sample')==2
        monkeypatch.setattr(book,'record_task',original_record)
        result=execute(book,store,request)
        assert result['status']=='SIMULATED' and result['delayed_processing'] and result['result']['status']=='FILLED'
        assert execute(book,store,request)==result and book.sequence('sample')==3
        assert D(result['account']['equity'])==99993 and result['account']['positions']=={'SPY':'100'}
        assert result['rows'][0]['effective_at']==execution.replace('Z','+00:00')
        assert result['hedge_stage_check']['processing_as_of']==processing.replace('Z','+00:00')
        # The original group also owns a frozen CLOSE; delayed receipt never
        # changes its execution day or sells the existing account stock.
        from personal_quant.options.exit_tasks import preview_freeze,freeze_exit,execute_exit
        from test_options_exit_tasks_v19 import exit_quote
        frame=frame.copy()
        mask=(frame.symbol=='SPY')&(frame.session_date>=pd.Timestamp('2024-11-29'))
        for field in ('open','high','low','close','adj_close'):frame.loc[mask,field]=100
        revised=data.save(frame,calendar)['snapshot_id']
        reference=exit_quote(store,activation,'2024-12-02T20:34:00Z')
        symbol=plan['selection']['legs'][0]['contract']['contract_id']
        def close_query(at,known,snapshot,**extra):
            greek=dict(contract_version=terms,unit='per_share',value=-.5,signed_contracts=1,
                source='explicit_test',data_type='synthetic',as_of=at,available_at=at,received_at=known,model_inputs={})
            return dict(query,as_of=at,knowledge_cutoff=known,ledger_seq=3,min_r2=0,max_standard_error=100,
                valuation_snapshot_id=revised,return_snapshot_id=revised,max_mark_skew_seconds=400000,
                greeks=[greek],option_valuation=dict(snapshot_id=snapshot,limits=dict(max_age_seconds=900,
                    max_underlying_skew_seconds=120,max_spread_fraction=.25,max_leg_skew_seconds=10)),**extra)
        before_close='2024-12-02T20:35:00Z';close_at='2024-12-02T21:00:00Z';received='2024-12-05T21:30:00Z'
        marks={'SPY':100,symbol:'1.05'}
        book.reconcile('sample',dict(account_id='sample',currency='USD',as_of='2024-12-02T20:33:00Z',
            cash_basis='settled',cash=89888,positions={'SPY':100},option_positions={symbol:1},equity=99993),marks)
        before_risk=publish(book,config,data,'sample',close_query(before_close,before_close,reference))
        closing_check=dict(check,stage_id='option-close',exposure_id=before_risk['exposure_id'],
            option_snapshot_id=reference,expected_resource_hash=resources(book,'sample'))
        review_request=dict(plan_id=plan['plan_id'],as_of=before_close,snapshot_id=reference,trigger='RISK_REDUCTION',
            exit_days=7,fee_per_contract=2,max_age_seconds=900,max_underlying_skew_seconds=120,
            max_spread_fraction=.25,max_leg_skew_seconds=10,max_underlying_price_fraction=.01,reconciliation_max_days=1)
        frozen_request=dict(request_id='bound-close',review=review_request,execution_at=close_at,
            purpose='PROTECTION_WITHDRAWAL',expected_sequence=3,hedge_stage_check=closing_check)
        preview=preview_freeze(book,store,frozen_request)
        assert preview['status']=='CHECKED',preview['checks']
        exit_record=freeze_exit(book,store,frozen_request,expected_hash=preview['preview_hash'])
        closing_quotes_id=exit_quote(store,activation,close_at)
        contracts,rows,metadata,_=store.load(closing_quotes_id)
        for row in rows:
            if row['contract_id']==symbol:row.update(available_at=received,received_at=received)
        closing_quotes_id=store.save(list(contracts.values()),pd.DataFrame(rows),metadata)['snapshot_id']
        replay=dict(plan_kind='option',plan_id=plan['plan_id'],exit_id=preview['exit_id'],execution_at=close_at,processing_at=received)
        from copy import deepcopy
        from personal_quant.common import canonical,digest,utc
        from personal_quant.hedging.execution_replay import validate as replay_clock
        class RollbackClock(Exception):pass
        with pytest.raises(RollbackClock):
            with book.transaction():
                damaged_exit=deepcopy(exit_record);proposal=damaged_exit['proposal']
                damaged_exit['request']['review']['as_of']='2024-12-02T20:36:00Z'
                damaged_exit['request_hash']=digest(damaged_exit['request'])
                proposal.update(as_of='2024-12-02T20:36:00Z',request=damaged_exit['request'],request_hash=damaged_exit['request_hash'])
                proposal['preview_hash']=digest({k:v for k,v in proposal.items() if k!='preview_hash'})
                book.connection.execute('UPDATE tasks SET details=? WHERE task_id=?',
                    (canonical(damaged_exit),'option-exit-freeze:'+preview['exit_id']))
                with pytest.raises(QuantError) as exc:replay_clock(book,'sample',replay,utc(close_at),utc(received))
                assert exc.value.code=='CORRUPT_HEDGE_STAGE_AUDIT' and book.sequence('sample')==3
                raise RollbackClock()
        close_risk=publish(book,config,data,'sample',close_query(close_at,received,closing_quotes_id,execution_replay=replay))
        fresh_close=dict(closing_check,exposure_id=close_risk['exposure_id'],option_snapshot_id=closing_quotes_id,
            expected_resource_hash=resources(book,'sample'))
        book.reconcile('sample',dict(account_id='sample',currency='USD',as_of=received,cash_basis='settled',
            cash=89888,positions={'SPY':100},option_positions={symbol:1},equity=99993),marks)
        exit_request=dict(exit_id=preview['exit_id'],report_id='late-bound',execution_snapshot_id=closing_quotes_id,
            as_of=received,expected_sequence=3,state_as_of=close_at,hedge_stage_check=fresh_close)
        before=resources(book,'sample')
        with pytest.raises(QuantError) as exc:execute_exit(book,store,{k:v for k,v in exit_request.items() if k!='state_as_of'})
        assert exc.value.code=='HEDGE_REPLAY_STATE_REQUIRED' and resources(book,'sample')==before
        with pytest.raises(QuantError) as exc:execute_exit(book,store,dict(exit_request,state_as_of='2024-12-02T21:01:00Z'))
        assert exc.value.code=='INVALID_SIMULATION_STATE_TIME' and book.sequence('sample')==3
        def fail_exit_audit(task_id,*args):
            if task_id.startswith('option-exit-simulation:'):raise QuantError('INJECTED_FAILURE','exit audit failed')
            return original_record(task_id,*args)
        monkeypatch.setattr(book,'record_task',fail_exit_audit)
        with pytest.raises(QuantError) as exc:execute_exit(book,store,exit_request)
        assert exc.value.code=='INJECTED_FAILURE' and resources(book,'sample')==before and book.sequence('sample')==3
        monkeypatch.setattr(book,'record_task',original_record)
        exited=execute_exit(book,store,exit_request)
        assert execute_exit(book,store,exit_request)==exited and book.sequence('sample')==4
        assert exited['result']['lifecycle']['position_status']=='CLOSED'
        assert exited['account']['positions']=={'SPY':'100'} and exited['account']['option_positions']=={}
        assert D(exited['account']['equity'])==99986 and D(exited['account']['settled_cash'])==89986
        assert exited['rows'][0]['effective_at']==close_at.replace('Z','+00:00')
        assert exited['hedge_stage_check']['processing_as_of']==received.replace('Z','+00:00')
        from personal_quant.hedging.stage_gate import validate_cached
        for field,value in [('as_of','2024-12-05T21:31:00Z'),('exit_id','another-frozen-exit')]:
            damaged_simulation=deepcopy(exited);damaged_simulation['request'][field]=value
            damaged_simulation['request_hash']=digest(damaged_simulation['request'])
            with pytest.raises(QuantError) as exc:validate_cached(book,damaged_simulation,'CLOSE')
            assert exc.value.code=='CORRUPT_HEDGE_STAGE_AUDIT' and book.sequence('sample')==4
    from personal_quant.portfolio.backup import create_bundle,verify_bundle,restore_bundle
    from pathlib import Path
    cfg=book.path.parent/'demo.toml';cfg.write_bytes((Path(__file__).resolve().parents[1]/'configs/demo.toml').read_bytes())
    # Runtime root is this fixture directory; provide the documented runtime layout in an isolated copy.
    import shutil
    copied=book.path.parent/'bundle-workspace';runtime=copied/'runtime/demo'
    runtime.parent.mkdir(parents=True)
    shutil.copytree(book.path.parent,runtime,ignore=shutil.ignore_patterns('bundle-workspace'))
    import sqlite3
    with sqlite3.connect(runtime/'account.sqlite') as copied_database:book.connection.backup(copied_database)
    monkeypatch.chdir(copied)
    create_bundle(runtime,cfg,book.path.parent/'bundle');verify_bundle(book.path.parent/'bundle','demo')
    restore_bundle(book.path.parent/'bundle',book.path.parent/'restored','demo')
    from copy import deepcopy
    import json
    import pytest
    from personal_quant.common import QuantError,canonical,digest
    damaged=deepcopy(audit)
    damaged['hedge_stage_check']['vertices'][1]['friction']='0'
    damaged['hedge_stage_check']['assessment_id']=digest({k:v for k,v in damaged['hedge_stage_check'].items() if k!='assessment_id'})
    task='option-activation:'+digest({'plan_id':plan['plan_id'],'request_id':activation['request_id']})
    book.connection.execute('UPDATE tasks SET details=? WHERE task_id=?',(canonical(damaged),task))
    with pytest.raises(QuantError) as exc:activate(book,store,{**activation,'hedge_stage_check':check})
    assert exc.value.code=='CORRUPT_HEDGE_STAGE_AUDIT' and book.sequence('sample')==(4 if late else 2)
