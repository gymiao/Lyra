import pandas as pd
import pytest
from pathlib import Path
import shutil
from personal_quant.common import decimal as D,now_utc,QuantError
from personal_quant.hedging.option_sizing import option_candidate
from personal_quant.hedging.spec import HedgeSpec
from personal_quant.hedging.preview import preview
from personal_quant.hedging.archive import publish
from personal_quant.hedging.intents import save,records,validate_references
from personal_quant.hedging.securities import register
from personal_quant.hedging.allocation_store import resources
from personal_quant.portfolio import Ledger
from personal_quant.portfolio.backup import create_bundle,verify_bundle,restore_bundle
from personal_quant.options.contracts import OptionContract
from personal_quant.options.data import OptionDataStore
from personal_quant.options.selection import select
from test_options_selection_v19 import chain,request as selection_request
from test_hedging_sizing_v19 import policy,quote,risk
from test_hedging_archive_v19 import frozen_risk
from test_hedging_exposure_v19 import risk_market
from test_hedging_securities_v19 import identity

LIMITS=dict(adverse_slippage_fraction=0,early_assignment_cash_reserve=0,max_greek_age_seconds=3600,
    max_mark_skew_seconds=3600,proxy_exit_policy='sell_before_expiry',failed_exit_policy='block_and_require_verified_resolution')

@pytest.fixture
def selected(tmp_path):
    contracts,rows,meta=chain();store=OptionDataStore(tmp_path/'chains')
    snapshot=store.save(contracts,pd.DataFrame(rows),meta)['snapshot_id']
    return {kind:select(store,snapshot,selection_request(kind)) for kind in ('protective_put','collar')}

def account(**changes):
    r=risk(E=26000,B=25000,cash=1000,positions={'SPY':'250'})
    r.update(as_of='2026-10-09T19:46:00Z',knowledge_cutoff='2026-10-09T19:46:00Z')
    r['account']['prices']['SPY']=100;r['valuation']['prices']['SPY']=100
    r['beta_model']['benchmark']='INDEX';r['beta_model']['estimates']['SPY']={'status':'CHECKED','beta':1}
    r['account'].update(changes);return r

def share_spec(**changes):
    return HedgeSpec.from_dict(policy(scope=['SPY'],tools=['protective_put','collar','proxy_put'],
        mode='share_protection',target_beta=None,protection_fraction=1,**changes))

def group(**changes):
    return dict(dict(parent_id='existing',actual_put_shares=0,actual_call_shares=0,pending_put_shares=0,
        pending_call_shares=0,valid_until='2026-12-18T22:30:00Z'),**changes)

def test_direct_put_integer_tail_and_costs_do_not_need_beta(selected):
    r=account();r['risk']['beta_amount']=None
    result=option_candidate(r,share_spec(),'protective_put',selected['protective_put'],[],[],LIMITS)
    assert result['incremental_packages']=='2' and result['uncovered_fractional_shares']=='50'
    assert D(result['E_post'])==25986 and D(result['available_cash_after_all_settlements'])==776
    assert D(result['estimated_fees'])==4 and D(result['estimated_cost'])==14
    assert result['B_post'] is None and not result['executable']

def test_existing_and_pending_are_subtracted_not_rebought(selected):
    g=group(actual_put_shares=100,pending_put_shares=100)
    result=option_candidate(account(),share_spec(),'protective_put',selected['protective_put'],[g],[],LIMITS)
    assert result['status']=='WAITING_FOR_FILL' and result['incremental_packages']=='0' and result['trades']==[]
    result=option_candidate(account(),share_spec(),'protective_put',selected['protective_put'],[group(actual_put_shares=100)],[],LIMITS)
    assert result['incremental_packages']=='1' and result['planned_total_packages']=='2'

@pytest.mark.parametrize('method,target,expected_B,expected_E',[
    ('protective_put',.58,15000,25986),('collar',.2,5000,25972)])
def test_direct_beta_target_signed_legs_and_physical_share_limit(selected,method,target,expected_B,expected_E):
    selection=selected[method]
    greeks=[dict(contract_version=leg['contract_version'],unit='per_share',
        value=-.5 if leg['quantity_per_package']>0 else .5,signed_contracts=leg['quantity_per_package'],
        source='synthetic',data_type='synthetic',as_of='2026-10-09T19:45:00Z',
        available_at='2026-10-09T19:45:02Z',received_at='2026-10-09T19:45:04Z',model_inputs={})
        for leg in selection['legs']]
    spec=HedgeSpec.from_dict(policy(scope=['SPY'],target_beta=target,residual_beta_tolerance=.01))
    result=option_candidate(account(),spec,method,selection,[],greeks,LIMITS)
    assert result['status']=='SELECTED_FOR_RESEARCH' and result['incremental_packages']=='2'
    assert D(result['B_post'])==expected_B and D(result['E_post'])==expected_E
    assert abs(D(result['beta_post'])-D(target))<=D('.01')
    limited=option_candidate(account(reserved_positions={'SPY':'100'}),spec,method,selection,[],greeks,LIMITS)
    assert limited['status']=='NO_FEASIBLE_HEDGE' and limited['trades']==[]
    assert 'INSUFFICIENT_UNALLOCATED_SHARES' in limited['checks'][0]


def test_model_delta_candidate_rejects_a_different_underlying_price(selected):
    selection=selected['protective_put'];leg=selection['legs'][0]
    greek=dict(contract_version=leg['contract_version'],unit='per_share',value=-.5,signed_contracts=1,
        source='explicit research model',data_type='model',as_of='2026-10-09T19:45:00Z',
        available_at='2026-10-09T19:45:02Z',received_at='2026-10-09T19:45:04Z',
        model_inputs={'pricing':{'spot':200}})
    spec=HedgeSpec.from_dict(policy(scope=['SPY'],target_beta=.58,residual_beta_tolerance=.01))
    result=option_candidate(account(),spec,'protective_put',selection,[],[greek],LIMITS)
    assert result['status']=='NO_FEASIBLE_HEDGE' and result['checks']==['MODEL_GREEK_PRICE_MISMATCH']
    assert result['trades']==[]

def test_collar_proceeds_are_not_advanced_and_unpaired_legs_recover(selected):
    result=option_candidate(account(),share_spec(),'collar',selected['collar'],[],[],LIMITS)
    assert result['incremental_packages']=='2' and D(result['E_post'])==25972
    assert D(result['available_cash_after_all_settlements'])==972 and D(result['estimated_cost'])==28
    denied=option_candidate(account(available_cash=100),share_spec(),'collar',selected['collar'],[],[],LIMITS)
    assert denied['status']=='NO_FEASIBLE_HEDGE' and 'INSUFFICIENT_SETTLED_CASH' in denied['checks'][0]
    unpaired=option_candidate(account(),share_spec(),'collar',selected['collar'],[group(actual_put_shares=100)],[],LIMITS)
    assert unpaired['checks']==['UNPAIRED_COLLAR_LEGS_REQUIRE_RECOVERY']

@pytest.mark.parametrize('change', [{'max_premium':100},{'max_notional':100},{'max_contracts':0}])
def test_budgets_produce_explicit_no_feasible_candidate(selected,change):
    result=option_candidate(account(),share_spec(**change),'protective_put',selected['protective_put'],[],[],LIMITS)
    assert result['status']=='NO_FEASIBLE_HEDGE' and result['trades']==[]

def test_old_protection_does_not_fake_continuous_expiry_coverage(selected):
    result=option_candidate(account(),share_spec(),'protective_put',selected['protective_put'],
        [group(actual_put_shares=100,valid_until='2026-11-01T00:00:00Z')],[],LIMITS)
    assert result['checks']==['PROTECTION_HORIZON_REVIEW_REQUIRED']

def test_proxy_delta_units_funding_and_exit_failure_policy(selected):
    r=account(positions={'BASE':'1000'},available_cash=0,equity='100000');r['risk']['beta_amount']='100000'
    spec=HedgeSpec.from_dict(policy(scope=['BASE'],funding='sell_scope',funding_symbol='BASE',
        tools=['proxy_put'],residual_beta_tolerance=.02))
    greek=dict(contract_version=selected['protective_put']['legs'][0]['contract_version'],unit='per_share',value=-.5,signed_contracts=1,
        source='synthetic',data_type='synthetic',as_of='2026-10-09T19:45:00Z',available_at='2026-10-09T19:45:02Z',
        received_at='2026-10-09T19:45:04Z',model_inputs={})
    result=option_candidate(r,spec,'proxy_put',selected['protective_put'],[],[greek],LIMITS,funding_quote=quote('BASE',100,1,'stock'))
    assert result['incremental_packages']=='10' and result['trades'][0]['quantity']=='12'
    assert D(result['B_post'])==48800 and D(result['E_post'])==99930
    assert result['funding_requires_settlement'] and D(result['available_cash_after_all_settlements'])==80
    total=dict(greek,unit='position_total',value=-50)
    normalized=option_candidate(r,spec,'proxy_put',selected['protective_put'],[],[total],LIMITS,funding_quote=quote('BASE',100,1,'stock'))
    assert D(normalized['B_post'])==D(result['B_post'])
    assert normalized['candidate_inputs']['greeks'][0]['unit']=='position_total'
    missing=option_candidate(r,spec,'proxy_put',selected['protective_put'],[],[],LIMITS)
    assert missing['checks']==['MODEL_INPUT_REQUIRED']
    bad=option_candidate(r,spec,'proxy_put',selected['protective_put'],[],[greek],dict(LIMITS,failed_exit_policy=None))
    assert bad['checks']==['PROXY_EXIT_FAILURE_POLICY_REQUIRED']

def option_request(fixture,method='protective_put'):
    book,config,store,q,calendar=fixture;artifact=publish(book,config,store,'sample',q)
    contracts,rows,meta=chain();converted=[]
    close=calendar.close(calendar.sessions[-1]);stamp=close.isoformat()
    for c in contracts:
        body=c.content();body.update(listed_at='2024-01-01T00:00:00Z',expiry='2025-01-30',
            last_trade_at='2025-01-30T21:00:00Z',exercise_cutoff_at='2025-01-30T22:30:00Z');converted.append(OptionContract.from_dict(body))
    for row,c in zip(rows,converted):
        row.update(contract_version=c.version_hash,exchange_timestamp=stamp,underlying_timestamp=stamp,last_timestamp=stamp,
            available_at=(close+pd.Timedelta(seconds=2)).isoformat(),received_at=(close+pd.Timedelta(seconds=4)).isoformat(),open_interest_available_at=stamp)
    chainstore=OptionDataStore(book.path.parent/'options/chains');snap=chainstore.save(converted,pd.DataFrame(rows),meta)['snapshot_id']
    params=dict(selection_request(method)['parameters'],minimum_dte=10,maximum_dte=80,max_age_seconds=3600)
    selection=dict(template_id=method,underlying='SPY',decision_at=q['as_of'],parameters=params)
    cov=dict(schema_version=1,as_of=q['as_of'],knowledge_cutoff=now_utc(),ledger_seq=2,ledger_view='restated',
        security_ids={'SPY':'declared-SPY'},allocations=[],inflight_plan_ids=[])
    return dict(exposure_id=artifact['exposure_id'],spec=share_spec(min_days_to_expiry=10,max_days_to_expiry=80).content(),method=method,
        option=dict(snapshot_id=snap,selection_request=selection,coverage_request=cov,greeks=[],limits=LIMITS,funding_quote=None))

def test_service_reuses_selection_and_account_facts_without_writing(frozen_risk):
    book,*_=frozen_risk;req=option_request(frozen_risk)
    first=preview(book,'sample',req);second=preview(book,'sample',req)
    assert first==second and first['status']=='SELECTED_FOR_RESEARCH' and first['incremental_packages']=='1'
    assert first['source_assessment']['status']=='SYNTHETIC_DEMO' and first['option_snapshot_id']
    assert book.sequence('sample')==2 and book.connection.execute('SELECT count(*) FROM tasks').fetchone()[0]==0

def test_service_cannot_inject_unrecorded_protection(frozen_risk):
    book,*_=frozen_risk;req=option_request(frozen_risk)
    req['option']['coverage_request']['allocations']=[{'invented':'coverage'}]
    with pytest.raises(QuantError) as exc:preview(book,'sample',req)
    assert exc.value.code=='HEDGE_ALLOCATION_BASIS_MISMATCH'

def test_option_candidate_parent_full_restore_and_missing_chain_rejected(frozen_risk,tmp_path):
    book,*_=frozen_risk;candidate=option_request(frozen_risk)
    registered=register(book.path.parent,'demo',identity())
    req=dict(schema_version=1,request_id='option-parent',expected_version=None,expected_resource_hash=resources(book,'sample'),
        preview_request=candidate,security_ids={'SPY':'security-us-spy'},security_versions={'SPY':registered['record']['version_hash']},
        decision_at=candidate['option']['selection_request']['decision_at'],knowledge_cutoff=now_utc(),
        valid_until='2025-01-30T22:30:00Z',trigger='synthetic_research',base_strategy_version='MANUAL_HOLDINGS',
        timing='historical_research',reason='synthetic protective Put candidate parent')
    saved=save(book,'sample',req,commit=True);validate_references(book.path.parent,book)
    assert saved['candidate']['incremental_packages']=='1'
    cfg=tmp_path/'demo.toml';cfg.write_bytes((Path(__file__).resolve().parents[1]/'configs/demo.toml').read_bytes())
    create_bundle(book.path.parent,cfg,tmp_path/'bundle');verify_bundle(tmp_path/'bundle','demo')
    restore_bundle(tmp_path/'bundle',tmp_path/'restored','demo')
    restored=Ledger(tmp_path/'restored/runtime/demo/account.sqlite','demo')
    assert records(restored,'sample')==[saved];validate_references(restored.path.parent,restored);restored.close()
    shutil.rmtree(book.path.parent/'options/chains'/saved['candidate']['option_snapshot_id'])
    with pytest.raises(QuantError) as exc:validate_references(book.path.parent,book)
    assert exc.value.code=='CORRUPT_HEDGE_INTENT'
