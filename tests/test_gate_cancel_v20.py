import json,subprocess,sys,os
from pathlib import Path
from personal_quant.common import write_json
from personal_quant.strategies.archive import source_fingerprint
from personal_quant.processes import python_environment
ROOT=Path(__file__).resolve().parents[1]


def test_cancelled_gate_cannot_be_presented_as_complete_release(tmp_path):
    file=tmp_path/'cancel.json';write_json(file,{'source_hash':source_fingerprint(),'confirm_cancel':True})
    out=tmp_path/'gate'
    result=subprocess.run([sys.executable,str(ROOT/'scripts/check_v20.py'),'--scope','fast','--destination',str(out),'--cancel-file',str(file)],
        cwd=ROOT,env=python_environment(),capture_output=True,text=True,timeout=60)
    assert result.returncode==1,result.stderr
    receipt=json.loads((out/'verification.json').read_text())
    assert receipt['status']=='FAILED' and receipt['cancelled']
    assert not receipt['complete_collection_coverage'] and not receipt['complete_version']
