from datetime import timedelta
import json
import pandas as pd
import pytest
from personal_quant.common import canonical,now_utc,utc,decimal as D
from personal_quant.hedging.allocation_store import resources
from personal_quant.hedging.archive import publish
from personal_quant.hedging.securities import register
from personal_quant.hedging.intents import save as parent_save
from personal_quant.hedging.groups import save,progress
from personal_quant.hedging.group_revisions import save as revise
from personal_quant.options.contracts import OptionContract
from personal_quant.options.data import OptionDataStore
from personal_quant.options.ledger import register_contract
from personal_quant.portfolio.schema import apply_workbench_schema,apply_v18_schema,apply_v19_schema
from test_hedging_archive_v19 import frozen_risk
from test_hedging_exposure_v19 import risk_market
from test_hedging_securities_v19 import identity
from test_hedging_sizing_v19 import policy
from test_options_data_v19 import sample
from test_options_lifecycle_v19 import plan
from conftest import event


@pytest.fixture
def option_partial(frozen_risk):
    book,config,store,query,calendar=frozen_risk
    with book.transaction():
        apply_workbench_schema(book.connection);apply_v18_schema(book.connection);apply_v19_schema(book.connection)
    book.import_events('sample',[event('extra-stock','BUY',symbol='SPY',quantity=100,price=100,
                                      settlement_at='2024-07-02T20:00:00Z')])
    query={**query,'ledger_seq':3};risk=publish(book,config,store,'sample',query)
    security=register(book.path.parent,'demo',identity());clock=utc(query['as_of'])
    body=sample()[0].content();body.update(contract_id='SYNTHETIC-PUT-REVISION',right='PUT',strike='95',exercise_cash='9500',
        listed_at='2024-01-01T00:00:00Z',expiry='2025-03-07',last_trade_at='2025-03-07T21:00:00Z',exercise_cutoff_at='2025-03-07T22:30:00Z')
    c=register_contract(book,body);q=sample()[1];close=calendar.close(calendar.sessions[-1]).to_pydatetime()
    q.update(contract_id=c.contract_id,contract_version=c.version_hash,underlying_price=100,
             exchange_timestamp=close.isoformat(),underlying_timestamp=close.isoformat(),last_timestamp=close.isoformat(),
             available_at=(close+timedelta(seconds=2)).isoformat(),received_at=(close+timedelta(seconds=4)).isoformat(),
             open_interest_available_at=close.isoformat())
    chain=OptionDataStore(book.path.parent/'options/chains').save([c],pd.DataFrame([q]),sample()[2])['snapshot_id']
    params=dict(target_dte=45,minimum_dte=30,maximum_dte=60,put_moneyness=.95,call_moneyness=1.05,exit_days_before_expiry=7,
                max_age_seconds=3600,max_underlying_skew_seconds=60,max_spread_fraction=.25,max_leg_skew_seconds=10,max_underlying_price_fraction=.01)
    coverage=dict(schema_version=1,as_of=clock.isoformat(),knowledge_cutoff=now_utc(),ledger_seq=3,ledger_view='restated',
                  security_ids={'SPY':'security-us-spy'},allocations=[],inflight_plan_ids=[])
    spec=policy(scope=['SPY'],benchmark='GLD',tools=['protective_put'],mode='share_protection',target_beta=None,
                protection_fraction=1,min_days_to_expiry=30,max_days_to_expiry=60,exit_days_before_expiry=7)
    option=dict(snapshot_id=chain,selection_request=dict(template_id='protective_put',underlying='SPY',decision_at=clock.isoformat(),parameters=params),
                coverage_request=coverage,greeks=[],limits=dict(adverse_slippage_fraction=0,early_assignment_cash_reserve=0,
                max_greek_age_seconds=3600,max_mark_skew_seconds=3600,proxy_exit_policy='sell_before_expiry',
                failed_exit_policy='block_and_require_verified_resolution'),funding_quote=None)
    parent=parent_save(book,'sample',dict(schema_version=1,request_id='option-revision-parent',expected_version=None,
        expected_resource_hash=resources(book,'sample'),preview_request=dict(exposure_id=risk['exposure_id'],spec=spec,method='protective_put',option=option),
        security_ids={'SPY':'security-us-spy'},security_versions={'SPY':security['record']['version_hash']},
        decision_at=clock.isoformat(),knowledge_cutoff=now_utc(),valid_until=(clock+timedelta(days=5)).isoformat(),
        trigger='explicit_synthetic_protection',base_strategy_version='MANUAL_HOLDINGS',timing='historical_research',reason='Synthetic two-package amendment'),commit=True)
    assert D(parent['candidate']['planned_total_packages'])==2
    old=plan(book,c,quantity=2)
    newbody=json.loads(book.connection.execute('SELECT payload FROM option_plans WHERE plan_id=?',(old,)).fetchone()[0])
    newbody['plan_id']='new-option-plan';newbody['sizing']['lines'][0]['contracts']='1'
    book.connection.execute('INSERT INTO option_plans VALUES(?,?,?,?,?,?,?)',('new-option-plan','sample','DRAFT',canonical(newbody),'0','{}',clock.isoformat()))
    root=save(book,'sample',dict(schema_version=1,request_id='option-revision-group',hedge_id=parent['hedge_id'],parent_version=parent['version_hash'],
        expected_resource_hash=resources(book,'sample'),stages=[dict(stage_id='open',plan_kind='option',plan_id=old,action='OPEN',depends_on=[]),
            dict(stage_id='close',plan_kind='option',plan_id=old,action='CLOSE',depends_on=['open'])],reason='Synthetic native-format open/close references'),commit=True)
    def fact(name,plan_id,action,day):
        return event(name,'OPTION_TRADE',contract_version=c.version_hash,plan_id=plan_id,action=action,
                     trade_side='BUY' if action=='OPEN' else 'SELL',quantity=1,price=2 if action=='OPEN' else 3,
                     effective_at=(clock+timedelta(days=day)).isoformat(),settlement_at=(clock+timedelta(days=day)).isoformat())
    book.import_events('sample',[fact('old-open',old,'OPEN',1)])
    oldbody=json.loads(book.connection.execute('SELECT payload FROM option_plans WHERE plan_id=?',(old,)).fetchone()[0]);oldbody['status']='CANCELLED'
    book.connection.execute("UPDATE option_plans SET status='CANCELLED',payload=? WHERE plan_id=?",(canonical(oldbody),old))
    request=dict(schema_version=1,request_id='option-amendment',previous_group_id=root['group_id'],expected_group_hash=root['record_hash'],
                 expected_resource_hash=resources(book,'sample'),as_of=(clock+timedelta(days=2)).isoformat(),
                 replacements={'open':'new-option-plan'},reason='Retain one opened package, move remaining package')
    return book,c,old,clock,fact,request


def test_partial_option_amendment_splits_exits_and_preserves_cash(option_partial):
    book,c,old,clock,fact,request=option_partial
    amended=revise(book,'sample',request,commit=True)
    assert [s['stage_id'] for s in amended['stages']]==['open__retired_r2','open','close','close__replacement_r2']
    assert [s['lines'][0]['quantity'] for s in amended['stages']]==['1','1','1','1']
    assert amended['stages'][2]['depends_on']==['open__retired_r2']
    book.import_events('sample',[fact('old-close',old,'CLOSE',2)])
    view=progress(book,'sample',amended,clock+timedelta(days=2))
    assert view['stages'][2]['status']=='COMPLETE' and view['stages'][3]['status']=='WAITING_DEPENDENCY'
    book.import_events('sample',[fact('new-open','new-option-plan','OPEN',3),fact('new-close','new-option-plan','CLOSE',4)])
    assert progress(book,'sample',amended,clock+timedelta(days=4))['status']=='COMPLETE'
    state=book.snapshot('sample',clock+timedelta(days=4),{'SPY':100})
    assert D(state['settled_cash'])==10200 and state['option_positions']=={} and state['positions']=={'SPY':'200'}
    assert book.sequence('sample')==7


def test_second_option_amendment_preserves_all_prior_exit_slices(option_partial):
    book,c,old,clock,fact,request=option_partial
    first=revise(book,'sample',request,commit=True)
    body=json.loads(book.connection.execute('SELECT payload FROM option_plans WHERE plan_id=?',('new-option-plan',)).fetchone()[0])
    body['plan_id']='third-option-plan'
    book.connection.execute('INSERT INTO option_plans VALUES(?,?,?,?,?,?,?)',
        ('third-option-plan','sample','DRAFT',canonical(body),'0','{}',clock.isoformat()))
    body['plan_id']='new-option-plan';body['status']='CANCELLED'
    book.connection.execute("UPDATE option_plans SET status='CANCELLED',payload=? WHERE plan_id=?",(canonical(body),'new-option-plan'))
    second=revise(book,'sample',{**request,'request_id':'second-option-amendment',
        'previous_group_id':first['group_id'],'expected_group_hash':first['record_hash'],
        'expected_resource_hash':resources(book,'sample'),'as_of':(clock+timedelta(days=3)).isoformat(),
        'replacements':{'open':'third-option-plan'}},commit=True)
    stages={s['stage_id']:s for s in second['stages']}
    assert stages['open__retired_r2']['lines'][0]['quantity']=='1'
    assert stages['open__retired_r3']['lines']==[]
    assert stages['close__replacement_r2']['lines']==[]
    assert stages['close__replacement_r2__replacement_r3']['plan_id']=='third-option-plan'
    book.import_events('sample',[fact('old-close',old,'CLOSE',3),
        fact('third-open','third-option-plan','OPEN',4),fact('third-close','third-option-plan','CLOSE',5)])
    assert progress(book,'sample',second,clock+timedelta(days=5))['status']=='COMPLETE'
    state=book.snapshot('sample',clock+timedelta(days=5),{'SPY':100})
    assert D(state['settled_cash'])==10200 and state['option_positions']=={}
    assert book.sequence('sample')==7
