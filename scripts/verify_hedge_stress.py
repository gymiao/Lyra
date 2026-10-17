"""Run read-only hedge-stress CLI on an explicitly synthetic frozen workspace."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from personal_quant.common import decimal as D
from personal_quant.portfolio import Ledger
from personal_quant.strategies.archive import source_fingerprint


def main():
    p=argparse.ArgumentParser();p.add_argument('--workspace',type=Path,required=True)
    p.add_argument('--destination',type=Path,required=True);args=p.parse_args()
    source=args.workspace.resolve();root=args.destination.absolute();root.mkdir()
    shutil.copytree(source/'runtime',root/'runtime');shutil.copyfile(source/'demo.toml',root/'demo.toml')
    put=json.loads((source/'put.json').read_text());collar=json.loads((source/'collar.json').read_text())
    selection=json.loads((source/'put.stdout').read_text())['selection']
    call_selection=json.loads((source/'collar.stdout').read_text())['selection']
    start=put['option']['selection_request']['decision_at'][:10]
    expiry=selection['legs'][0]['contract']['expiry']
    def scenario(name,ret,iv=1,mult=1,horizon=expiry):
        return dict(name=name,horizon_date=horizon,benchmark_return=ret,beta_multiplier=mult,
            residual_returns={'SPY':0,'IEF':0},volatility_multiplier=iv)
    grid=[scenario('flat',0,horizon=start),scenario('down',-.2),scenario('up',.2),
          scenario('iv_up',0,iv=2,horizon=start),scenario('basis_break',-.2,mult=0)]
    def body(req,sel):
        return dict(preview_request=req,scenarios=grid,models={l['contract_version']:
            dict(volatility=.2,rate=0,dividend_yield=0) for l in sel['legs']})
    putreq=body(put,selection);collarreq=body(collar,call_selection)
    cases=[('put',putreq,0),('repeat',putreq,0),('collar',collarreq,0),
           ('missing_model',dict(putreq,models={}),2)]
    runtime=root/'runtime/demo';book=Ledger(runtime/'account.sqlite','demo')
    before=(book.sequence('sample'),book.connection.execute('SELECT count(*) FROM tasks').fetchone()[0]);book.close()
    fingerprint=source_fingerprint();checks=[];results={}
    for name,req,exit_code in cases:
        file=root/(name+'.json');file.write_text(json.dumps(req))
        command=[sys.executable,'-m','personal_quant.cli','--config','demo.toml','hedge-stress',
                 '--account-id','sample','--file',file.name]
        run=subprocess.run(command,cwd=root,capture_output=True,text=True,
            env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src')))
        (root/(name+'.stdout')).write_text(run.stdout);(root/(name+'.stderr')).write_text(run.stderr)
        assert run.returncode==exit_code,(name,run.stdout,run.stderr)
        out=json.loads(run.stderr if exit_code else run.stdout);results[name]=out
        if exit_code:assert out['code']=='MODEL_INPUT_REQUIRED'
        else:
            assert out['data_type']=='scenario_only' and not out['executable'] and len(out['points'])==5
            flat=out['points'][0]
            assert D(flat['unhedged_equity'])==30000
            assert D(flat['candidate_equity'])==(29986 if name=='collar' else 29993)
            assert out['maximum_loss']=='NOT_INFERRED_FROM_FINITE_GRID'
        checks.append(dict(case=name,command=command,exit_code=exit_code))
    assert results['put']==results['repeat']
    book=Ledger(runtime/'account.sqlite','demo')
    assert before==(book.sequence('sample'),book.connection.execute('SELECT count(*) FROM tasks').fetchone()[0])
    book.close();assert fingerprint==source_fingerprint()
    path=root/'verification.json'
    path.write_text(json.dumps(dict(status='PASSED',checks=checks,source_fingerprint=fingerprint,
        data_type='synthetic_scenario_only',account_unchanged=True),ensure_ascii=False,indent=2))
    print(json.dumps(dict(status='PASSED',checks=len(checks),verification=str(path))))

if __name__=='__main__':main()

