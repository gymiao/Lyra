"""Actual read-only hedge-status CLI checks on a copied synthetic account."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from personal_quant.common import now_utc
from personal_quant.hedging.allocation_store import latest,resources
from personal_quant.portfolio import Ledger
from personal_quant.strategies.archive import source_fingerprint


def main():
    p=argparse.ArgumentParser();p.add_argument('--workspace',type=Path,required=True)
    p.add_argument('--destination',type=Path,required=True);args=p.parse_args()
    root=args.destination.resolve();root.mkdir(parents=True,exist_ok=False)
    shutil.copytree(args.workspace/'runtime',root/'runtime')
    shutil.copy2(args.workspace/'demo.toml',root/'demo.toml')
    book=Ledger(root/'runtime/demo/account.sqlite','demo')
    allocation=latest(book,'sample');assert allocation['schema_version']==2
    clock=allocation['coverage_request']['as_of']
    before=resources(book,'sample');seq=book.sequence('sample');book.close()
    fingerprint=source_fingerprint();checks=[]
    def run(name,as_of):
        cmd=[sys.executable,'-m','personal_quant.cli','--config','demo.toml','hedge-status','--account-id','sample','--as-of',as_of]
        r=subprocess.run(cmd,cwd=root,text=True,capture_output=True,
            env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src')))
        (root/(name+'.stdout')).write_text(r.stdout);(root/(name+'.stderr')).write_text(r.stderr)
        assert r.returncode==0,r.stderr
        checks.append(dict(case=name,command=cmd,exit_code=r.returncode))
        return json.loads(r.stdout)
    historical=run('historical',clock);repeat=run('repeat',clock)
    assert historical['status']==repeat['status']=='SUCCESS'
    assert historical['parents']==repeat['parents'] and historical['allocation_archive']==allocation
    assert historical['current_coverage']['unallocated_actual_contracts'][0]['unallocated_contracts']=='1'
    overdue=run('unresolved-expiry','2026-10-10T00:00:00Z')
    assert overdue['status']=='BLOCKED'
    assert any(c['code']=='HEDGE_EXPIRED_POSITION_UNRESOLVED' for c in overdue['checks'])
    book=Ledger(root/'runtime/demo/account.sqlite','demo')
    assert resources(book,'sample')==before and book.sequence('sample')==seq
    book.connection.execute('INSERT INTO tasks VALUES(?,?,?,?)',
        ('hedge-intent:broken','DRAFT','{"bad":true}',now_utc()))
    changed=resources(book,'sample');book.close()
    broken=run('corrupt-reference',clock)
    assert broken['status']=='BLOCKED' and broken['checks'][0]['code']=='CORRUPT_HEDGE_INTENT'
    book=Ledger(root/'runtime/demo/account.sqlite','demo')
    assert resources(book,'sample')==changed and book.sequence('sample')==seq;book.close()
    assert source_fingerprint()==fingerprint
    proof=dict(status='PASSED',checks=checks,source_fingerprint=fingerprint,data_type='synthetic',
               ledger_sequence=seq,diagnostic_reads_write_tasks=False,creates_reservations=False,
               browser_validation='not_performed_by_this_script')
    (root/'verification.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2))
    print(json.dumps(dict(status='PASSED',checks=len(checks),verification=str(root/'verification.json'))))


if __name__=='__main__':main()

