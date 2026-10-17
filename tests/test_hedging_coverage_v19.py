import copy
import json
import os
import subprocess
import sqlite3
from pathlib import Path

import pytest

from personal_quant.common import QuantError, now_utc
from personal_quant.hedging.coverage_service import account_coverage
from personal_quant.options.ledger import register_contract
from test_options_ledger_v19 import contract, option_event
from test_options_lifecycle_v19 import plan
from personal_quant.options.lifecycle import manual_action
from conftest import event


def request(book, c, *, sequence=None):
    result=dict(schema_version=1, as_of='2026-10-09T21:00:00Z', knowledge_cutoff=now_utc(),
        ledger_seq=book.sequence('sample') if sequence is None else sequence, ledger_view='restated',
        security_ids={'SPY': 'security-us-spy'}, inflight_plan_ids=[], allocations=[dict(
            allocation_id='allocation-put', parent_id='hedge-one', security_id='security-us-spy',
            contract_id=c.contract_id, contract_version=c.version_hash, role='put_protection', state='actual',
            share_start=0, share_end=100, contracts=1, shares_per_contract=100,
            valid_from='2026-10-09T19:45:00Z', valid_until=c.exercise_cutoff_at, recorded_at=now_utc())])
    result['knowledge_cutoff']=now_utc()
    return result


def funded(book):
    c=contract(book)
    book.import_events('sample',[event('cash','DEPOSIT',amount=30000),
        event('stock','BUY',symbol='SPY',quantity=200,price=100,settlement_at='2026-10-09T20:00:00Z'),
        option_event('put','OPTION_TRADE',c,action='OPEN',trade_side='BUY',price=2)])
    return c


def test_actual_prefix_retains_put_after_later_close_and_no_writes(ledger):
    c=funded(ledger); req=request(ledger,c); original=copy.deepcopy(req)
    before=account_coverage(ledger,'sample',req)
    ledger.import_events('sample',[option_event('closed','OPTION_TRADE',c,action='CLOSE',trade_side='SELL',price=2)])
    old=account_coverage(ledger,'sample',req)
    assert old==before and req==original
    assert old['actual_protected_shares']=={'security-us-spy':'100'}
    assert ledger.sequence('sample')==4 and ledger.connection.execute('SELECT count(*) FROM tasks').fetchone()[0]==0
    with pytest.raises(QuantError) as exc:
        account_coverage(ledger,'sample',dict(req,ledger_seq=4,knowledge_cutoff=now_utc()))
    assert exc.value.code=='ALLOCATION_TERMS_MISMATCH'
    current=account_coverage(ledger,'sample',dict(req,ledger_seq=4,knowledge_cutoff=now_utc(),allocations=[]))
    assert current['actual_protected_shares']=={'security-us-spy':'0'}


@pytest.mark.parametrize('change,code',[
    ({'security_ids':{}},'MISSING_SECURITY_ID'),
    ({'security_ids':{'SPY':'same','IEF':'same'}},'INVALID_COVERAGE_REQUEST'),
    ({'ledger_seq':999},'INVALID_LEDGER_SEQUENCE'),
    ({'ledger_view':'known_then','knowledge_cutoff':'2026-10-09T21:00:00Z'},'LEDGER_NOT_KNOWN'),
    ({'as_of':'2099-10-09T21:00:00Z'},'FUTURE_COVERAGE'),
    ({'inflight_plan_ids':['fake-plan']},'UNKNOWN_OPTION_PLAN')])
def test_scope_time_sequence_and_foreign_plans(ledger,change,code):
    c=funded(ledger)
    with pytest.raises(QuantError) as exc: account_coverage(ledger,'sample',dict(request(ledger,c),**change))
    assert exc.value.code==code


def test_terms_from_registry_cannot_be_overridden_or_backdated(ledger):
    c=funded(ledger);req=request(ledger,c)
    req['allocations'][0]['shares_per_contract']=200
    with pytest.raises(QuantError) as exc:account_coverage(ledger,'sample',req)
    assert exc.value.code=='ALLOCATION_TERMS_MISMATCH'
    req=request(ledger,c)
    ledger.connection.execute("UPDATE option_contracts SET created_at='2099-01-01T00:00:00Z'")
    with pytest.raises(QuantError) as exc:account_coverage(ledger,'sample',req)
    assert exc.value.code=='ALLOCATION_TERMS_NOT_KNOWN'


def test_unrelated_option_is_retained_as_unallocated_risk(ledger):
    c=funded(ledger)
    body=c.content();body.update(contract_id='OTHER-PUT',underlying='IEF')
    other=register_contract(ledger,body)
    ledger.import_events('sample',[option_event('other','OPTION_TRADE',other,action='OPEN',trade_side='BUY',price=2)])
    result=account_coverage(ledger,'sample',request(ledger,c))
    assert result['unallocated_actual_contracts'][0]['contract_id']=='OTHER-PUT'


def test_draft_is_not_an_inflight_order(ledger):
    c=funded(ledger);identity=plan(ledger,c)
    req=request(ledger,c);req['inflight_plan_ids']=[identity]
    with pytest.raises(QuantError) as exc:account_coverage(ledger,'sample',req)
    assert exc.value.code=='NO_INFLIGHT_OPTION_ORDER'


def test_manual_partial_fill_splits_actual_and_inflight_without_extra_reservation(ledger):
    c=contract(ledger);plan_id=plan(ledger,c)
    ledger.import_events('sample',[event('cash','DEPOSIT',amount=30000),
        event('stock','BUY',symbol='SPY',quantity=200,price=100,settlement_at='2026-10-09T20:00:00Z')])
    manual_action(ledger,{'request_id':'submit','plan_id':plan_id,'action':'record-submitted',
        'as_of':'2026-10-09T19:40:00Z','expected_sequence':2,'reason':'synthetic explicit manual order',
        'orders':[{'contract_id':c.contract_id,'side':'BUY','contracts':2,'limit_price':2,'fee_per_contract':1}]})
    ledger.import_events('sample',[option_event('partial','OPTION_TRADE',c,action='OPEN',trade_side='BUY',price=2,plan_id=plan_id)])
    req=request(ledger,c);req['inflight_plan_ids']=[plan_id]
    req['allocations'].append(dict(req['allocations'][0],allocation_id='pending-put',state='inflight',share_start=100,share_end=200))
    before=ledger.connection.execute('SELECT payload,reserved_cash,reserved_positions FROM option_plans').fetchone()
    result=account_coverage(ledger,'sample',req)
    after=ledger.connection.execute('SELECT payload,reserved_cash,reserved_positions FROM option_plans').fetchone()
    assert tuple(before)==tuple(after)
    assert result['actual_protected_shares']['security-us-spy']=='100'
    assert result['inflight_intended_shares']['security-us-spy']=='100'
    assert len(result['inflight_plan_basis'])==1 and not result['creates_reservations']


def test_real_cli_read_repeat_and_error_never_records_tasks(ledger,tmp_path):
    c=funded(ledger); req=request(ledger,c); seq=ledger.sequence('sample')
    path=tmp_path/'coverage.json';path.write_text(json.dumps(req))
    cfg=tmp_path/'demo.toml';cfg.write_text((Path(__file__).resolve().parents[1]/'configs/demo.toml').read_text())
    target=tmp_path/'runtime/demo/account.sqlite';target.parent.mkdir(parents=True)
    copied=sqlite3.connect(target);ledger.connection.backup(copied);copied.close()
    env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'))
    command=[os.sys.executable,'-m','personal_quant.cli','--config',str(cfg),'hedge-coverage','--account-id','sample','--file',str(path)]
    ids=[]
    for _ in range(2):
        result=subprocess.run(command,capture_output=True,text=True,env=env,cwd=tmp_path)
        assert result.returncode==0,result.stderr
        ids.append(json.loads(result.stdout)['coverage_id'])
    assert len(set(ids))==1
    req['ledger_seq']=999;path.write_text(json.dumps(req))
    bad=subprocess.run(command,capture_output=True,text=True,env=env,cwd=tmp_path)
    assert bad.returncode==2 and json.loads(bad.stderr)['code']=='INVALID_LEDGER_SEQUENCE'
    assert ledger.sequence('sample')==seq and ledger.connection.execute('SELECT count(*) FROM tasks').fetchone()[0]==0
    with sqlite3.connect(target) as copied:
        assert copied.execute('SELECT count(*) FROM events').fetchone()[0]==seq
        assert copied.execute('SELECT count(*) FROM tasks').fetchone()[0]==0
