import json
from datetime import timedelta
from pathlib import Path

import pytest

from personal_quant.common import QuantError,now_utc,utc
from personal_quant.hedging.archive import publish
from personal_quant.hedging.allocation_store import resources
from personal_quant.hedging.intents import save,records,validate_references
from personal_quant.hedging.securities import register
from personal_quant.portfolio import Ledger
from personal_quant.portfolio.backup import create_bundle,verify_bundle,restore_bundle
from personal_quant.portfolio.schema import apply_workbench_schema
from test_hedging_archive_v19 import frozen_risk
from test_hedging_exposure_v19 import risk_market
from test_hedging_securities_v19 import identity
from test_hedging_sizing_v19 import policy


def parent(fixture):
    book,config,store,query,_=fixture
    archive=publish(book,config,store,'sample',query)
    registered=register(book.path.parent,'demo',identity())
    preview=dict(exposure_id=archive['exposure_id'],spec=policy(scope=['SPY'],benchmark='GLD',target_beta=.1,
        tools=['reduce_stock'],residual_beta_tolerance=.001),method='reduce_stock',funding_quote=None,
        proxy=dict(symbol='SPY',execution_price=100,market_price=100,beta=.5,trade_unit=1,
                   product_type='etf',product_evidence='synthetic research declaration'))
    return dict(schema_version=1,request_id='parent-one',expected_version=None,
        expected_resource_hash=resources(book,'sample'),preview_request=preview,
        security_ids={'SPY':'security-us-spy'},security_versions={'SPY':registered['record']['version_hash']},
        decision_at=query['as_of'],knowledge_cutoff=now_utc(),valid_until='2025-01-30T22:30:00Z',
        trigger='monthly_research',base_strategy_version='MANUAL_HOLDINGS',timing='historical_research',reason='Synthetic frozen parent decision')


def test_parent_freezes_all_inputs_and_exact_retry(frozen_risk):
    book,*_=frozen_risk;req=parent(frozen_risk)
    preview=save(book,'sample',req)
    assert records(book,'sample')==[]
    saved=save(book,'sample',req,commit=True)
    assert saved['version_hash']==preview['version_hash'] and save(book,'sample',req,commit=True)==saved
    assert saved['candidate']['incremental_quantity']=='-40' and saved['candidate']['spec_hash']
    assert saved['exposure_id']==req['preview_request']['exposure_id'] and saved['security_basis']['SPY']
    assert saved['generated_at']!=saved['decision_at'] and saved['timing']=='historical_research'
    assert not saved['executable'] and not saved['creates_reservations'] and book.sequence('sample')==2
    validate_references(book.path.parent,book)


def test_candidate_revision_preserves_parent_and_old_decision(frozen_risk):
    book,*_=frozen_risk;req=parent(frozen_risk);first=save(book,'sample',req,commit=True)
    revised=dict(req,request_id='revise-price',expected_version=first['version_hash'],expected_resource_hash=resources(book,'sample'))
    revised['preview_request']=dict(req['preview_request'],proxy=dict(req['preview_request']['proxy'],execution_price=101))
    second=save(book,'sample',revised,commit=True)
    assert second['hedge_id']==first['hedge_id'] and second['revision']==2
    assert second['previous_version']==first['version_hash'] and second['candidate']['preview_hash']!=first['candidate']['preview_hash']
    assert records(book,'sample')[0]==first


@pytest.mark.parametrize('change,code',[
    ({'base_strategy_version':'unbound-strategy'},'HEDGE_BASE_STRATEGY_NOT_ACTIVE'),
    ({'timing':'forward'},'INVALID_HEDGE_INTENT_TIME'),
    ({'decision_at':'2099-01-01T00:00:00Z'},'INVALID_HEDGE_INTENT_TIME'),
    ({'security_ids':{'SPY':{}}},'INVALID_HEDGE_SCOPE'),
    ({'expected_resource_hash':'stale'},'STALE_HEDGE_RESOURCES')])
def test_unbound_future_or_stale_inputs_do_not_create_parent(frozen_risk,change,code):
    book,*_=frozen_risk;req=parent(frozen_risk)
    with pytest.raises(QuantError) as exc:save(book,'sample',dict(req,**change),commit=True)
    assert exc.value.code==code and records(book,'sample')==[]


@pytest.mark.parametrize('change,code',[
    ({'security_versions':[]},'INVALID_SECURITY_BINDING'),
    ({'security_versions':{'GLD':'unrelated-version'}},'INVALID_SECURITY_BINDING'),
    ({'tool_security_ids':{'GLD':'security-us-gld'}},'INVALID_HEDGE_INTENT'),
    ({'tool_security_ids':{'GLD':'security-us-gld'},'tool_security_versions':[]},'INVALID_SECURITY_BINDING'),
    ({'tool_security_ids':{'GLD':'security-us-gld'},'tool_security_versions':{'IEF':'unrelated-version'}},'INVALID_SECURITY_BINDING'),
])
def test_malformed_tool_bindings_fail_with_domain_error(frozen_risk,change,code):
    book,*_=frozen_risk;req=parent(frozen_risk)
    with pytest.raises(QuantError) as exc:save(book,'sample',dict(req,**change),commit=True)
    assert exc.value.code==code and records(book,'sample')==[]


def test_spec_version_and_overlapping_scope_cannot_bypass_parent(frozen_risk):
    book,*_=frozen_risk;req=parent(frozen_risk);first=save(book,'sample',req,commit=True)
    revised=dict(req,request_id='new-policy',expected_version=first['version_hash'],expected_resource_hash=resources(book,'sample'))
    revised['preview_request']=dict(req['preview_request'],spec=dict(req['preview_request']['spec'],target_beta=.2))
    with pytest.raises(QuantError) as exc:save(book,'sample',revised,commit=True)
    assert exc.value.code=='HEDGE_POLICY_VERSION_CONFLICT'
    revised['preview_request']['spec']['version']='2';revised['expected_version']=None
    with pytest.raises(QuantError) as exc:save(book,'sample',revised,commit=True)
    assert exc.value.code=='HEDGE_SCOPE_CONFLICT'
    assert len(records(book,'sample'))==1


def test_full_backup_restore_and_parent_tampering(frozen_risk,tmp_path):
    book,*_=frozen_risk;req=parent(frozen_risk);saved=save(book,'sample',req,commit=True)
    cfg=tmp_path/'demo.toml';cfg.write_bytes((Path(__file__).resolve().parents[1]/'configs/demo.toml').read_bytes())
    create_bundle(book.path.parent,cfg,tmp_path/'bundle');verify_bundle(tmp_path/'bundle','demo')
    restore_bundle(tmp_path/'bundle',tmp_path/'restored','demo')
    restored=Ledger(tmp_path/'restored/runtime/demo/account.sqlite','demo')
    assert records(restored,'sample')==[saved];validate_references(restored.path.parent,restored);restored.close()
    bad=dict(saved,decision_at='2024-01-01T00:00:00Z')
    book.connection.execute("UPDATE tasks SET details=? WHERE task_id LIKE 'hedge-intent:%'",(json.dumps(bad),))
    with pytest.raises(QuantError) as exc:validate_references(book.path.parent,book)
    assert exc.value.code=='CORRUPT_HEDGE_INTENT'


@pytest.mark.parametrize('next_session', [False,True])
def test_strategy_effective_date_uses_new_york_session_at_utc_midnight(frozen_risk,next_session):
    book,*_=frozen_risk;req=parent(frozen_risk)
    day=utc(req['decision_at']).date();utc_day=day+timedelta(days=1)
    req['decision_at']=utc_day.isoformat()+'T01:00:00Z'
    with book.transaction():
        apply_workbench_schema(book.connection)
        book.connection.execute('INSERT INTO strategy_versions VALUES(?,?,?,?,?,?)',
            ('synthetic-base',1,'test','test-base-hash','{}','2024-01-01T00:00:00Z'))
        book.connection.execute('INSERT INTO strategy_bindings(account_id,strategy_id,revision,spec_hash,effective_session,requested_at,status,details) VALUES(?,?,?,?,?,?,?,?)',
            ('sample','synthetic-base',1,'test-base-hash',(utc_day if next_session else day).isoformat(),'2024-01-01T00:00:00Z','ACTIVE','{}'))
    req.update(base_strategy_version='test-base-hash',expected_resource_hash=resources(book,'sample'))
    if next_session:
        with pytest.raises(QuantError) as exc:save(book,'sample',req,commit=True)
        assert exc.value.code=='HEDGE_BASE_STRATEGY_NOT_ACTIVE'
    else:
        assert save(book,'sample',req,commit=True)['strategy_basis']['strategy_id']=='synthetic-base'
