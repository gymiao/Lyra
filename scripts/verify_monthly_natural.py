"""Actual CLI tests of native LEAN expiry/exercise/assignment account bridges."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from personal_quant.strategies.archive import source_fingerprint

def main():
    p=argparse.ArgumentParser();p.add_argument('--workspace',type=Path,required=True)
    p.add_argument('--engine-root',type=Path,required=True);p.add_argument('--dotnet',type=Path,required=True)
    args=p.parse_args();root=args.workspace.absolute();root.mkdir(parents=True)
    project=Path(__file__).resolve().parents[1];fingerprint=source_fingerprint();checks=[]
    for case in json.loads((project/'examples/options/monthly-natural-fixtures.json').read_text()):
        target=root/case['name'];target.mkdir()
        (target/'request.json').write_text(json.dumps(case['request']))
        (target/'demo.toml').write_bytes((project/'configs/demo.toml').read_bytes())
        command=[sys.executable,'-m','personal_quant.cli','--config','demo.toml','options','--action','monthly-replay',
            '--file','request.json','--engine-root',str(args.engine_root.absolute()),'--dotnet',str(args.dotnet.absolute()),
            '--destination',str(target/'engine'),'--capital','100000','--fee-per-contract','2']
        result=subprocess.run(command,cwd=target,capture_output=True,text=True,
            env=dict(os.environ,PYTHONPATH=str(project/'src')))
        (target/'stdout.json').write_text(result.stdout);(target/'stderr.log').write_text(result.stderr)
        assert result.returncode==0,result.stderr
        out=json.loads(result.stdout)
        assert out['status']=='PASSED' and out['final_lifecycle']=='natural_expiry'
        assert float(out['actual_equity'])==case['expected_equity']
        assert float(out['ledger_bridge']['equity'])==case['expected_equity']
        assert out['duplicate_events_added']==0 and not out['ledger_bridge']['positions'] and not out['ledger_bridge']['option_positions']
        events=json.loads((target/'engine/engine-events.json').read_text())
        native=[e for e in events if e['order_type']=='OptionExercise' and e['symbol']==e['order_symbol']]
        assert len(native)==len(case['request']['signals'][-1]['selection']['legs'])
        assert all(abs(e['quantity'])==2 for e in native)
        assert len(out['lifecycle_receipts'])==len(native)
        checks.append(dict(name=case['name'],command=command,exit_code=0,
            expected_equity=case['expected_equity'],native_lifecycle=native,duplicate_events_added=0))
    assert fingerprint==source_fingerprint()
    path=root/'verification.json';path.write_text(json.dumps(dict(status='PASSED',source_fingerprint=fingerprint,
        data_type='synthetic_natural_expiry',checks=checks,no_user_account_writes=True),ensure_ascii=False,indent=2))
    print(json.dumps(dict(status='PASSED',checks=len(checks),verification=str(path))))

if __name__=='__main__':main()

