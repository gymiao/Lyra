from datetime import datetime,timedelta,time
from zoneinfo import ZoneInfo
import copy
from pathlib import Path

import pandas as pd
import pytest

from personal_quant.common import QuantError,now_utc,utc
from personal_quant.hedging.archive import publish
from personal_quant.hedging.allocation_store import resources,update,validate_references
from personal_quant.hedging.intents import save
from personal_quant.hedging.intent_actions import save as close_parent
from personal_quant.hedging.securities import register
from personal_quant.options.contracts import OptionContract
from personal_quant.options.data import OptionDataStore
from personal_quant.options.ledger import register_contract
from personal_quant.portfolio import Ledger
from personal_quant.portfolio.backup import create_bundle,verify_bundle,restore_bundle
from personal_quant.portfolio.schema import apply_workbench_schema,apply_v18_schema,apply_v19_schema
from test_hedging_archive_v19 import frozen_risk
from test_hedging_exposure_v19 import risk_market
from test_hedging_intents_v19 import parent
from test_hedging_intent_actions_v19 import close_request
from test_hedging_securities_v19 import identity
from test_hedging_sizing_v19 import policy
from test_options_data_v19 import sample


@pytest.fixture
def bound_option(frozen_risk):
    book,config,store,query,calendar=frozen_risk
    with book.transaction():
        apply_workbench_schema(book.connection);apply_v18_schema(book.connection);apply_v19_schema(book.connection)
    risk=publish(book,config,store,'sample',query)
    registered=register(book.path.parent,'demo',identity())
    clock=utc(query['as_of']);close=calendar.close(calendar.sessions[-1]).to_pydatetime()
    expiry=clock.date()+timedelta(days=45);expiry+=timedelta(days=(4-expiry.weekday())%7)
    last=datetime.combine(expiry,time(16),ZoneInfo('America/New_York')).astimezone(ZoneInfo('UTC'))
    body=sample()[0].content()
    body.update(contract_id='SYNTHETIC-PUT-95',right='PUT',strike='95',exercise_cash='9500',
        listed_at='2024-01-01T00:00:00Z',expiry=expiry.isoformat(),last_trade_at=last.isoformat(),
        exercise_cutoff_at=(last+timedelta(minutes=90)).isoformat())
    c=OptionContract.from_dict(body);row=sample()[1]
    row.update(contract_id=c.contract_id,contract_version=c.version_hash,underlying_price=100,
        exchange_timestamp=close.isoformat(),underlying_timestamp=close.isoformat(),last_timestamp=close.isoformat(),
        available_at=(close+timedelta(seconds=2)).isoformat(),received_at=(close+timedelta(seconds=4)).isoformat(),
        open_interest_available_at=close.isoformat())
    snapshot=OptionDataStore(book.path.parent/'options/chains').save([c],pd.DataFrame([row]),sample()[2])['snapshot_id']
    coverage=dict(schema_version=1,as_of=clock.isoformat(),knowledge_cutoff=now_utc(),ledger_seq=2,
                  ledger_view='restated',security_ids={'SPY':'security-us-spy'},allocations=[],inflight_plan_ids=[])
    params=dict(target_dte=45,minimum_dte=30,maximum_dte=60,put_moneyness=.95,call_moneyness=1.05,
        exit_days_before_expiry=7,max_age_seconds=3600,max_underlying_skew_seconds=60,max_spread_fraction=.25,
        max_leg_skew_seconds=10,max_underlying_price_fraction=.01)
    spec=policy(scope=['SPY'],benchmark='GLD',tools=['protective_put'],mode='share_protection',
        target_beta=None,protection_fraction=1,min_days_to_expiry=30,max_days_to_expiry=60,exit_days_before_expiry=7)
    option=dict(snapshot_id=snapshot,selection_request=dict(template_id='protective_put',underlying='SPY',
        decision_at=clock.isoformat(),parameters=params),coverage_request=coverage,greeks=[],
        limits=dict(adverse_slippage_fraction=0,early_assignment_cash_reserve=0,max_greek_age_seconds=3600,
                    max_mark_skew_seconds=3600,proxy_exit_policy='sell_before_expiry',
                    failed_exit_policy='block_and_require_verified_resolution'),funding_quote=None)
    req=dict(schema_version=1,request_id='option-parent',expected_version=None,expected_resource_hash=resources(book,'sample'),
        preview_request=dict(exposure_id=risk['exposure_id'],spec=spec,method='protective_put',option=option),
        security_ids={'SPY':'security-us-spy'},security_versions={'SPY':registered['record']['version_hash']},
        decision_at=clock.isoformat(),knowledge_cutoff=now_utc(),valid_until=(clock+timedelta(days=5)).isoformat(),
        trigger='explicit_synthetic_protection',base_strategy_version='MANUAL_HOLDINGS',timing='historical_research',
        reason='Synthetic actual parent/option linkage')
    original=save(book,'sample',req,commit=True)
    assert original['candidate']['planned_total_packages']=='1'
    register_contract(book,c.content())
    effective=clock+timedelta(days=1)
    book.import_events('sample',[dict(event_id='put-fill',kind='OPTION_TRADE',contract_version=c.version_hash,
        action='OPEN',trade_side='BUY',quantity=1,price=2,effective_at=effective.isoformat(),
        settlement_at=effective.isoformat(),source='synthetic_statement',evidence_type='test')])
    coverage.update(as_of=effective.isoformat(),knowledge_cutoff=now_utc(),ledger_seq=book.sequence('sample'),
                    security_versions=req['security_versions'])
    allocation=dict(allocation_id='protection',parent_id=original['hedge_id'],security_id='security-us-spy',
        contract_id=c.contract_id,contract_version=c.version_hash,role='put_protection',state='actual',
        share_start=0,share_end=100,contracts=1,shares_per_contract=100,valid_from=effective.isoformat(),
        valid_until=c.exercise_cutoff_at,recorded_at=now_utc())
    coverage['knowledge_cutoff']=now_utc()
    request=dict(schema_version=2,request_id='strict-first',expected_version=None,
        expected_resource_hash=resources(book,'sample'),coverage_request=coverage,changes=[allocation],retire_ids=[],
        reason='Explicit strict parent binding',parent_versions={'protection':original['version_hash']})
    return book,original,request


def test_strict_binding_preserves_parent_and_actual_facts(bound_option):
    book,parent,req=bound_option
    preview=update(book,'sample',req)
    first=update(book,'sample',req,commit=True)
    assert first['version_hash']==preview['version_hash'] and first['schema_version']==2
    assert first['parent_basis']['protection']['parent_record_hash']==parent['record_hash']
    assert first['coverage']['actual_protected_shares']['security-us-spy']=='100'
    assert update(book,'sample',req,commit=True)==first and book.sequence('sample')==3
    validate_references(book.path.parent,book)


@pytest.mark.parametrize('field,value,code',[
    ('parent_versions',{},'HEDGE_PARENT_BINDINGS_REQUIRED'),
    ('parent_versions',{'protection':'unknown'},'UNKNOWN_HEDGE_PARENT_VERSION'),
    ('parent_id','arbitrary','HEDGE_ALLOCATION_SCOPE_MISMATCH')])
def test_missing_or_wrong_parent_is_rejected_atomically(bound_option,field,value,code):
    book,_,req=bound_option;req=copy.deepcopy(req);before=resources(book,'sample')
    if field=='parent_id':req['changes'][0][field]=value
    else:req[field]=value
    with pytest.raises(QuantError) as exc:update(book,'sample',req,commit=True)
    assert exc.value.code==code and resources(book,'sample')==before


def test_close_preserves_bound_history_but_forbids_new_changes(bound_option):
    book,original,req=bound_option;first=update(book,'sample',req,commit=True)
    close_parent(book,'sample',close_request(book,original),commit=True)
    validate_references(book.path.parent,book)
    changed=dict(req,request_id='closed-edit',expected_version=first['version_hash'],expected_resource_hash=resources(book,'sample'))
    with pytest.raises(QuantError) as exc:update(book,'sample',changed,commit=True)
    assert exc.value.code=='HEDGE_INTENT_CLOSED'
    retired=dict(changed,request_id='retire',changes=[],retire_ids=['protection'],parent_versions={})
    second=update(book,'sample',retired,commit=True)
    assert second['coverage']['actual_protected_shares']['security-us-spy']=='0'
    assert second['coverage']['unallocated_actual_contracts'][0]['unallocated_contracts']=='1'
    assert book.sequence('sample')==3


def test_strict_collection_cannot_downgrade_and_full_restore(bound_option,tmp_path):
    book,_,req=bound_option;first=update(book,'sample',req,commit=True)
    legacy=dict(req,schema_version=1,request_id='downgrade',expected_version=first['version_hash'],
                expected_resource_hash=resources(book,'sample'));legacy.pop('parent_versions')
    with pytest.raises(QuantError) as exc:update(book,'sample',legacy,commit=True)
    assert exc.value.code=='HEDGE_PARENT_BINDINGS_REQUIRED'
    cfg=tmp_path/'demo.toml';cfg.write_bytes((Path(__file__).resolve().parents[1]/'configs/demo.toml').read_bytes())
    create_bundle(book.path.parent,cfg,tmp_path/'bundle');verify_bundle(tmp_path/'bundle','demo')
    restore_bundle(tmp_path/'bundle',tmp_path/'restored','demo')
    restored=Ledger(tmp_path/'restored/runtime/demo/account.sqlite','demo')
    validate_references(restored.path.parent,restored);restored.close()


@pytest.mark.parametrize('different_contract',[False,True])
def test_actual_position_does_not_override_frozen_contract_or_target(bound_option,different_contract):
    book,_,req=bound_option;req=copy.deepcopy(req)
    row=req['changes'][0]
    original=book.connection.execute('SELECT payload FROM option_contracts WHERE version_hash=?',
                                     (row['contract_version'],)).fetchone()
    import json
    body=json.loads(original[0])
    if different_contract:body['contract_id']='OTHER-UNSELECTED-PUT'
    c=register_contract(book,body)
    clock=req['coverage_request']['as_of']
    book.import_events('sample',[dict(event_id='additional-put',kind='OPTION_TRADE',contract_version=c.version_hash,
        action='OPEN',trade_side='BUY',quantity=1,price=2,effective_at=clock,settlement_at=clock,
        source='synthetic_statement',evidence_type='test')])
    req['coverage_request'].update(ledger_seq=book.sequence('sample'),knowledge_cutoff=now_utc())
    req['expected_resource_hash']=resources(book,'sample')
    if different_contract:row.update(contract_id=c.contract_id,contract_version=c.version_hash)
    else:row['contracts']=2
    row['recorded_at']=now_utc();req['coverage_request']['knowledge_cutoff']=now_utc()
    before=resources(book,'sample')
    with pytest.raises(QuantError) as exc:update(book,'sample',req,commit=True)
    assert exc.value.code==('HEDGE_ALLOCATION_CANDIDATE_MISMATCH' if different_contract else 'HEDGE_ALLOCATION_EXCEEDS_TARGET')
    assert resources(book,'sample')==before and book.sequence('sample')==4


def test_explicit_legacy_upgrade_binds_all_retained_references(bound_option):
    book,parent,req=bound_option
    legacy=dict(req,schema_version=1,request_id='legacy');legacy.pop('parent_versions')
    first=update(book,'sample',legacy,commit=True)
    strict=dict(req,request_id='upgrade',expected_version=first['version_hash'],
                expected_resource_hash=resources(book,'sample'),changes=[])
    second=update(book,'sample',strict,commit=True)
    assert second['parent_basis']['protection']['parent_record_hash']==parent['record_hash']
    assert second['allocations']==first['allocations'] and book.sequence('sample')==3


def test_exact_retry_validates_original_parent_reference(bound_option):
    import json
    from personal_quant.common import canonical,digest
    book,parent,req=bound_option;update(book,'sample',req,commit=True)
    changed=dict(parent,meaning='Changed after allocation binding')
    changed['record_hash']=digest({k:v for k,v in changed.items() if k!='record_hash'})
    book.connection.execute("UPDATE tasks SET details=? WHERE task_id LIKE 'hedge-intent:%'",(canonical(changed),))
    with pytest.raises(QuantError) as exc:update(book,'sample',req,commit=True)
    assert exc.value.code=='CORRUPT_ALLOCATION_PARENT'

