"""Verify the actual monthly CLI and save source-bound engine evidence."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from personal_quant.strategies.archive import source_fingerprint
from personal_quant.options.monthly_report import engine_curve

def main():
    p=argparse.ArgumentParser();p.add_argument('--workspace',type=Path,required=True)
    p.add_argument('--engine-root',type=Path,required=True);p.add_argument('--dotnet',type=Path,required=True);args=p.parse_args()
    root=args.workspace.absolute();project=Path(__file__).resolve().parents[1]
    if not root.exists():
        root.mkdir(parents=True)
        (root/'request.json').write_bytes((project/'examples/options/monthly-variable-path.json').read_bytes())
        (root/'demo.toml').write_bytes((project/'configs/demo.toml').read_bytes())
    fingerprint=source_fingerprint()
    cmd=[sys.executable,'-m','personal_quant.cli','--config','demo.toml','options','--action','monthly-replay',
        '--file','request.json','--engine-root',str(args.engine_root.absolute()),'--dotnet',str(args.dotnet.absolute()),
        '--destination',str(root/'engine'),'--capital','100000','--fee-per-contract','2','--stock-commission-bps','2']
    run=subprocess.run(cmd,cwd=root,capture_output=True,text=True,
        env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src')))
    (root/'stdout.json').write_text(run.stdout);(root/'stderr.log').write_text(run.stderr)
    assert run.returncode==0,run.stderr
    out=json.loads(run.stdout)
    assert out['status']=='PASSED' and out['data_type']=='synthetic_variable_path'
    assert abs(float(out['expected_equity'])-100642.7416)<1e-8
    assert abs(float(out['actual_equity'])-100642.7416)<=.01
    assert out['duplicate_events_added']==0 and not out['ledger_bridge']['positions'] and not out['ledger_bridge']['option_positions']
    assert out['no_user_account_writes'] and source_fingerprint()==fingerprint
    curve=engine_curve(root/'engine',out)
    proof=dict(status='PASSED',command=cmd,exit_code=0,source_fingerprint=fingerprint,
        daily_engine_ledger_points=len(curve)-1,daily_engine_ledger_match=True,
        data_type=out['data_type'],expected_equity=out['expected_equity'],actual_equity=out['actual_equity'],
        engine_commit=out['engine_commit'],adapter_source=out['adapter_source'],
        duplicate_events_added=0,no_user_account_writes=True)
    (root/'verification.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2))
    print(json.dumps(dict(status='PASSED',verification=str(root/'verification.json'))))

if __name__=='__main__':main()

