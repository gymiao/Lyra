"""Isolated no-key v1.8 CLI acceptance, preserving command/results/source provenance."""
from pathlib import Path
import contextlib,io,json,os,sys
from uuid import uuid4
REPO=Path(__file__).resolve().parents[1]
WRITABLE_ALIAS=Path('/mnt/c/quant/project/lyra')
if WRITABLE_ALIAS.is_dir() and WRITABLE_ALIAS.samefile(REPO):
    REPO=WRITABLE_ALIAS
sys.path.insert(0,str(REPO/'src'))
from personal_quant.cli import main
from personal_quant.common import write_json, now_utc
from personal_quant.config import Config
from personal_quant.strategies.archive import source_fingerprint
from personal_quant.data.store import DataStore


def verify():
    output=REPO/'reports/v18-validation'/uuid4().hex
    workspace=output/'workspace';workspace.mkdir(parents=True)
    config=Config.load(REPO/'configs/demo.toml');path=workspace/'config.json';write_json(path,config.content())
    records=[];previous=Path.cwd()
    def run(*args,expected=0):
        out,err=io.StringIO(),io.StringIO()
        with contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):code=main(['--config',str(path),*map(str,args)])
        lines=(out.getvalue() or err.getvalue()).strip().splitlines();result=json.loads(lines[-1])
        records.append({'command':list(map(str,args)),'exit_code':code,'result':result})
        assert code==expected,(args,result)
        return result
    try:
        os.chdir(workspace)
        run('fixture');run('workbench-init');run('v18-init');run('data-series')
        frame,meta,calendar=DataStore(Path(config.runtime_dir)/'data').load()
        for role in ['signal','execution','valuation']:
            run('data-bind','--role',role,'--identity',meta['snapshot_id'],'--expected-revision',0)
        run('data-status')
        for name in ['fixed','momentum_rotation']:
            run('strategies','--file',REPO/'configs/strategies'/f'{name}.json')
        bundle={'signal_snapshot_id':meta['snapshot_id'],'execution_snapshot_id':meta['snapshot_id'],'calendar_hash':calendar.hash,'factor_snapshot_id':None}
        request={'members':{n:{'strategy_id':n,'revision':1} for n in ['fixed','momentum_rotation']},'benchmark_member_id':'fixed','data_bundle':bundle,
            'windows':[{'start':'2024-07-01','end':'2024-12-31'}],
            'cost_scenarios':[{'id':'base','commission_multiplier':1,'slippage_multiplier':1,'fixed_fee_multiplier':1},
                {'id':'double','commission_multiplier':2,'slippage_multiplier':2,'fixed_fee_multiplier':2}]}
        write_json(Path('validation.json'),request)
        write_json(Path('protocol.json'),{'name':'fixed_before_validation','specification':request,'future_start':None})
        protocol=run('research-protocol','--file','protocol.json')
        suite=run('research-validate','--file','validation.json','--protocol-id',protocol['protocol_id'])
        assert suite['status']=='SUCCESS',suite
        repeat=run('research-validate','--suite-id',suite['suite_id']);assert repeat['suite_id']==suite['suite_id']
        run_id=suite['items'][0]['details']['run_id']
        package=run('research-package','--action','export','--run-id',run_id,'--destination','research-package')
        run('research-package','--action','verify','--source','research-package')
        run('research-package','--action','restore','--source','research-package','--destination','restored-package')
        replay=run('research-package','--action','replay','--source','research-package','--destination','replay-package')
        # Standard statement import, monthly daily plan, effective fills and read-only CSV.
        run('account','--account-id','v18-demo')
        Path('opening.csv').write_text('event_id,kind,amount,effective_at,source,evidence_type\nopening,DEPOSIT,10000,2024-07-01T20:00:00Z,test_statement,test\n')
        preview=run('import-events','--account-id','v18-demo','--file','opening.csv','--as-of','2024-07-31T20:30:00Z')
        run('import-events','--account-id','v18-demo','--file','opening.csv','--commit','--expected-sequence',preview['expected_sequence'],'--expected-hash',preview['batch_hash'])
        write_json(Path('opening_snapshot.json'),{'account_id':'v18-demo','currency':'USD','as_of':'2024-07-31T20:30:00Z','cash_basis':'settled','cash':10000,'positions':{},'source':'independent_test_statement'})
        run('reconcile','--account-id','v18-demo','--file','opening_snapshot.json')
        run('strategy-bind','--account-id','v18-demo','--strategy-id','momentum_rotation','--revision',1,'--as-of','2024-07-01T20:30:00Z')
        daily=run('daily','--account-id','v18-demo','--as-of','2024-07-31T20:30:00Z')
        assert daily['planning']['status']=='READY',daily
        plan=daily['planning']['plan_id']
        run('simulate','--plan-id',plan,'--as-of','2024-08-01T20:30:00Z')
        run('simulate','--plan-id',plan,'--as-of','2024-08-01T20:30:00Z')
        review=run('execution-review','--plan-id',plan,'--as-of','2024-08-02T20:30:00Z','--output','review.csv')
        assert review['lines'] and all(l['actual_quantity_current_units']==l['suggested_quantity_current_units'] for l in review['lines'])
        # Run a different suite with the real worker CLI, then query its durable success.
        import sqlite3,time
        background_request={**request,'windows':[{'start':'2024-07-01','end':'2024-09-30'}],'cost_scenarios':request['cost_scenarios'][:1]}
        write_json(Path('background.json'),background_request)
        background=run('research-validate','--file','background.json','--background')
        deadline=time.monotonic()+90
        while time.monotonic()<deadline:
            with sqlite3.connect(Path(config.runtime_dir)/'account.sqlite') as db:
                status=db.execute('SELECT status FROM validation_suites WHERE suite_id=?',(background['suite_id'],)).fetchone()[0]
            if status in {'SUCCESS','INCOMPLETE'}:break
            time.sleep(.2)
        assert status=='SUCCESS',status
        run('research-validate','--suite-id',background['suite_id'])
        run('doctor','--as-of' ,'2024-12-31T21:30:00Z');run('notices','--sync');run('notices')
        run('backup-bundle','--destination','complete-backup')
        run('verify-backup','--source','complete-backup','--environment','demo')
        run('restore','--source','complete-backup','--destination','restored','--environment','demo')
        # The legacy full demonstration checks account facts, fills, reconciliations.
        result={'status':'PASS_V18_CLI','commands':len(records),'source_hash':source_fingerprint(),'generated_at':now_utc(),
            'suite_id':suite['suite_id'],'run_id':run_id,'package':package,'replay':replay,'records':records}
        write_json(output/'verification.json',result);write_json(REPO/'reports/v18-validation/latest.json',{'verification':str(output/'verification.json')})
        print(json.dumps({k:v for k,v in result.items() if k!='records'},ensure_ascii=False))
    finally:os.chdir(previous)

if __name__=='__main__':verify()
