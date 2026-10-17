"""Actual public CLI multi-option basket report, explicitly synthetic and read-only."""
import argparse,json,os,subprocess,sys,shutil
from pathlib import Path
from personal_quant.common import decimal as D
from personal_quant.strategies.archive import source_fingerprint
from personal_quant.options.monthly_report import load_monthly_report


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--workspace',type=Path,required=True)
    parser.add_argument('--engine-root',type=Path,required=True);parser.add_argument('--dotnet',type=Path,required=True)
    args=parser.parse_args();root=args.workspace.absolute();root.mkdir(parents=True,exist_ok=False)
    project=Path(__file__).absolute().parents[1];sys.path.insert(0,str(project/'tests'))
    from test_options_monthly_portfolio_v19 import basket_inputs,independent_roundtrips
    batches,path,_=basket_inputs(root/'frozen-inputs')
    (root/'demo.toml').write_bytes((project/'configs/demo.toml').read_bytes())
    request=dict(signals=batches,packages=[[2,1],[3,2]],stock_basket={'IEF':50},execution_path=path)
    (root/'request.json').write_text(json.dumps(request))
    fingerprint=source_fingerprint();checks=[]
    def run(name,tail):
        cmd=[sys.executable,'-m','personal_quant.cli','--config','demo.toml',*tail]
        result=subprocess.run(cmd,cwd=root,capture_output=True,text=True,env=dict(os.environ,PYTHONPATH=str(project/'src')))
        (root/(name+'-stdout.json')).write_text(result.stdout);(root/(name+'-stderr.log')).write_text(result.stderr)
        assert result.returncode==0,(result.returncode,result.stdout,result.stderr)
        checks.append(dict(name=name,command=cmd,exit_code=result.returncode))
        return json.loads(result.stdout)
    run('enable',['v19-init'])
    from personal_quant.portfolio import Ledger
    book=Ledger(root/'runtime/demo/account.sqlite','demo');book.account('portfolio-research');book.close()
    runtime=root/'runtime/demo'
    chains=runtime/'options/chains';chains.mkdir(parents=True,exist_ok=True)
    monthly=runtime/'options/monthly';monthly.mkdir(parents=True,exist_ok=True)
    for symbol in ('spy','gld'):
        for item in (root/'frozen-inputs'/symbol/'chains').iterdir():
            if item.is_dir() and len(item.name)==64:shutil.copytree(item,chains/item.name)
        for item in (root/'frozen-inputs'/symbol/'monthly').glob('*.json'):shutil.copyfile(item,monthly/item.name)
    comparison=runtime/'options/monthly-research/basket-comparison'
    command=[sys.executable,'-m','personal_quant.cli','--config','demo.toml','options','--action','monthly-compare','--file','request.json',
        '--engine-root',str(args.engine_root.absolute()),'--dotnet',str(args.dotnet.absolute()),'--destination',str(comparison),
        '--capital','100000','--fee-per-contract','2','--stock-commission-bps','2']
    result=subprocess.run(command,cwd=root,capture_output=True,text=True,env=dict(os.environ,PYTHONPATH=str(project/'src')))
    (root/'stdout.json').write_text(result.stdout);(root/'stderr.log').write_text(result.stderr)
    assert result.returncode==0,(result.returncode,result.stdout,result.stderr)
    checks.append(dict(name='monthly-compare',command=command,exit_code=result.returncode))
    report=load_monthly_report(comparison);native=json.loads((comparison/'protective_put/verification.json').read_text())
    expected=independent_roundtrips(native['cycles'],path)
    assert D(native['ledger_bridge']['equity'])==expected and report['option_underlyings']==['GLD','SPY']
    assert len(report['signal_ids'])==4 and fingerprint==source_fingerprint()
    run('backup',['backup-bundle','--destination',str(root/'bundle')])
    run('verify',['verify-backup','--source',str(root/'bundle'),'--environment','demo'])
    run('restore',['restore','--source',str(root/'bundle'),'--environment','demo','--destination',str(root/'restored')])
    restored=load_monthly_report(root/'restored/runtime/demo/options/monthly-research/basket-comparison')
    assert restored==report and source_fingerprint()==fingerprint
    recovered=Ledger(root/'restored/runtime/demo/account.sqlite','demo')
    try:assert recovered.sequence('portfolio-research')==0
    finally:recovered.close()
    proof=dict(status='PASSED',source_fingerprint=fingerprint,checks=checks,command=command,exit_code=0,data_type='synthetic',
        option_underlyings=['GLD','SPY'],stock_symbols=['GLD','IEF','SPY'],signals=4,monthly_cycles=2,
        initial_cash='100000',final_cash=str(expected),report=str(comparison/'report.md'),no_user_account_writes=True,empty_account_sequence=0,complete_restore_passed=True)
    (root/'verification.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2))
    print(json.dumps(proof,ensure_ascii=False))


if __name__=='__main__':main()
