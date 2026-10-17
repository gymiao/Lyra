"""Public CLI model-Delta proof; all documents are fabricated engineering data."""
import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from personal_quant.common import now_utc
from personal_quant.options import pricing
from personal_quant.options.contracts import OptionContract
from personal_quant.hedging.greek_evidence import assess, model_series_id
from personal_quant.portfolio import Ledger
from personal_quant.strategies.archive import source_fingerprint


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--workspace',type=Path,required=True);args=parser.parse_args()
    root=args.workspace.absolute();root.mkdir(parents=True,exist_ok=False)
    project=Path(__file__).absolute().parents[1];source=Path(pricing.__file__).parents[2]
    (root/'demo.toml').write_bytes((project/'configs/demo.toml').read_bytes())
    fingerprint=source_fingerprint();records=[]
    def run(name,command,*,error=None):
        result=subprocess.run([sys.executable,'-m','personal_quant.cli','--config','demo.toml',*command],
            cwd=root,capture_output=True,text=True,env=dict(os.environ,PYTHONPATH=str(source)))
        (root/(name+'-stdout.json')).write_text(result.stdout);(root/(name+'-stderr.json')).write_text(result.stderr)
        parsed=json.loads(result.stderr if error else result.stdout)
        assert (result.returncode!=0 and parsed['code']==error) if error else result.returncode==0,(name,parsed)
        records.append(dict(name=name,command=command,exit_code=result.returncode,expected_error=error))
        return parsed
    def call(name,command,body,*,error=None):
        file=name+'.json';(root/file).write_text(json.dumps(body));return run(name,[*command,'--file',file],error=error)
    run('enable',['v19-init']);run('account',['account','--account-id','sample'])
    contract=OptionContract.from_dict(dict(contract_id='SPY-20261218-C100-model-fixture',underlying='SPY',right='CALL',strike=100,
        expiry='2026-12-18',last_trade_at='2026-12-18T21:00:00Z',exercise_cutoff_at='2026-12-18T22:30:00Z',
        listed_at='2026-01-01T00:00:00Z',style='EUROPEAN',settlement='PHYSICAL',currency='USD',quote_multiplier=100,
        deliverable_shares=100,deliverable_cash=0,exercise_cash=10000,tick_size='.01',revision='test',evidence_hash='TEST_ONLY'))
    parameters=dict(right='CALL',style='EUROPEAN',spot=100,strike=100,valuation_date='2026-10-09',expiry=contract.expiry,
        volatility=.2,rate=.04,dividend_yield=.01,multiplier=100,contracts=2,market_price=None,discrete_dividends=None)
    priced=call('price',['options','--action','price'],parameters)
    observations={name:dict(value=parameters[name],source='TEST_ONLY',as_of='2026-10-09T19:45:00Z',
        available_at='2026-10-09T19:45:02Z',received_at='2026-10-09T19:45:04Z',max_age_seconds=60,
        data_type='synthetic',raw_file='raw-inputs.txt')
        for name in ('spot','volatility','rate','dividend_yield','discrete_dividends')}
    inputs=dict(pricing=parameters,model=priced['model'],engine=priced['engine'],model_version=priced['model_version'],
        pricing_source_hash=hashlib.sha256(Path(pricing.__file__).read_bytes()).hexdigest(),input_observations=observations)
    item=dict(contract_version=contract.version_hash,unit='position_total',value=str(priced['greeks']['delta']),signed_contracts=2,
        source='QuantLib explicit test inputs',data_type='model',as_of='2026-10-09T19:45:00Z',
        available_at='2026-10-09T19:45:04Z',received_at='2026-10-09T19:45:05Z',model_inputs=inputs)
    evidence=root/'proof';evidence.mkdir()
    (evidence/'raw-inputs.txt').write_text('FABRICATED TEST INPUTS; NO DATA ACCESS OR ACCOUNT PERMISSION')
    (evidence/'observation.json').write_text(json.dumps(item));(evidence/'model-inputs.json').write_text(json.dumps(inputs))
    body=dict(schema_version=2,asset_type='OPTION_MODEL_GREEK_OBSERVATION',
        series_id=model_series_id(item['source'],contract.version_hash),contract=contract.content(),observation=item,
        reviewed_at=now_utc(),valid_until='2027-01-01T00:00:00Z',decision='QUALIFIED',reviewer='test_fixture',
        reason='ENGINEERING TEST ONLY',evidence_type='test',evidence_files={name:hashlib.sha256((evidence/name).read_bytes()).hexdigest()
            for name in ('observation.json','model-inputs.json','raw-inputs.txt')})
    command=['options','--action','greek-register','--destination','proof','--commit']
    registered=call('register',command,body);assert call('register-repeat',command,body)==registered
    bound={**item,'qualification_id':registered['qualification_id']}
    request=dict(item=bound,contract=contract.content(),knowledge_cutoff=now_utc())
    checked=call('assess',['options','--action','greek-assess'],request)
    assert checked['status']=='UNQUALIFIED' and checked['checks']==['GREEK_NOT_QUALIFIED'] and not checked['executable']
    forged=deepcopy(body);forged['observation']['value']=str(priced['greeks']['delta']+1)
    call('forged-delta',command,forged,error='MODEL_GREEK_MISMATCH')
    future=deepcopy(body);future['observation']['model_inputs']['input_observations']['rate']['received_at']='2026-10-09T20:00:00Z'
    call('future-input',command,future,error='INVALID_MODEL_GREEK_INPUT')
    run('backup',['backup-bundle','--destination',str(root/'bundle')])
    run('verify',['verify-backup','--source',str(root/'bundle'),'--environment','demo'])
    run('restore',['restore','--source',str(root/'bundle'),'--environment','demo','--destination',str(root/'restored')])
    recovered=Ledger(root/'restored/runtime/demo/account.sqlite','demo')
    try:
        assert assess(recovered,bound,contract,request['knowledge_cutoff'])==checked
        assert recovered.sequence('sample')==0 and source_fingerprint()==fingerprint
    finally:recovered.close()
    proof=dict(status='PASSED',source_fingerprint=fingerprint,data_type='synthetic_test_only',commands=len(records),
        checks=records,greek_status=checked['status'],account_sequence=0,complete_restore_passed=True)
    (root/'verification.json').write_text(json.dumps(proof,indent=2));print(json.dumps(proof))


if __name__=='__main__':main()
