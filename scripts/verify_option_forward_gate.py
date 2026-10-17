"""Public CLI refusal of a missed option month end; no clock override or broker call."""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from personal_quant.portfolio import Ledger
from personal_quant.strategies.archive import source_fingerprint


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--workspace',type=Path,required=True);args=parser.parse_args()
    root=args.workspace.absolute();root.mkdir(parents=True,exist_ok=False)
    project=Path(__file__).resolve().parents[1]
    template=(project/'configs/demo.toml').read_text()
    (root/'paper.toml').write_text(template.replace('environment = "demo"','environment = "paper"')
        .replace('runtime_dir = "runtime/demo"','runtime_dir = "runtime/paper"'))
    rule=json.loads((project/'examples/options/selection-engine-fixture.json').read_text())
    rule['decision_at']='2024-10-31T20:30:00Z'
    (root/'rule.json').write_text(json.dumps(rule))
    env=dict(os.environ,PYTHONPATH=str(project/'src'))
    def run(name,arguments):
        result=subprocess.run([sys.executable,'-m','personal_quant.cli','--config','paper.toml',*arguments],
            cwd=root,capture_output=True,text=True,env=env)
        (root/(name+'-stdout.json')).write_text(result.stdout)
        (root/(name+'-stderr.json')).write_text(result.stderr)
        return result
    setup=run('enable',['v19-init']);assert setup.returncode==0,setup.stderr
    book=Ledger(root/'runtime/paper/account.sqlite','paper');book.account('sample')
    before=book.sequence('sample')
    command=['options','--action','monthly-forward','--account-id','sample','--snapshot-id','0'*64,
             '--file','rule.json','--publication-delay-minutes','30','--max-generation-delay-minutes','10','--commit']
    rejected=run('missed-forward',command)
    assert rejected.returncode!=0,rejected.stdout
    failure=json.loads(rejected.stderr)
    assert failure['code']=='MISSED_FORWARD_WINDOW',failure
    assert book.sequence('sample')==before==0
    assert not list((root/'runtime/paper/options/monthly-forward').glob('*.json'))
    proof={'status':'PASSED','source_fingerprint':source_fingerprint(),'environment':'paper',
           'command':command,'expected_error':failure['code'],'account_sequence':0,
           'no_forward_signal_published':True,'no_broker_orders':True}
    (root/'verification.json').write_text(json.dumps(proof,indent=2));print(json.dumps(proof));book.close()


if __name__=='__main__':main()
