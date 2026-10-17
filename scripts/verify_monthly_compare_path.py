"""Actual CLI same-capital variable-path comparison and archived report checks."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from personal_quant.options.monthly_report import load_monthly_report
from personal_quant.strategies.archive import source_fingerprint

def main():
    p=argparse.ArgumentParser();p.add_argument('--workspace',type=Path,required=True)
    p.add_argument('--engine-root',type=Path,required=True);p.add_argument('--dotnet',type=Path,required=True)
    args=p.parse_args();root=args.workspace.absolute();root.mkdir(parents=True)
    project=Path(__file__).resolve().parents[1]
    (root/'request.json').write_bytes((project/'examples/options/monthly-variable-path.json').read_bytes())
    (root/'demo.toml').write_bytes((project/'configs/demo.toml').read_bytes())
    fingerprint=source_fingerprint()
    command=[sys.executable,'-m','personal_quant.cli','--config','demo.toml','options','--action','monthly-compare',
        '--file','request.json','--engine-root',str(args.engine_root.absolute()),'--dotnet',str(args.dotnet.absolute()),
        '--destination',str(root/'comparison'),'--capital','100000','--fee-per-contract','2','--stock-commission-bps','2']
    result=subprocess.run(command,cwd=root,capture_output=True,text=True,
        env=dict(os.environ,PYTHONPATH=str(project/'src')))
    (root/'stdout.json').write_text(result.stdout);(root/'stderr.log').write_text(result.stderr)
    assert result.returncode==0,result.stderr
    report=json.loads(result.stdout);assert load_monthly_report(root/'comparison')==report
    assert report['data_type']=='synthetic_variable_path' and not report['executable']
    metrics=report['metrics']
    assert abs(metrics['protective_put']['net_trading_pnl']-642.7416)<1e-8
    assert abs(metrics['stock']['net_trading_pnl']-597.7416)<1e-8
    assert metrics['cash']['net_trading_pnl']==0 and metrics['cash']['cost']==0
    assert abs(report['comparison']['strategy_vs_stock_pnl']-45)<1e-8
    assert abs(metrics['protective_put']['bid_ask_cost']-50)<1e-8
    assert metrics['protective_put']['observations']==47
    proofs={member:json.loads((root/'comparison'/member/'verification.json').read_text()) for member in metrics}
    assert all(x['no_user_account_writes'] and x['duplicate_events_added']==0 for x in proofs.values())
    assert source_fingerprint()==fingerprint
    proof=dict(status='PASSED',command=command,exit_code=0,source_fingerprint=fingerprint,data_type=report['data_type'],
        members=list(metrics),observations=47,strategy_vs_stock_pnl=report['comparison']['strategy_vs_stock_pnl'],
        report_hash=load_monthly_report(root/'comparison')['execution_path_hash'],no_user_account_writes=True)
    (root/'verification.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2))
    print(json.dumps(dict(status='PASSED',verification=str(root/'verification.json'))))

if __name__=='__main__':main()

