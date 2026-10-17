"""Public evidence linkage/operation gates with unmistakably test-only documents."""
import argparse,hashlib,json,os,subprocess,sys
from pathlib import Path
import pandas as pd
from personal_quant.common import now_utc
from personal_quant.data.fixture import create_fixture
from personal_quant.data.calendar import Calendar
from personal_quant.data.store import DataStore
from personal_quant.portfolio import Ledger
from personal_quant.options.permissions import series_id
from personal_quant.options.contracts import OptionContract
from personal_quant.hedging.greek_evidence import series_id as greek_series_id
from personal_quant.strategies.archive import source_fingerprint


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--workspace',type=Path,required=True);args=parser.parse_args()
    root=args.workspace.absolute();root.mkdir(parents=True,exist_ok=False);project=Path(__file__).absolute().parents[1]
    (root/'demo.toml').write_bytes((project/'configs/demo.toml').read_bytes());fingerprint=source_fingerprint();checks=[]
    def run(name,command):
        completed=subprocess.run([sys.executable,'-m','personal_quant.cli','--config','demo.toml',*command],cwd=root,capture_output=True,text=True,
            env=dict(os.environ,PYTHONPATH=str(project/'src')))
        (root/(name+'-stdout.json')).write_text(completed.stdout);(root/(name+'-stderr.log')).write_text(completed.stderr)
        assert completed.returncode==0,(name,completed.returncode,completed.stdout,completed.stderr)
        checks.append(dict(name=name,command=command,exit_code=completed.returncode));return json.loads(completed.stdout)
    def call(name,command,body):
        file=name+'.json';(root/file).write_text(json.dumps(body));return run(name,[*command,'--file',file])
    run('enable',['v19-init']);book=Ledger(root/'runtime/demo/account.sqlite','demo');book.account('sample')
    prices,sessions=create_fixture(root/'fixtures');store=DataStore(book.path.parent/'data');metadata=store.save(pd.read_csv(prices),Calendar.csv(sessions,'synthetic_test_sessions'))
    directory=root/'proof';directory.mkdir();(directory/'terms.txt').write_text('TEST ONLY: invented source and broker document. No real permissions or data qualification.')
    files={'terms.txt':hashlib.sha256((directory/'terms.txt').read_bytes()).hexdigest()}
    source=call('stock-source',['qualify-source','--evidence-directory','proof'],dict(schema_version=1,series_id=store.series_identity(metadata),
        sources=metadata['source'],market='XNYS',currency='USD',timezone='America/New_York',price_basis='unadjusted',units_description='test shares',
        adjustment_method='test no adjustment',actions_description='test actions only',scope_symbols=metadata['symbols'],
        reviewed_at='2024-01-01T00:00:00Z',valid_until='2027-01-01T00:00:00Z',decision='QUALIFIED',reviewer='test_fixture',
        reason='engineering test only',evidence_type='test',evidence_files=files))
    identity=dict(schema_version=1,security_id='security-us-spy',instrument_type='etf',exchange='ARCX',calendar='XNYS',timezone='America/New_York',
        currency='USD',trade_unit='1',valid_from='2024-01-01T00:00:00Z',valid_until='2030-01-01T00:00:00Z',
        ticker_history=[dict(ticker='SPY',valid_from='2024-01-01T00:00:00Z',valid_until='2030-01-01T00:00:00Z')],
        corporate_action_refs=[],source_qualification_refs=[source['qualification_id']],source_type='synthetic')
    registered=call('security',['security-register','--commit'],identity)
    request=dict(security_versions={'SPY':registered['record']['version_hash']},security_ids={'SPY':'security-us-spy'},as_of='2025-01-15T21:30:00Z',
        knowledge_cutoff=now_utc(),valuation_snapshot_id=metadata['snapshot_id'],ledger_seq=0)
    result=call('security-assessment',['security-assess','--account-id','sample'],request)
    assert result['status']=='BLOCKED' and 'SOURCE_NOT_QUALIFIED:SPY' in result['checks'] and not result['executable']
    body=dict(schema_version=2,asset_type='ACCOUNT_OPTION_PERMISSIONS',series_id=series_id('sample','demo'),account_id='sample',environment='demo',
        broker='TEST_ONLY',market='OPRA',currency='USD',scope_templates=['long_put'],scope_operations=['OPEN','CLOSE'],settlement_policy='cash_account_no_margin',
        exercise_policy='close_before_expiry',maximum_contracts=2,maximum_physical_cash='10000',minimum_exit_days=7,
        reviewed_at='2024-01-01T00:00:00Z',valid_until='2027-01-01T00:00:00Z',decision='QUALIFIED',reviewer='test_fixture',reason='test only',evidence_type='test',evidence_files=files)
    grant=call('permissions',['options','--action','permissions-register','--destination','proof','--commit'],body)
    assert call('permissions-repeat',['options','--action','permissions-register','--destination','proof','--commit'],body)==grant
    assessment=dict(account_id='sample',template_id='long_put',operation='OPEN',as_of=now_utc(),contract_count=3,physical_cash=0,exit_days=2)
    gate=call('permissions-assessment',['options','--action','permissions-assess'],assessment)
    assert gate['status']=='UNQUALIFIED' and not gate['executable']
    assert set(gate['checks'])=={'ACCOUNT_OPTION_LIMIT_EXCEEDED','ACCOUNT_OPTION_DISPOSITION_REQUIRED','ACCOUNT_OPTION_PERMISSIONS_NOT_QUALIFIED'}
    contract=OptionContract.from_dict(dict(contract_id='SPY-20261218-P100-fixture',underlying='SPY',right='PUT',strike=100,
        expiry='2026-12-18',last_trade_at='2026-12-18T21:00:00Z',exercise_cutoff_at='2026-12-18T22:30:00Z',
        listed_at='2026-01-01T00:00:00Z',style='AMERICAN',settlement='PHYSICAL',currency='USD',quote_multiplier=100,
        deliverable_shares=100,deliverable_cash=0,exercise_cash=10000,tick_size='.01',revision='test',evidence_hash='TEST_ONLY'))
    greek=dict(contract_version=contract.version_hash,unit='per_share',value='-0.5',signed_contracts=1,
        source='TEST_ONLY',data_type='provider',as_of='2026-10-09T19:45:00Z',available_at='2026-10-09T19:45:02Z',
        received_at='2026-10-09T19:45:04Z',model_inputs={})
    (directory/'observation.json').write_text(json.dumps(greek))
    greek_files={name:hashlib.sha256((directory/name).read_bytes()).hexdigest() for name in ('observation.json','terms.txt')}
    greek_body=dict(schema_version=2,asset_type='OPTION_GREEK_OBSERVATION',series_id=greek_series_id(greek['source'],contract.version_hash),
        contract=contract.content(),observation=greek,reviewed_at=now_utc(),valid_until='2027-01-01T00:00:00Z',
        decision='QUALIFIED',reviewer='test_fixture',reason='TEST ONLY',evidence_type='test',evidence_files=greek_files)
    greek_proof=call('greek-register',['options','--action','greek-register','--destination','proof','--commit'],greek_body)
    greek_request=dict(item={**greek,'qualification_id':greek_proof['qualification_id']},contract=contract.content(),knowledge_cutoff=now_utc())
    greek_check=call('greek-assess',['options','--action','greek-assess'],greek_request)
    assert greek_check['status']=='UNQUALIFIED' and greek_check['checks']==['GREEK_NOT_QUALIFIED'] and not greek_check['executable']
    run('backup',['backup-bundle','--destination',str(root/'bundle')]);run('verify',['verify-backup','--source',str(root/'bundle'),'--environment','demo'])
    run('restore',['restore','--source',str(root/'bundle'),'--environment','demo','--destination',str(root/'restored')])
    recovered=Ledger(root/'restored/runtime/demo/account.sqlite','demo')
    from personal_quant.hedging.securities import assess
    from personal_quant.options.permissions import assess as permissions
    from personal_quant.hedging.greek_evidence import assess as assess_greek
    assert assess(recovered,'sample',request)==result and permissions(recovered,**assessment)==gate
    assert assess_greek(recovered,greek_request['item'],contract,greek_request['knowledge_cutoff'])==greek_check
    assert recovered.sequence('sample')==book.sequence('sample')==0
    assert source_fingerprint()==fingerprint
    proof=dict(status='PASSED',source_fingerprint=fingerprint,data_type='synthetic',checks=checks,commands=len(checks),
        security_status=result['status'],permission_status=gate['status'],greek_status=greek_check['status'],
        empty_account_sequence=0,complete_restore_passed=True,no_user_account_writes=True)
    (root/'verification.json').write_text(json.dumps(proof,indent=2));print(json.dumps(proof));recovered.close();book.close()


if __name__=='__main__':main()
