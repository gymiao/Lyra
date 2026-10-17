"""Archive actual read-only CLI checks from a synthetic risk test workspace."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from personal_quant.data.store import DataStore
from personal_quant.portfolio import Ledger
from personal_quant.strategies.archive import source_fingerprint
from personal_quant.hedging.archive import load


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--workspace',type=Path,required=True)
    parser.add_argument('--destination',type=Path,required=True);args=parser.parse_args()
    source=args.workspace;request=json.loads((source/'risk.json').read_text())
    for key in ('valuation_snapshot_id','return_snapshot_id'):
        assert DataStore(source/'runtime/demo/data').load(request[key])[1]['data_type']=='synthetic'
    destination=Path(os.path.abspath(args.destination));shutil.copytree(source,destination)
    fingerprint=source_fingerprint();checks=[];ids=[]
    book=Ledger(destination/'runtime/demo/account.sqlite','demo')
    before=(book.sequence('sample'),book.connection.execute('SELECT count(*) FROM tasks').fetchone()[0]);book.close()
    for name,known in [('risk',False),('repeat',False),('unreceived_ledger',True)]:
        file=destination/(name+'.json');file.write_text(json.dumps({**request,'ledger_view':'known_then'} if known else request))
        command=[sys.executable,'-m','personal_quant.cli','--config','demo.toml','hedge-exposure','--account-id','sample','--file',file.name]
        run=subprocess.run(command,cwd=destination,capture_output=True,text=True,env=os.environ.copy())
        (destination/(name+'.stdout.json')).write_text(run.stdout);(destination/(name+'.stderr.json')).write_text(run.stderr)
        assert run.returncode==(2 if known else 0)
        result=json.loads(run.stderr if known else run.stdout)
        if known:assert result['code']=='LEDGER_NOT_KNOWN'
        else:
            assert result['status']=='COMPLETE' and abs(float(result['risk']['beta_amount'])-35000)<1e-6
            assert abs(float(result['risk']['account_beta'])-7/6)<1e-10 and not result['executable']
            ids.append(result['exposure_id'])
        checks.append({'case':name,'command':command,'exit_code':run.returncode,'status':result['status']})
    for name in ('archive','archive_repeat'):
        command=[sys.executable,'-m','personal_quant.cli','--config','demo.toml','hedge-exposure',
            '--account-id','sample','--file','risk.json','--archive']
        run=subprocess.run(command,cwd=destination,capture_output=True,text=True,env=os.environ.copy())
        (destination/(name+'.stdout.json')).write_text(run.stdout);(destination/(name+'.stderr.json')).write_text(run.stderr)
        assert run.returncode==0,run.stderr
        result=json.loads(run.stdout);assert result['exposure_id']==ids[0]
        assert load(destination/'runtime/demo/hedging/exposures',ids[0])['exposure_id']==ids[0]
        checks.append({'case':name,'command':command,'exit_code':run.returncode,'status':result['status']})
    for name,arguments in [('backup',['--config','demo.toml','backup-bundle','--destination','bundle']),
        ('verify',['verify-backup','--source','bundle','--environment','demo']),
        ('restore',['restore','--source','bundle','--destination','restored','--environment','demo'])]:
        command=[sys.executable,'-m','personal_quant.cli',*arguments]
        run=subprocess.run(command,cwd=destination,capture_output=True,text=True,env=os.environ.copy())
        (destination/(name+'.stdout.json')).write_text(run.stdout);(destination/(name+'.stderr.json')).write_text(run.stderr)
        assert run.returncode==0,run.stderr
        checks.append({'case':name,'command':command,'exit_code':run.returncode,'status':'SUCCESS'})
    assert load(destination/'restored/runtime/demo/hedging/exposures',ids[0])==load(destination/'runtime/demo/hedging/exposures',ids[0])
    book=Ledger(destination/'runtime/demo/account.sqlite','demo')
    try:assert before==(book.sequence('sample'),book.connection.execute('SELECT count(*) FROM tasks').fetchone()[0])
    finally:book.close()
    assert len(set(ids))==1 and source_fingerprint()==fingerprint
    (destination/'verification.json').write_text(json.dumps({'status':'PASSED','checks':checks,
        'source_fingerprint':fingerprint,'data_type':'synthetic_restated_account_risk',
        'ledger_sequence_and_tasks_unchanged':True,'beta_amount':35000,'account_beta':7/6,
        'limits':'Read-only risk; no hedge quantity, execution plan, genuine options or model qualification.'},ensure_ascii=False,indent=2))
    print(json.dumps({'status':'PASSED','checks':len(checks),'verification':str(destination/'verification.json')}))


if __name__=='__main__':main()
