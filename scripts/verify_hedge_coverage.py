"""Actual CLI checks using explicitly synthetic statements, without network."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from personal_quant.common import now_utc
from personal_quant.portfolio import Ledger
from personal_quant.portfolio.schema import apply_workbench_schema, apply_v18_schema, apply_v19_schema
from personal_quant.options.ledger import register_contract
from personal_quant.strategies.archive import source_fingerprint


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--destination',type=Path,required=True)
    root=parser.parse_args().destination.resolve();root.mkdir(parents=True,exist_ok=False)
    repo=Path(__file__).resolve().parents[1]
    (root/'demo.toml').write_bytes((repo/'configs/demo.toml').read_bytes())
    runtime=root/'runtime/demo';runtime.mkdir(parents=True)
    book=Ledger(runtime/'account.sqlite','demo');book.account('sample')
    with book.transaction():
        apply_workbench_schema(book.connection);apply_v18_schema(book.connection);apply_v19_schema(book.connection)
    contract=register_contract(book,dict(contract_id='SYNTHETIC-SPY-P100',underlying='SPY',right='PUT',strike=100,
        expiry='2026-12-18',last_trade_at='2026-12-18T21:00:00Z',exercise_cutoff_at='2026-12-18T22:30:00Z',
        listed_at='2026-01-01T00:00:00Z',style='AMERICAN',settlement='PHYSICAL',currency='USD',
        quote_multiplier=100,deliverable_shares=100,deliverable_cash=0,exercise_cash=10000,
        tick_size=.01,revision='synthetic-v1',evidence_hash='synthetic_test_contract_terms'))
    base=dict(effective_at='2026-10-09T19:45:00Z',source='synthetic_test_statements',evidence_type='test')
    book.import_events('sample',[dict(base,event_id='cash',kind='DEPOSIT',amount=30000),
        dict(base,event_id='stock',kind='BUY',symbol='SPY',quantity=200,price=100,settlement_at='2026-10-09T20:00:00Z'),
        dict(base,event_id='put',kind='OPTION_TRADE',contract_version=contract.version_hash,
             action='OPEN',trade_side='BUY',quantity=1,price=2,settlement_at='2026-10-09T20:00:00Z')])
    request=dict(schema_version=1,as_of='2026-10-09T21:00:00Z',ledger_view='restated',ledger_seq=3,
        security_ids={'SPY':'synthetic-security-spy'},inflight_plan_ids=[],allocations=[dict(
        allocation_id='protect-100',parent_id='synthetic-parent',security_id='synthetic-security-spy',
        contract_id=contract.contract_id,contract_version=contract.version_hash,role='put_protection',state='actual',
        share_start=0,share_end=100,contracts=1,shares_per_contract=100,
        valid_from=base['effective_at'],valid_until=contract.exercise_cutoff_at,recorded_at=now_utc())])
    request['knowledge_cutoff']=now_utc();book.close()
    fingerprint=source_fingerprint();checks=[];ids=[]
    identity=dict(schema_version=1,security_id='synthetic-security-spy',instrument_type='etf',
        ticker_history=[dict(ticker='SPY',valid_from='2024-01-01T00:00:00Z',valid_until='2030-01-01T00:00:00Z')],
        exchange='ARCX',calendar='XNYS',timezone='America/New_York',currency='USD',trade_unit='1',
        valid_from='2024-01-01T00:00:00Z',valid_until='2030-01-01T00:00:00Z',
        corporate_action_refs=[],source_qualification_refs=[],source_type='synthetic')
    (root/'security.json').write_text(json.dumps(identity));versions=[]
    for name,commit in [('identity_preview',False),('identity_register',True),('identity_repeat',True)]:
        command=[sys.executable,'-m','personal_quant.cli','--config','demo.toml','security-register','--file','security.json']
        if commit:command.append('--commit')
        process=subprocess.run(command,cwd=root,text=True,capture_output=True,
                               env=dict(os.environ,PYTHONPATH=str(repo/'src')))
        (root/(name+'.stdout')).write_text(process.stdout);(root/(name+'.stderr')).write_text(process.stderr)
        assert process.returncode==0,process.stderr
        body=json.loads(process.stdout);versions.append(body['record']['version_hash'] if commit else body['version_hash'])
        assert not body['executable']
        checks.append(dict(case=name,command=command,exit_code=0))
    assert len(set(versions))==1
    request['security_versions']={'SPY':versions[0]};request['knowledge_cutoff']=now_utc()
    book=Ledger(runtime/'account.sqlite','demo');task_count=book.connection.execute('SELECT count(*) FROM tasks').fetchone()[0];book.close()
    for name,payload,expected in [('read',request,0),('repeat',request,0),('invalid_prefix',dict(request,ledger_seq=999),2),
                                ('invalid_identity',dict(request,security_ids={'SPY':'wrong-id'}),2)]:
        path=root/(name+'.json');path.write_text(json.dumps(payload))
        command=[sys.executable,'-m','personal_quant.cli','--config','demo.toml','hedge-coverage',
                 '--account-id','sample','--file',path.name]
        process=subprocess.run(command,cwd=root,text=True,capture_output=True,
                               env=dict(os.environ,PYTHONPATH=str(repo/'src')))
        (root/(name+'.stdout')).write_text(process.stdout);(root/(name+'.stderr')).write_text(process.stderr)
        assert process.returncode==expected,process.stderr
        body=json.loads(process.stdout if expected==0 else process.stderr)
        if expected==0:
            assert body['actual_protected_shares']=={'synthetic-security-spy':'100'}
            assert not body['executable'] and not body['creates_reservations']
            assert body['security_identity_basis']['SPY']['version_hash']==versions[0]
            ids.append(body['coverage_id'])
        else:assert body['code']==('SECURITY_BINDING_CONFLICT' if name=='invalid_identity' else 'INVALID_LEDGER_SEQUENCE')
        checks.append(dict(case=name,command=command,exit_code=process.returncode))
    book=Ledger(runtime/'account.sqlite','demo')
    assert book.sequence('sample')==3 and book.connection.execute('SELECT count(*) FROM tasks').fetchone()[0]==task_count
    book.close();assert len(set(ids))==1 and source_fingerprint()==fingerprint
    evidence=dict(status='PASSED',checks=checks,source_fingerprint=fingerprint,
                  data_type='synthetic_test_statements',ledger_sequence=3,actual_protected_shares=100,executable=False)
    evidence['security_version']=versions[0];evidence['registry_task_count']=task_count
    (root/'verification.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2))
    print(json.dumps(dict(status='PASSED',checks=len(checks),verification=str(root/'verification.json'))))


if __name__=='__main__':main()
