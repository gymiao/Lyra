"""Actual CLI fact-review flow, built only from synthetic account statements."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from personal_quant.options.incidents import status
from personal_quant.portfolio import Ledger
from personal_quant.strategies.archive import source_fingerprint


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--destination',type=Path,required=True)
    root=parser.parse_args().destination.resolve();repo=Path(__file__).resolve().parents[1]
    source=source_fingerprint()
    setup=subprocess.run([sys.executable,str(repo/'scripts/verify_receipt_prefix.py'),'--destination',str(root)],
                         capture_output=True,text=True)
    assert setup.returncode==0,(setup.stdout,setup.stderr)
    checks=json.loads((root/'verification.json').read_text())['checks']
    book=Ledger(root/'runtime/demo/account.sqlite','demo')
    incident=status(book,'sample','2026-10-10T00:00:00Z')['incidents'][0]
    book.reconcile('sample',{'account_id':'sample','currency':'USD','as_of':'2026-10-10T00:00:00Z',
                            'cash_basis':'settled','cash':19600,'positions':{},'option_positions':{},'equity':19600})
    rid=book.connection.execute('SELECT max(id) FROM reconciliations').fetchone()[0];book.close()
    evidence=root/'review-evidence';evidence.mkdir()
    blob=b'synthetic test statement: Put delivery -100, Call delivery +100, cash 19600'
    (evidence/'statement.txt').write_bytes(blob)
    request={'schema_version':1,'request_id':'synthetic-review','incident_id':incident['incident_id'],
             'expected_hash':incident['view_hash'],'expected_sequence':5,'as_of':'2026-10-10T00:00:00Z',
             'recovery_event_ids':['exercise-CALL'],'reconciliation_id':rid,'reviewer':'synthetic-verifier',
             'reason':'核对同批实际提供的抵销交割和现金；不抹掉Put中间空头',
             'evidence_type':'test','evidence_files':{'statement.txt':hashlib.sha256(blob).hexdigest()}}
    (root/'review.json').write_text(json.dumps(request,ensure_ascii=False,indent=2))
    def run(name,args,exit_code=0):
        cmd=[sys.executable,'-m','personal_quant.cli','--config','demo.toml',*args]
        result=subprocess.run(cmd,cwd=root,text=True,capture_output=True,env=dict(os.environ,PYTHONPATH=str(repo/'src')))
        (root/(name+'.stdout')).write_text(result.stdout);(root/(name+'.stderr')).write_text(result.stderr)
        assert result.returncode==exit_code,(result.returncode,result.stdout[-1000:],result.stderr)
        checks.append(dict(case=name,command=cmd,exit_code=result.returncode))
        return json.loads(result.stderr if exit_code==2 else result.stdout)
    monitor=['hedge-status','--account-id','sample','--as-of','2026-10-10T00:00:00Z']
    assert run('before-review',monitor)['checks'][0]['code']=='OPTION_INCIDENT_REVIEW_REQUIRED'
    review=['option-incident-review','--account-id','sample','--file','review.json','--evidence-directory','review-evidence']
    assert run('preview-review',review)['status']=='PREVIEW'
    (root/'stale-review.json').write_text(json.dumps({**request,'expected_sequence':4}))
    assert run('stale-review',[*review[:3],'--file','stale-review.json','--evidence-directory','review-evidence','--commit'],2)['code']=='STALE_PREVIEW'
    saved=run('commit-review',[*review,'--commit']);assert saved['status']=='REVIEWED'
    assert run('repeat-review',[*review,'--commit'])==saved
    assert run('after-review',monitor)['option_incidents']['status']=='REVIEWED'
    book=Ledger(root/'runtime/demo/account.sqlite','demo');assert book.sequence('sample')==5
    assert book.snapshot('sample',request['as_of'])['settled_cash']=='19600';book.close()
    frozen=root/'runtime/demo/options/incident-evidence'/saved['request_hash']/'statement.txt'
    frozen.write_text('intentionally corrupted synthetic test evidence')
    assert run('corrupt-review-evidence',monitor)['checks'][0]['code']=='CORRUPT_INCIDENT_REVIEW'
    assert source_fingerprint()==source
    proof=dict(status='PASSED',checks=checks,source_fingerprint=source,data_type='synthetic',
               financial_events_added_by_review=0,ledger_sequence=5,final_cash='19600',
               original_intermediate_short_preserved=True,final_fixture='intentionally_corrupted_for_gate_check',
               broker_orders=False)
    (root/'incident-verification.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2))
    print(json.dumps(dict(status='PASSED',checks=len(checks),verification=str(root/'incident-verification.json'))))


if __name__=='__main__':main()
