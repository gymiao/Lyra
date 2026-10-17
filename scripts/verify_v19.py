"""Isolated no-key v1.9 CLI integration; records source and explicit data types."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
from uuid import uuid4
REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'src'))
from personal_quant.cli import main
from personal_quant.common import write_json,now_utc
from personal_quant.config import Config
from personal_quant.strategies.archive import source_fingerprint


def verify():
    # The sandbox grants the lowercase mount path; preserve it in writable paths.
    root=Path('/mnt/c/quant/project/lyra') if Path('/mnt/c/quant/project/lyra').is_dir() else REPO
    output=root/'reports/v19-validation'/uuid4().hex
    workspace=output/'workspace';workspace.mkdir(parents=True)
    config=workspace/'config.json';write_json(config,Config.load(REPO/'configs/demo.toml').content())
    original=Path.cwd();records=[]
    def run(*arguments):
        out,err=io.StringIO(),io.StringIO()
        with contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):
            code=main(['--config',str(config),*map(str,arguments)])
        text=(out.getvalue() or err.getvalue()).strip().splitlines()
        result=json.loads(text[-1]);records.append({'command':list(map(str,arguments)),'exit_code':code,'result':result})
        write_json(output/'commands.json',records)
        assert code==0,(arguments,result)
        return result
    try:
        os.chdir(workspace)
        directory=run('hedge-catalog')
        assert len(directory['methods'])==16 and not directory['executable']
        assert not (workspace/'runtime').exists()
        meta=run('fixture');run('account','--account-id','v19-demo');run('v19-init');run('v19-init');run('data-series')
        for role in ('signal','execution','valuation'):
            run('data-bind','--role',role,'--identity',meta['snapshot_id'],'--expected-revision',0)
        run('options','--action','catalog')
        scenario=run('options','--action','scenario','--file',REPO/'examples/options/protective_put.json','--destination',workspace/'scenario-reports')
        assert scenario['maximum_loss']=='700.00' or float(scenario['maximum_loss'])==700
        model=run('options','--action','price','--file',REPO/'examples/options/european_call.json')
        assert abs(model['unit_price']-10.450583572185565)<1e-8
        chain=run('options','--action','import-chain','--file',REPO/'examples/options/quotes.csv',
            '--contracts',REPO/'examples/options/contracts.json','--metadata',REPO/'examples/options/metadata.json')
        repeat=run('options','--action','import-chain','--file',REPO/'examples/options/quotes.csv',
            '--contracts',REPO/'examples/options/contracts.json','--metadata',REPO/'examples/options/metadata.json')
        assert chain['snapshot_id']==repeat['snapshot_id']
        quality=run('options','--action','check-chain','--snapshot-id',chain['snapshot_id'],'--as-of','2026-10-09T19:46:00Z')
        assert not quality['executable'] and quality['checks'][0]['status']=='PASSED'
        run('options','--action','register-contracts','--contracts',REPO/'examples/options/contracts.json')
        full=run('options','--action','import-chain','--file',REPO/'examples/options/quotes-a8.csv',
            '--contracts',REPO/'examples/options/contracts-a8.json','--metadata',REPO/'examples/options/metadata.json')
        selected=run('options','--action','select','--snapshot-id',full['snapshot_id'],'--file',REPO/'examples/options/selection.json')
        assert selected['expiry']=='2026-11-20' and len(selected['legs'])==2 and not selected['executable']
        pressure=run('options','--action','stress','--file',REPO/'examples/options/calendar-stress.json')
        assert len(pressure['points'])==15 and pressure['maximum_loss']=='NOT_INFERRED_FROM_FINITE_GRID'
        args=('mapped-import','--account-id','v19-demo','--file',REPO/'examples/mappings/test_broker.csv',
              '--mapping',REPO/'examples/mappings/test_broker.json','--as-of','2024-07-03T21:00:00Z')
        preview=run(*args)
        imported=run(*args,'--commit','--expected-sequence',preview['preview']['expected_sequence'],'--expected-hash',preview['expected_hash'])
        assert imported['added']==3
        preview=run(*args)
        repeated=run(*args,'--commit','--expected-sequence',preview['preview']['expected_sequence'],'--expected-hash',preview['expected_hash'])
        assert repeated['added']==0
        option_draft=run('options','--action','plan-draft','--account-id','v19-demo','--snapshot-id',full['snapshot_id'],
                        '--file',REPO/'examples/options/plan-draft.json')
        again_draft=run('options','--action','plan-draft','--account-id','v19-demo','--snapshot-id',full['snapshot_id'],
                        '--file',REPO/'examples/options/plan-draft.json')
        assert option_draft['plan_id']==again_draft['plan_id'] and not option_draft['executable']
        assert any('INSUFFICIENT' in check for check in option_draft['checks'])
        progress=run('options','--action','plan-review','--plan-id',option_draft['plan_id'],'--as-of','2026-10-09T21:00:00Z')
        assert progress['status']=='DRAFT' and not progress['executable']
        # A missing contract receipt stays pending until the exact terms arrive.
        from personal_quant.options.contracts import OptionContract
        from personal_quant.portfolio.imports import event_csv
        import csv
        terms=json.loads((REPO/'examples/options/contracts.json').read_text())[0]
        terms={**terms,'contract_id':'LATE-TERMS-TEST'}
        late=OptionContract.from_dict(terms)
        receipt=event_csv((REPO/'examples/options/test-option-events.csv').read_bytes())[0]
        receipt.update(event_id='late-contract-receipt',contract_version=late.version_hash)
        receipt_file=workspace/'late-contract-events.csv'
        with receipt_file.open('w',newline='') as handle:
            writer=csv.DictWriter(handle,fieldnames=list(receipt));writer.writeheader();writer.writerow(receipt)
        late_args=('options','--action','import-facts','--account-id','v19-demo','--file',receipt_file,'--as-of','2026-10-09T21:00:00Z')
        late_preview=run(*late_args)
        assert late_preview['pending_events']
        pending=run(*late_args,'--commit','--expected-sequence',late_preview['expected_sequence'],'--expected-hash',late_preview['expected_hash'])
        assert pending['pending_events']==['late-contract-receipt']
        listed=run('options','--action','pending-list','--account-id','v19-demo')['pending_events']
        assert len(listed)==1
        terms_file=workspace/'late-contract.json';write_json(terms_file,[terms])
        run('options','--action','register-contracts','--contracts',terms_file)
        resolution_args=('options','--action','resolve-pending','--account-id','v19-demo','--event-id','late-contract-receipt',
            '--commit','--expected-sequence',pending['ledger_seq'],'--expected-hash',listed[0]['receipt_hash'])
        resolved=run(*resolution_args);assert resolved['status']=='RESOLVED'
        assert run(*resolution_args)==resolved
        assert not run('options','--action','pending-list','--account-id','v19-demo')['pending_events']
        long_request=json.loads((REPO/'examples/options/plan-draft.json').read_text())
        long_request['selection']['template_id']='long_call'
        long_request_file=workspace/'long-call-plan.json';write_json(long_request_file,long_request)
        long_plan=run('options','--action','plan-draft','--account-id','v19-demo','--snapshot-id',full['snapshot_id'],'--file',long_request_file)
        long_terms_file=workspace/'long-call-terms.json';write_json(long_terms_file,[long_plan['selection']['legs'][0]['contract']])
        run('options','--action','register-contracts','--contracts',long_terms_file)
        manual={'request_id':'test-manual-submission','plan_id':long_plan['plan_id'],'action':'record-submitted',
                'as_of':'2026-10-09T19:40:00Z','expected_sequence':resolved['import']['ledger_seq'],
                'reason':'Synthetic test: order already submitted manually, no broker call',
                'orders':[{'contract_id':long_plan['selection']['legs'][0]['contract']['contract_id'],
                           'side':'BUY','contracts':1,'limit_price':2,'fee_per_contract':1}]}
        manual_file=workspace/'manual-fact.json';write_json(manual_file,manual)
        manual_result=run('options','--action','manual-record','--file',manual_file,'--commit')
        assert run('options','--action','manual-record','--file',manual_file,'--commit')==manual_result
        linked=dict(receipt,event_id='linked-long-call',contract_version=long_plan['selection']['legs'][0]['contract_version'],plan_id=long_plan['plan_id'])
        linked_file=workspace/'linked-long-call.csv'
        with linked_file.open('w',newline='') as handle:
            writer=csv.DictWriter(handle,fieldnames=list(linked));writer.writeheader();writer.writerow(linked)
        linked_args=('options','--action','import-facts','--account-id','v19-demo','--file',linked_file,'--as-of','2026-10-09T21:00:00Z')
        linked_preview=run(*linked_args)
        run(*linked_args,'--commit','--expected-sequence',linked_preview['expected_sequence'],'--expected-hash',linked_preview['expected_hash'])
        linked_preview=run(*linked_args)
        assert run(*linked_args,'--commit','--expected-sequence',linked_preview['expected_sequence'],'--expected-hash',linked_preview['expected_hash'])['added']==0
        linked_progress=run('options','--action','plan-review','--plan-id',long_plan['plan_id'],'--as-of','2026-10-09T21:00:00Z')
        assert linked_progress['status']=='FILLED' and linked_progress['progress']['linked_events']==['linked-long-call']
        assert not linked_progress['executable']
        write_json(manual_file,{**manual,'request_id':'test-manual-end','action':'confirm-ended','as_of':'2026-10-09T21:00:00Z',
                               'expected_sequence':linked_preview['expected_sequence'],'orders':[],'reason':'Synthetic test: no remaining broker orders'})
        ended=run('options','--action','manual-record','--file',manual_file,'--commit')
        assert ended['result']['manual_execution']['reserved_cash']=='0'
        event_args=('options','--action','import-facts','--account-id','v19-demo','--file',REPO/'examples/options/test-option-events.csv',
                    '--as-of','2026-10-09T21:00:00Z')
        opt_preview=run(*event_args)
        opt_added=run(*event_args,'--commit','--expected-sequence',opt_preview['expected_sequence'],'--expected-hash',opt_preview['expected_hash'])
        assert opt_added['added']==1
        opt_preview=run(*event_args)
        opt_repeated=run(*event_args,'--commit','--expected-sequence',opt_preview['expected_sequence'],'--expected-hash',opt_preview['expected_hash'])
        assert opt_repeated['added']==0
        research=run('research')
        run('doctor','--as-of','2024-12-31T21:40:00Z','--verify-reports')
        first=run('backup-maintenance','--directory',output/'backups','--environment','demo','--action','create','--keep',1)
        run('backup-maintenance','--directory',output/'backups','--environment','demo','--action','preview','--keep',1)
        run('verify-backup','--source',first['backup'],'--environment','demo')
        run('restore','--source',first['backup'],'--destination',output/'restored','--environment','demo')
        from personal_quant.portfolio import Ledger
        book=Ledger(workspace/'runtime/demo/account.sqlite','demo')
        state=book.snapshot('v19-demo','2024-07-03T21:00:00Z',{'SPY':100});book.close()
        assert state['settled_cash']=='598' and state['equity']=='998' and state['positions']=={'SPY':'4'}
        result={'status':'PASSED','source_hash':source_fingerprint(),'completed_at':now_utc(),'commands':len(records),
                'workspace':str(workspace),'scenario_report':scenario['report_path'],'data_type':'synthetic_test_only',
                'account_expected':{'cash':'598','SPY':'4','equity':'998'},'research':research}
        write_json(output/'verification.json',result)
        print(output/'verification.json')
        return result
    finally:os.chdir(original)


if __name__=='__main__':verify()
