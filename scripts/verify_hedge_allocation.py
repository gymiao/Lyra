"""CLI revision checks on an explicitly synthetic registered-coverage workspace."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from personal_quant.portfolio import Ledger
from personal_quant.hedging.allocation_store import history
from personal_quant.strategies.archive import source_fingerprint


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--workspace',type=Path,required=True)
    parser.add_argument('--destination',type=Path,required=True);args=parser.parse_args()
    root=args.destination.resolve();root.mkdir(parents=True,exist_ok=False)
    shutil.copytree(args.workspace/'runtime',root/'runtime');shutil.copy2(args.workspace/'demo.toml',root/'demo.toml')
    query=json.loads((args.workspace/'read.json').read_text());changes=query.pop('allocations');query['allocations']=[]
    repo=Path(__file__).resolve().parents[1];checks=[];fingerprint=source_fingerprint()

    def run(name,command,expected=0):
        command=[sys.executable,'-m','personal_quant.cli','--config','demo.toml',*command]
        result=subprocess.run(command,cwd=root,text=True,capture_output=True,
                              env=dict(os.environ,PYTHONPATH=str(repo/'src')))
        (root/(name+'.stdout')).write_text(result.stdout);(root/(name+'.stderr')).write_text(result.stderr)
        assert result.returncode==expected,result.stderr
        checks.append(dict(case=name,command=command,exit_code=result.returncode))
        return json.loads(result.stdout if expected==0 else result.stderr)

    basis=run('basis',['hedge-allocation-basis','--account-id','sample'])
    request=dict(schema_version=1,request_id='synthetic-register-protection',expected_version=basis['version_hash'],
        expected_resource_hash=basis['resource_hash'],coverage_request=query,changes=changes,retire_ids=[],
        reason='Synthetic actual position reference; no trading authorization')
    path=root/'allocation.json';path.write_text(json.dumps(request))
    command=['hedge-allocation','--account-id','sample','--file',path.name]
    preview=run('preview',command);committed=run('commit',command+['--commit']);repeated=run('repeat',command+['--commit'])
    assert committed==repeated and committed['version_hash']==preview['version_hash']
    assert not committed['creates_reservations'] and not committed['executable']
    latest=run('latest',['hedge-allocation-basis','--account-id','sample'])
    assert latest['revision']==1 and latest['version_hash']==committed['version_hash']
    duplicate=dict(request,request_id='another-policy',expected_version=latest['version_hash'],
        expected_resource_hash=latest['resource_hash'],changes=[dict(changes[0],allocation_id='different',parent_id='another-parent')])
    (root/'duplicate.json').write_text(json.dumps(duplicate))
    error=run('duplicate',['hedge-allocation','--account-id','sample','--file','duplicate.json','--commit'],2)
    assert error['code']=='DUPLICATE_PROTECTION'
    (root/'conflict.json').write_text(json.dumps(dict(request,reason='Different content using same request')))
    error=run('conflict',['hedge-allocation','--account-id','sample','--file','conflict.json','--commit'],2)
    assert error['code']=='ALLOCATION_REQUEST_CONFLICT'
    book=Ledger(root/'runtime/demo/account.sqlite','demo')
    assert book.sequence('sample')==3 and len(history(book,'sample'))==1
    book.close();assert source_fingerprint()==fingerprint
    (root/'verification.json').write_text(json.dumps(dict(status='PASSED',checks=checks,source_fingerprint=fingerprint,
        data_type='synthetic_test_statements',ledger_sequence=3,revision=1,executable=False),ensure_ascii=False,indent=2))
    print(json.dumps(dict(status='PASSED',checks=len(checks),verification=str(root/'verification.json'))))


if __name__=='__main__':main()
