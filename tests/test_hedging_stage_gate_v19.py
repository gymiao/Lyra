from datetime import timedelta
import pytest
from personal_quant.common import QuantError
from personal_quant.hedging.stage_gate import require_for_plan
from personal_quant.hedging.stage_assessment import analyze
from personal_quant.hedging.monitor import require_planning
from personal_quant.options.activation import activate
from personal_quant.options.simulation import execute
from personal_quant.options.data import OptionDataStore
from personal_quant.execution.simulator import simulate
from personal_quant.execution.plans import PlanService
from test_hedging_stage_assessment_v19 import setup,option_stage_request
from test_hedging_group_option_revisions_v19 import option_partial
from test_hedging_archive_v19 import frozen_risk
from test_hedging_exposure_v19 import risk_market


def test_bound_stock_gate_is_mandatory_fresh_and_exact(frozen_risk):
    book,request=setup(frozen_risk);clock='2025-01-15T21:30:00Z'
    with pytest.raises(QuantError) as exc:require_for_plan(book,'sample','stock','native-sale','OPEN',clock)
    assert exc.value.code=='HEDGE_STAGE_CHECK_REQUIRED'
    result=require_for_plan(book,'sample','stock','native-sale','OPEN',clock,request)
    assert result['status']=='CHECKED'
    with pytest.raises(QuantError) as exc:require_for_plan(book,'sample','stock','native-sale','OPEN','2025-01-16T21:30:00Z',request)
    assert exc.value.code=='HEDGE_STAGE_TIME_MISMATCH'
    with pytest.raises(QuantError) as exc:require_for_plan(book,'sample','stock','native-sale','OPEN',clock,{**request,'stage_id':'other'})
    assert exc.value.code=='HEDGE_STAGE_PLAN_MISMATCH'
    bad={**request,'stress':{**request['stress'],'limits':{**request['stress']['limits'],'maximum_sample_loss':0}}}
    with pytest.raises(QuantError) as exc:require_for_plan(book,'sample','stock','native-sale','OPEN',clock,bad)
    assert exc.value.code=='HEDGE_STAGE_BLOCKED'


def test_stock_simulator_requires_bound_check_before_financial_changes(frozen_risk):
    book,request=setup(frozen_risk);_,config,store,_,calendar=frozen_risk
    before=book.sequence('sample')
    service=PlanService(book,config)
    with pytest.raises(QuantError) as exc:simulate(service,'native-sale',None,calendar,'2025-01-15T21:30:00Z')
    assert exc.value.code=='HEDGE_STAGE_CHECK_REQUIRED' and book.sequence('sample')==before


def test_unbound_native_path_remains_unbound_and_cannot_claim_another_stage(frozen_risk):
    book,request=setup(frozen_risk)
    assert require_for_plan(book,'sample','stock','unbound','OPEN','2025-01-15T21:30:00Z')['status']=='UNBOUND_NATIVE_PLAN'
    with pytest.raises(QuantError) as exc:require_for_plan(book,'sample','stock','unbound','OPEN','2025-01-15T21:30:00Z',request)
    assert exc.value.code=='UNBOUND_STAGE_CHECK'


def test_native_option_activation_and_simulation_cannot_skip_bound_gate(frozen_risk,option_partial):
    book,c,clock,request=option_stage_request(frozen_risk,option_partial)
    store=OptionDataStore(book.path.parent/'options/chains');sequence=book.sequence('sample')
    args=dict(request_id='gate',plan_id='test-option-plan',as_of=clock.isoformat(),
              valid_until=(clock+timedelta(days=1)).isoformat(),expected_sequence=sequence,
              monthly_signal={},engine_evidence_file='not-needed',quote_snapshot_id=request['option_snapshot_id'],reconciliation_max_days=7)
    with pytest.raises(QuantError) as exc:activate(book,store,args)
    assert exc.value.code=='HEDGE_STAGE_CHECK_REQUIRED'
    with pytest.raises(QuantError) as exc:execute(book,store,dict(plan_id='test-option-plan',report_id='not-needed',
        execution_snapshot_id=request['option_snapshot_id'],as_of=clock.isoformat(),expected_sequence=sequence))
    assert exc.value.code=='HEDGE_STAGE_CHECK_REQUIRED' and book.sequence('sample')==sequence


def test_own_forward_pending_can_only_be_removed_by_fresh_checked_phase(frozen_risk,monkeypatch):
    book,request=setup(frozen_risk);clock='2025-01-15T21:30:00Z';assessment=analyze(book,'sample',request)
    import personal_quant.hedging.monitor as module
    original=module.monitor(book,'sample',clock);own=original['groups'][0]['hedge_id']
    blocked={**original,'status':'BLOCKED','checks':[dict(code='HEDGE_FORWARD_INTENT_PENDING',hedge_id=own,message='own pending')]}
    monkeypatch.setattr(module,'monitor',lambda *a:blocked)
    with pytest.raises(QuantError):require_planning(book,'sample',clock)
    require_planning(book,'sample',clock,stage_check=assessment)
    blocked['checks'].append(dict(code='OPTION_INCIDENT_REVIEW_REQUIRED',message='unresolved actual incident'))
    with pytest.raises(QuantError) as exc:require_planning(book,'sample',clock,stage_check=assessment)
    assert exc.value.code=='HEDGE_MONITOR_BLOCKED'


def test_rehashed_pressure_numbers_cannot_replace_original_calculation(frozen_risk):
    from copy import deepcopy
    from personal_quant.common import digest
    from personal_quant.hedging.stage_gate import validate_record
    book,request=setup(frozen_risk);assessment=analyze(book,'sample',request)
    bad=deepcopy(assessment);bad['vertices'][1]['friction']='0'
    bad['assessment_id']=digest({k:v for k,v in bad.items() if k!='assessment_id'})
    with pytest.raises(QuantError) as exc:validate_record(book,'sample','native-sale','OPEN',request,bad)
    assert exc.value.code=='CORRUPT_HEDGE_STAGE_AUDIT'
