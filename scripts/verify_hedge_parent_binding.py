"""Actual schema2 allocation CLI checks with a copied synthetic option workspace."""
import argparse
from datetime import timedelta
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from personal_quant.common import now_utc,utc
from personal_quant.hedging.allocation_store import resources
from personal_quant.hedging.securities import register
from personal_quant.options.contracts import OptionContract
from personal_quant.options.data import OptionDataStore
from personal_quant.options.ledger import register_contract
from personal_quant.portfolio import Ledger
from personal_quant.portfolio.schema import apply_workbench_schema,apply_v18_schema,apply_v19_schema
from personal_quant.strategies.archive import source_fingerprint


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--workspace',type=Path,required=True);parser.add_argument('--destination',type=Path,required=True)
    args=parser.parse_args()
    root=args.destination.resolve();root.mkdir(parents=True,exist_ok=False)
    shutil.copytree(args.workspace/'runtime',root/'runtime');shutil.copy2(args.workspace/'demo.toml',root/'demo.toml')
    preview=json.loads((args.workspace/'put.json').read_text())
    book=Ledger(root/'runtime/demo/account.sqlite','demo')
    with book.transaction():
        apply_workbench_schema(book.connection);apply_v18_schema(book.connection);apply_v19_schema(book.connection)
    versions={}
    for symbol in preview['spec']['scope']:
        identity=dict(schema_version=1,security_id='synthetic-'+symbol,instrument_type='etf',
            ticker_history=[dict(ticker=symbol,valid_from='2024-01-01T00:00:00Z',valid_until='2030-01-01T00:00:00Z')],
            exchange='ARCX',calendar='XNYS',timezone='America/New_York',currency='USD',trade_unit=1,
            valid_from='2024-01-01T00:00:00Z',valid_until='2030-01-01T00:00:00Z',corporate_action_refs=[],
            source_qualification_refs=[],source_type='synthetic')
        versions[symbol]=register(book.path.parent,'demo',identity)['record']['version_hash']
    risk=json.loads((book.path.parent/'hedging/exposures'/preview['exposure_id']/'exposure.json').read_text())
    preview['option']['coverage_request']['knowledge_cutoff']=now_utc()
    parent_req=dict(schema_version=1,request_id='strict-option-parent',expected_version=None,
        expected_resource_hash=resources(book,'sample'),preview_request=preview,
        security_ids={s:'synthetic-'+s for s in preview['spec']['scope']},security_versions=versions,
        decision_at=risk['as_of'],knowledge_cutoff=now_utc(),valid_until=(utc(risk['as_of'])+timedelta(days=5)).isoformat(),
        trigger='synthetic_strict_allocation',base_strategy_version='MANUAL_HOLDINGS',timing='historical_research',
        reason='Synthetic strict parent coverage')
    before=book.sequence('sample');book.close();fingerprint=source_fingerprint();checks=[]
    def run(name,command,payload,commit=False,expected=0):
        file=root/(name+'.json');file.write_text(json.dumps(payload))
        cmd=[sys.executable,'-m','personal_quant.cli','--config','demo.toml',command,'--account-id','sample','--file',file.name]
        if commit:cmd+=['--commit']
        result=subprocess.run(cmd,cwd=root,text=True,capture_output=True,
            env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src')))
        (root/(name+'.stdout')).write_text(result.stdout);(root/(name+'.stderr')).write_text(result.stderr)
        assert result.returncode==expected,result.stderr
        checks.append(dict(case=name,command=cmd,exit_code=result.returncode))
        return json.loads(result.stdout if expected==0 else result.stderr)
    parent=run('parent','hedge-intent',parent_req,True)
    assert parent['candidate']['planned_total_packages']=='1'
    c=OptionContract.from_dict(parent['candidate']['selection']['legs'][0]['contract'])
    quote=parent['candidate']['selection']['legs'][0]['reference_quote']
    clock=utc(parent['decision_at'])+timedelta(days=1)
    book=Ledger(root/'runtime/demo/account.sqlite','demo');register_contract(book,c.content())
    facts=[]
    for trade in parent['candidate']['trades']:
        common=dict(event_id='strict-'+trade['kind'],effective_at=clock.isoformat(),settlement_at=clock.isoformat(),
                    source='synthetic_strict_statement',evidence_type='test')
        if trade['kind']=='stock':
            facts.append(dict(common,kind=trade['side'],symbol=trade['symbol'],quantity=trade['quantity'],
                              price=preview['option']['funding_quote']['execution_price']))
        else:
            facts.append(dict(common,kind='OPTION_TRADE',contract_version=c.version_hash,action='OPEN',
                              trade_side=trade['side'],quantity=trade['contracts'],price=quote['ask'],fee=2))
    first_import=book.import_events('sample',facts);repeat_import=book.import_events('sample',facts)
    assert first_import['added']==2 and repeat_import['added']==0
    query=dict(preview['option']['coverage_request'],as_of=clock.isoformat(),knowledge_cutoff=now_utc(),
               ledger_seq=book.sequence('sample'),security_versions=versions,allocations=[])
    allocation=dict(allocation_id='strict-put',parent_id=parent['hedge_id'],security_id='synthetic-SPY',
        contract_id=c.contract_id,contract_version=c.version_hash,role='put_protection',state='actual',
        share_start=0,share_end=100,contracts=1,shares_per_contract=100,valid_from=clock.isoformat(),
        valid_until=c.exercise_cutoff_at,recorded_at=now_utc())
    query['knowledge_cutoff']=now_utc()
    req=dict(schema_version=2,request_id='strict-allocation',expected_version=None,
        expected_resource_hash=resources(book,'sample'),coverage_request=query,changes=[allocation],retire_ids=[],
        parent_versions={'strict-put':parent['version_hash']},reason='Explicit strict selected parent')
    book.close()
    pre=run('preview','hedge-allocation',req)
    assert run('wrong-parent','hedge-allocation',dict(req,parent_versions={'strict-put':'unknown'}),True,2)['code']=='UNKNOWN_HEDGE_PARENT_VERSION'
    saved=run('commit','hedge-allocation',req,True)
    assert pre['version_hash']==saved['version_hash'] and saved['coverage']['actual_protected_shares']['synthetic-SPY']=='100'
    assert run('repeat','hedge-allocation',req,True)==saved
    book=Ledger(root/'runtime/demo/account.sqlite','demo');basis=resources(book,'sample');book.close()
    legacy=dict(req,schema_version=1,request_id='downgrade',expected_version=saved['version_hash'],
                expected_resource_hash=basis);legacy.pop('parent_versions')
    assert run('downgrade','hedge-allocation',legacy,True,2)['code']=='HEDGE_PARENT_BINDINGS_REQUIRED'
    close=dict(schema_version=1,request_id='close-parent',hedge_id=parent['hedge_id'],expected_version=parent['version_hash'],
               expected_resource_hash=basis,action='CANCELLED',reason='Close research, retain facts')
    run('close','hedge-intent-close',close,True)
    book=Ledger(root/'runtime/demo/account.sqlite','demo');basis=resources(book,'sample');book.close()
    next_req=dict(req,request_id='after-close',expected_version=saved['version_hash'],expected_resource_hash=basis)
    assert run('closed-edit','hedge-allocation',next_req,True,2)['code']=='HEDGE_INTENT_CLOSED'
    retired=run('retire','hedge-allocation',dict(next_req,request_id='retire',changes=[],retire_ids=['strict-put'],parent_versions={}),True)
    assert retired['coverage']['actual_protected_shares']['synthetic-SPY']=='0'
    assert retired['coverage']['unallocated_actual_contracts'][0]['unallocated_contracts']=='1'
    book=Ledger(root/'runtime/demo/account.sqlite','demo');assert book.sequence('sample')==before+2;book.close()
    assert source_fingerprint()==fingerprint
    (root/'verification.json').write_text(json.dumps(dict(status='PASSED',checks=checks,
        source_fingerprint=fingerprint,data_type='synthetic',native_facts=2,duplicate_added=0,
        original_sequence=before,final_sequence=before+2,executable=False),ensure_ascii=False,indent=2))
    print(json.dumps(dict(status='PASSED',checks=len(checks),verification=str(root/'verification.json'))))


if __name__=='__main__':main()

