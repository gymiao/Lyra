"""Verify real CLI entrypoints against an isolated, synthetic frozen fixture.

The fixture is produced by test_options_daily_v19, never a real account.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from personal_quant.options.data import OptionDataStore
from personal_quant.portfolio import Ledger
from personal_quant.strategies.archive import source_fingerprint


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--base',type=Path,required=True)
    parser.add_argument('--destination',type=Path,required=True)
    args=parser.parse_args();destination=args.destination.resolve()
    destination.mkdir(parents=True,exist_ok=False)
    project=Path(__file__).resolve().parents[1];source_hash=source_fingerprint();checks=[]
    for kind,source,clock,expected_equity,expected_sequence in (
        ('OPEN',args.base/'unopened','2024-11-01T20:01:00Z',99993,2),
        ('CLOSE',args.base/'runtime/demo','2024-12-02T21:01:00Z',99986,3)):
        work=destination/kind.lower();root=work/'runtime/demo';shutil.copytree(source,root)
        (work/'demo.toml').write_bytes((project/'configs/demo.toml').read_bytes())
        book=Ledger(root/'account.sqlite','demo')
        try:
            if kind=='OPEN':
                identity=book.connection.execute('SELECT plan_id FROM option_plans').fetchone()[0]
                request={'plan_id':identity,'expected_sequence':1}
                execution_at='2024-11-01T20:00:00+00:00'
            else:
                freeze=json.loads(book.connection.execute("SELECT details FROM tasks WHERE task_id LIKE 'option-exit-freeze:%'").fetchone()[0])
                request={'exit_id':freeze['proposal']['exit_id'],'expected_sequence':2}
                execution_at='2024-12-02T21:00:00+00:00'
            store=OptionDataStore(root/'options/chains');matches=[]
            for path in store.root.iterdir():
                if len(path.name)!=64:continue
                _,rows,_,_=store.load(path.name)
                from personal_quant.common import utc
                if any(utc(row['exchange_timestamp'])==utc(execution_at) for row in rows):matches.append(path.name)
            assert len(matches)==1,matches
            request.update(report_id='comparison',execution_snapshot_id=matches[0],as_of=clock)
        finally:book.close()
        cases=[('wrong_clock',{**request,'as_of':'2024-12-03T21:01:00Z'},False),
               ('execute',request,True),('repeat',request,True)]
        reports=[]
        for name,item,success in cases:
            file=work/(name+'.json');file.write_text(json.dumps([{'kind':kind,'request':item}]))
            command=[sys.executable,'-m','personal_quant.cli','--config','demo.toml','daily',
                '--account-id','sample','--as-of',clock,'--option-tasks',file.name]
            run=subprocess.run(command,cwd=work,env=os.environ.copy(),capture_output=True,text=True)
            (work/(name+'.stdout.json')).write_text(run.stdout)
            (work/(name+'.stderr.log')).write_text(run.stderr)
            assert run.returncode==3,(kind,name,run.returncode,run.stderr)
            result=json.loads(run.stdout);execution=result['option_execution']
            assert result['status']=='BLOCKED' # Stock signal inputs are intentionally absent.
            assert execution['status']==('SUCCESS' if success else 'BLOCKED')
            if not success:assert execution['errors'][0]['code']=='OPTION_PROCESSING_TIME_MISMATCH'
            book=Ledger(root/'account.sqlite','demo')
            try:
                seq=book.sequence('sample');assert seq==(expected_sequence if success else expected_sequence-1)
                if success:
                    audit=execution['results'][0]['audit'];assert float(audit['account']['equity'])==expected_equity
                    reports.append(result['report_id'])
            finally:book.close()
            checks.append({'kind':kind,'case':name,'command':command,'exit_code':run.returncode,
                'option_status':execution['status'],'ledger_sequence':seq})
        assert len(set(reports))==1
    assert source_fingerprint()==source_hash
    result={'status':'PASSED','source_fingerprint':source_hash,'checks':checks,
        'data_type':'synthetic_historical_demonstration',
        'limits':'No genuine options or broker permissions; overall daily blocked on absent stock inputs.'}
    (destination/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps({'status':'PASSED','checks':len(checks),'verification':str(destination/'verification.json')}))


if __name__=='__main__':main()
