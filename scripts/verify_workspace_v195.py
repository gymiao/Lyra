"""Public workspace CLI, complete ETF path, repeat and backup/restore evidence."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from personal_quant.common import digest,now_utc,write_json
from personal_quant.strategies.archive import source_fingerprint
from personal_quant.workspace.service import status
from personal_quant.portfolio.report import load_account_report


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--destination',type=Path,required=True);args=parser.parse_args()
    repo=Path(__file__).absolute().parents[1];writable=Path('/mnt/c/quant/project/lyra')
    if writable.exists() and writable.samefile(repo):repo=writable
    root=args.destination.absolute();root.mkdir(parents=True,exist_ok=False)
    fingerprint=source_fingerprint();checks=[];env=dict(os.environ,MPLCONFIGDIR='/tmp/lyrax-mpl',PYTHONDONTWRITEBYTECODE='1')
    def cli(name,*arguments):
        command=[sys.executable,'-m','personal_quant','--config',str(repo/'configs/demo.toml'),*map(str,arguments)]
        process=subprocess.run(command,cwd=repo,env=env,capture_output=True,text=True)
        (root/(name+'.stdout.json')).write_text(process.stdout);(root/(name+'.stderr.log')).write_text(process.stderr)
        checks.append({'name':name,'command':command,'exit_code':process.returncode})
        assert process.returncode==0,(name,process.stderr)
        return json.loads(process.stdout)
    workspace=root/'workspace';spec=repo/'configs/v195-etf-workspace.json'
    first=cli('init','workspace','init','--workspace',workspace,'--spec',spec)
    repeated=cli('init-repeat','workspace','init','--workspace',workspace,'--spec',spec)
    assert first['identity']['workspace_id']==repeated['identity']['workspace_id'] and repeated['events']==1
    run=cli('start','simulation','start','--workspace',workspace)
    prefix=cli('prefix','simulation','resume','--workspace',workspace,'--run-id',run['run_id'],'--through','2024-08-02')
    assert prefix['status']=='PAUSED' and prefix['events']>1,(prefix['status'],prefix['details'])
    final=cli('complete','simulation','resume','--workspace',workspace,'--run-id',run['run_id'],'--through','2024-12-31')
    assert final['status']=='COMPLETED',final['details']
    repeated=cli('repeat','simulation','resume','--workspace',workspace,'--run-id',run['run_id'],'--through','2024-12-31')
    assert final['events']==repeated['events'] and final['details']['equity']==repeated['details']['equity']
    report=load_account_report(workspace/'runtime/demo/reports/account-latest')
    assert report['net_contributions']=='100000' and report['equity'] is not None
    # Existing backup CLI requires its source working directory; supply explicit
    # absolute config/runtime paths through a workspace cwd subprocess.
    command=[sys.executable,'-m','personal_quant','--config',str(workspace/'config.json'),'backup-bundle','--destination',str(root/'backup')]
    result=subprocess.run(command,cwd=workspace,env=env,capture_output=True,text=True)
    (root/'backup.stdout.json').write_text(result.stdout);(root/'backup.stderr.log').write_text(result.stderr)
    assert result.returncode==0,result.stderr
    cli('restore','restore','--source',root/'backup','--destination',root/'restored','--environment','demo')
    restored=status(root/'restored');assert restored['events']==final['events']
    assert restored['identity']==first['identity']
    proof={'status':'PASSED','source_hash':fingerprint,'source_unchanged':source_fingerprint()==fingerprint,
           'data_type':'synthetic_historical_simulation','checks':checks,'account':report,
           'repeated_events_added':repeated['events']-final['events'],'restored_events':restored['events'],'completed_at':now_utc()}
    assert proof['source_unchanged'];write_json(root/'verification.json',proof)
    print(json.dumps({'status':'PASSED','verification':str(root/'verification.json'),'events':final['events']}))

if __name__=='__main__':main()
