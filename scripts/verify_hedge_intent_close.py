"""Actual CLI checks of append-only research closure, using an isolated frozen fixture."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from personal_quant.hedging.allocation_store import resources
from personal_quant.hedging.intents import records
from personal_quant.hedging.intent_actions import history
from personal_quant.portfolio import Ledger
from personal_quant.strategies.archive import source_fingerprint


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--workspace',type=Path,required=True)
    parser.add_argument('--destination',type=Path,required=True)
    args=parser.parse_args()
    root=args.destination.resolve();root.mkdir(parents=True,exist_ok=False)
    shutil.copytree(args.workspace/'runtime',root/'runtime')
    shutil.copy2(args.workspace/'demo.toml',root/'demo.toml')
    book=Ledger(root/'runtime/demo/account.sqlite','demo')
    originals=records(book,'sample');assert len(originals)==1 and not history(book,'sample')
    original=originals[0];before=resources(book,'sample');seq=book.sequence('sample');book.close()
    request=dict(schema_version=1,request_id='close-synthetic-parent',hedge_id=original['hedge_id'],
                 expected_version=original['version_hash'],expected_resource_hash=before,
                 action='EXPIRED',reason='Explicit closure of frozen historical research decision')
    fingerprint=source_fingerprint();checks=[]
    def run(name,payload=None,commit=False,expected=0):
        command=[sys.executable,'-m','personal_quant.cli','--config','demo.toml']
        if payload is None:
            command+=['hedge-intents','--account-id','sample']
        else:
            file=root/(name+'.json');file.write_text(json.dumps(payload))
            command+=['hedge-intent-close','--account-id','sample','--file',file.name]
            if commit:command+=['--commit']
        result=subprocess.run(command,cwd=root,text=True,capture_output=True,
                              env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src')))
        (root/(name+'.stdout')).write_text(result.stdout);(root/(name+'.stderr')).write_text(result.stderr)
        assert result.returncode==expected,result.stderr
        checks.append(dict(case=name,command=command,exit_code=result.returncode))
        return json.loads(result.stdout if expected==0 else result.stderr)
    preview=run('preview',request)
    book=Ledger(root/'runtime/demo/account.sqlite','demo')
    assert resources(book,'sample')==before and history(book,'sample')==[];book.close()
    assert run('stale',dict(request,expected_resource_hash='stale'),True,2)['code']=='STALE_HEDGE_RESOURCES'
    closed=run('commit',request,True)
    assert preview['proposed_status']==closed['status']=='EXPIRED'
    assert run('repeat',request,True)==closed
    listed=run('list')
    assert listed['intents']==originals and listed['closures']==[closed]
    assert run('request-conflict',dict(request,reason='different'),True,2)['code']=='HEDGE_INTENT_ACTION_REQUEST_CONFLICT'
    book=Ledger(root/'runtime/demo/account.sqlite','demo');after=resources(book,'sample');book.close()
    assert run('already-closed',dict(request,request_id='again',expected_resource_hash=after),True,2)['code']=='HEDGE_INTENT_CLOSED'
    book=Ledger(root/'runtime/demo/account.sqlite','demo')
    assert book.sequence('sample')==seq and resources(book,'sample')==after and records(book,'sample')==originals
    book.close();assert source_fingerprint()==fingerprint
    proof=dict(status='PASSED',source_fingerprint=fingerprint,data_type='synthetic_historical_reconstruction',
               checks=checks,ledger_sequence=seq,releases_reservations=False,cancels_broker_orders=False)
    (root/'verification.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2))
    print(json.dumps(dict(status='PASSED',checks=len(checks),verification=str(root/'verification.json'))))


if __name__=='__main__':main()

