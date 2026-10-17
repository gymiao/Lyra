"""Run with the clean prefix's Python -I, using only installed application code."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import personal_quant
from personal_quant.common import now_utc,write_json
from personal_quant.strategies.archive import source_fingerprint


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--destination',type=Path,required=True)
    parser.add_argument('--engine-root',type=Path,required=True)
    parser.add_argument('--dotnet',type=Path,required=True)
    args=parser.parse_args()
    package=Path(personal_quant.__file__).absolute()
    assert 'site-packages' in package.parts,'Must use installed wheel, not editable/source imports'
    out=args.destination.absolute();out.mkdir(parents=True,exist_ok=False)
    client=out/'client';client.mkdir();assets=out/'configs';assets.mkdir()
    for name in ('demo.toml','v195-etf-workspace.json','v195-options-workspace.json','v195-option-setup.json'):
        shutil.copyfile(args.project/'configs'/name,assets/name)
    source=source_fingerprint();checks=[]
    environment=dict(os.environ,MPLCONFIGDIR=str(out/'mpl-cache'),PYTHONDONTWRITEBYTECODE='1')
    def cli(name,*arguments):
        command=[sys.executable,'-I','-m','personal_quant','--config',str(assets/'demo.toml'),*map(str,arguments)]
        process=subprocess.run(command,cwd=client,env=environment,text=True,capture_output=True)
        (out/(name+'.stdout.json')).write_text(process.stdout)
        (out/(name+'.stderr.log')).write_text(process.stderr)
        checks.append({'name':name,'command':command,'exit_code':process.returncode})
        assert process.returncode==0,(name,process.stderr)
        return json.loads(process.stdout)
    etf=out/'etf'
    cli('etf-init','workspace','init','--workspace',etf,'--spec',assets/'v195-etf-workspace.json')
    run=cli('etf-start','simulation','start','--workspace',etf)
    limited=cli('etf-budget','simulation','batch','--workspace',etf,'--run-id',run['run_id'],'--through','2024-12-31','--max-sessions','1','--max-seconds','120','--min-free-bytes','0')
    assert limited['batch']['reason']=='BATCH_SESSION_LIMIT' and limited['through_session']=='2024-07-01'
    finished=cli('etf-complete','simulation','batch','--workspace',etf,'--run-id',run['run_id'],'--through','2024-12-31','--max-sessions','256')
    assert finished['status']=='COMPLETED'
    again=cli('etf-repeat','simulation','resume','--workspace',etf,'--run-id',run['run_id'],'--through','2024-12-31')
    assert again['events']==finished['events'] and again['status']=='COMPLETED' and again['details']['equity']==finished['details']['equity']
    option=out/'options'
    cli('option-init','workspace','init','--workspace',option,'--spec',assets/'v195-options-workspace.json')
    setup=cli('option-prepare','simulation','prepare','--workspace',option,'--file',assets/'v195-option-setup.json')
    run=cli('option-start','simulation','start','--workspace',option,'--file',setup['request_file'],
        '--engine-root',args.engine_root,'--dotnet',args.dotnet,'--fee-per-contract','2')
    market=cli('option-close','simulation','batch','--workspace',option,'--run-id',run['run_id'],'--through',setup['last_settlement_session'])
    assert market['batch']['reason']=='BATCH_MARKET_BOUNDARY' and market['through_session']==setup['last_market_session']
    terminal=cli('option-settle','simulation','batch','--workspace',option,'--run-id',run['run_id'],'--through',setup['last_settlement_session'])
    assert terminal['status']=='COMPLETED' and float(terminal['details']['equity'])==99978 and terminal['events']==7
    repeated=cli('option-repeat','simulation','resume','--workspace',option,'--run-id',run['run_id'],'--through',setup['last_settlement_session'])
    assert repeated['repeated'] and repeated['events']==7
    db=sqlite3.connect((option/'runtime/demo/account.sqlite').as_uri()+'?mode=ro',uri=True)
    try:assert db.execute("SELECT count(*) FROM events WHERE json_extract(payload,'$.kind')='DEPOSIT'").fetchone()[0]==1
    finally:db.close()
    cli('option-diagnostic','workspace','diagnostic','--workspace',option,'--destination',out/'diagnostic')
    assert source_fingerprint()==source
    write_json(out/'verification.json',{'status':'PASSED','source_hash':source,'source_unchanged':True,
        'python':sys.executable,'prefix':sys.prefix,'package':str(package),'checks':checks,'completed_at':now_utc(),
        'etf_equity':finished['details']['equity'],'option_equity':terminal['details']['equity'],
        'option_events':7,'data_type':'synthetic','complete_version':False,
        'scope':'clean complete dependencies + installed wheel, external pinned tools, ETF and option study end-to-end'})
    print(json.dumps({'status':'PASSED','verification':str(out/'verification.json')}))


if __name__=='__main__':main()
