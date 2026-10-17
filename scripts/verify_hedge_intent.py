"""CLI parent binding checks using frozen synthetic risk, never broker orders."""
import argparse
from datetime import timedelta
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from personal_quant.common import now_utc,utc
from personal_quant.portfolio import Ledger
from personal_quant.hedging.allocation_store import resources
from personal_quant.hedging.intents import records
from personal_quant.hedging.securities import register
from personal_quant.strategies.archive import source_fingerprint


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--workspace',type=Path,required=True)
    parser.add_argument('--destination',type=Path,required=True);args=parser.parse_args()
    root=args.destination.resolve();root.mkdir(parents=True,exist_ok=False)
    shutil.copytree(args.workspace/'runtime',root/'runtime');shutil.copy2(args.workspace/'demo.toml',root/'demo.toml')
    candidate=json.loads((args.workspace/'preview.json').read_text());scope=candidate['spec']['scope']
    assert len(scope)==1;symbol=scope[0];book=Ledger(root/'runtime/demo/account.sqlite','demo')
    identity=dict(schema_version=1,security_id='synthetic-'+symbol,instrument_type='etf',
        ticker_history=[dict(ticker=symbol,valid_from='2024-01-01T00:00:00Z',valid_until='2030-01-01T00:00:00Z')],
        exchange='ARCX',calendar='XNYS',timezone='America/New_York',currency='USD',trade_unit=1,
        valid_from='2024-01-01T00:00:00Z',valid_until='2030-01-01T00:00:00Z',
        corporate_action_refs=[],source_qualification_refs=[],source_type='synthetic')
    registered=register(book.path.parent,'demo',identity)
    risk=json.loads((book.path.parent/'hedging/exposures'/candidate['exposure_id']/'exposure.json').read_text())
    request=dict(schema_version=1,request_id='freeze-parent',expected_version=None,expected_resource_hash=resources(book,'sample'),
        preview_request=candidate,security_ids={symbol:identity['security_id']},security_versions={symbol:registered['record']['version_hash']},
        decision_at=risk['as_of'],knowledge_cutoff=now_utc(),valid_until=(utc(risk['as_of'])+timedelta(days=5)).isoformat(),
        trigger='synthetic_research',base_strategy_version='MANUAL_HOLDINGS',timing='historical_research',reason='Explicit synthetic parent reconstruction')
    seq=book.sequence('sample');book.close();fingerprint=source_fingerprint();checks=[]
    def run(name,payload=None,*,commit=False,expected=0):
        command=[sys.executable,'-m','personal_quant.cli','--config','demo.toml']
        if payload is None:command+=['hedge-intents','--account-id','sample']
        else:
            file=root/(name+'.json');file.write_text(json.dumps(payload));command+=['hedge-intent','--account-id','sample','--file',file.name]
            if commit:command+=['--commit']
        result=subprocess.run(command,cwd=root,text=True,capture_output=True,env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src')))
        (root/(name+'.stdout')).write_text(result.stdout);(root/(name+'.stderr')).write_text(result.stderr)
        assert result.returncode==expected,result.stderr
        checks.append(dict(case=name,command=command,exit_code=result.returncode))
        return json.loads(result.stdout if expected==0 else result.stderr)
    preview=run('preview',request);first=run('commit',request,commit=True);repeat=run('repeat',request,commit=True)
    assert first==repeat and preview['version_hash']==first['version_hash'] and not first['executable']
    assert run('list')['intents']==[first]
    book=Ledger(root/'runtime/demo/account.sqlite','demo');basis=resources(book,'sample');book.close()
    revised=dict(request,request_id='changed-parameters',expected_version=first['version_hash'],expected_resource_hash=basis)
    revised['preview_request']=dict(candidate,spec=dict(candidate['spec'],target_beta=.7))
    assert run('same-policy-version',revised,commit=True,expected=2)['code']=='HEDGE_POLICY_VERSION_CONFLICT'
    assert run('request-conflict',dict(request,reason='same ID, new content'),commit=True,expected=2)['code']=='HEDGE_INTENT_REQUEST_CONFLICT'
    revised['preview_request']['spec']['version']='next';revised['expected_version']=None
    assert run('scope-conflict',revised,commit=True,expected=2)['code']=='HEDGE_SCOPE_CONFLICT'
    book=Ledger(root/'runtime/demo/account.sqlite','demo')
    assert book.sequence('sample')==seq and len(records(book,'sample'))==1;book.close()
    assert source_fingerprint()==fingerprint
    (root/'verification.json').write_text(json.dumps(dict(status='PASSED',checks=checks,source_fingerprint=fingerprint,
        data_type='synthetic_historical_reconstruction',ledger_sequence=seq,revision=1,executable=False),ensure_ascii=False,indent=2))
    print(json.dumps(dict(status='PASSED',checks=len(checks),verification=str(root/'verification.json'))))


if __name__=='__main__':main()
