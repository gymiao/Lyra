"""Public CSV/incident CLI with qualified native LEAN synthetic assignment facts."""
import argparse,hashlib,json,os,sqlite3,subprocess,sys
from pathlib import Path
import pandas as pd
from personal_quant.common import decimal as D,utc
from personal_quant.options.qualification import assess_engine
from personal_quant.options.contracts import OptionContract
from personal_quant.options.incidents import status
from personal_quant.portfolio import Ledger
from personal_quant.strategies.archive import source_fingerprint


def main():
    p=argparse.ArgumentParser();p.add_argument('--workspace',type=Path,required=True);p.add_argument('--engine-evidence',type=Path,required=True);p.add_argument('--generic',action='store_true');args=p.parse_args()
    project=Path(__file__).absolute().parents[1];proof=args.engine_evidence.absolute()
    assert assess_engine(proof,'bull_call_debit_spread')['status']=='PASSED'
    case=proof.parent/'bull_call_partial_assignment'
    native=json.loads((case/'engine-events.json').read_text());terms=json.loads((case/'input.json').read_text())
    connection=sqlite3.connect('file:'+str(case/'bridge.sqlite')+'?mode=ro',uri=True)
    try:rows=[json.loads(r[0]) for r in connection.execute('SELECT payload FROM events ORDER BY seq')]
    finally:connection.close()
    assert len(rows)==5 and D(rows[0]['amount'])==100000
    events={str(e['order_id'])+':'+str(e['event_id']):e for e in native if e['order_type']!='OptionExercise' or e['symbol']==e['order_symbol']}
    contracts={}
    for r in rows:
        r['account_id']='sample'
        if r['kind']=='DEPOSIT':continue
        e=events[r['event_id']];c=OptionContract.from_dict(r.pop('contract'));c.require_standard_vanilla();contracts[c.version_hash]=c.content()
        assert D(r['quantity'])==abs(D(e['quantity'])) and D(r['price'])==D(e['price']) and D(r['fee'])==D(e['fee']) and utc(r['effective_at'])==utc(e['utc_time'])
        leg=next(l for l in terms['legs'] if l['right']==c.right and D(l['strike'])==c.strike and l['expiry']==c.expiry)
        assert c.quote_multiplier==100 and c.deliverable_shares==100 and c.exercise_cash==c.strike*100
        assert r['kind']==('OPTION_ASSIGNMENT' if e['assignment'] else 'OPTION_EXERCISE') if e['order_type']=='OptionExercise' else r['kind']=='OPTION_TRADE' and r['action']=='OPEN'
    root=args.workspace.absolute();root.mkdir(parents=True,exist_ok=False);(root/'demo.toml').write_bytes((project/'configs/demo.toml').read_bytes())
    source=source_fingerprint();checks=[]
    def run(name,command):
        process=subprocess.run([sys.executable,'-m','personal_quant.cli','--config','demo.toml',*map(str,command)],cwd=root,capture_output=True,text=True,env=dict(os.environ,PYTHONPATH=str(project/'src')))
        (root/(name+'-stdout.json')).write_text(process.stdout);(root/(name+'-stderr.log')).write_text(process.stderr)
        assert process.returncode==0,(process.returncode,process.stdout,process.stderr)
        checks.append(dict(name=name,command=command,exit_code=process.returncode));return json.loads(process.stdout)
    run('enable',['v19-init'])
    (root/'contracts.json').write_text(json.dumps(list(contracts.values())))
    run('contracts',['options','--action','register-contracts','--contracts','contracts.json'])
    book=Ledger(root/'runtime/demo/account.sqlite','demo');book.account('sample');book.import_events('sample',rows[:3]);assert book.sequence('sample')==3
    def import_row(name,row):
        file=name+'.csv';pd.DataFrame([row]).to_csv(root/file,index=False)
        command=(['import-events'] if args.generic else ['options','--action','import-facts'])+['--account-id','sample','--file',file,'--as-of',row['effective_at']]
        preview=run(name+'-preview',command);assert preview.get('pending_events',[])==[]
        committed=[*command,'--commit','--expected-sequence',str(preview['expected_sequence']),'--expected-hash',preview['batch_hash' if args.generic else 'expected_hash']]
        result=run(name+'-commit',committed);assert result['added']==1
        assert run(name+'-repeat',committed)==result
        return result
    assigned=import_row('assignment',rows[3]);assert assigned['has_intermediate_anomaly']
    first=book.snapshot('sample',rows[3]['effective_at'])
    assert first['positions']=={'SPY':'-100'} and D(first['settled_cash'])==110386
    clock=rows[4]['effective_at'];monitor=['hedge-status','--account-id','sample','--as-of',clock]
    assert run('before-recovery',monitor)['status']=='BLOCKED'
    recovered=import_row('recovery',rows[4]);assert not recovered['has_intermediate_anomaly']
    assert run('flat-but-unreviewed',monitor)['status']=='BLOCKED'
    final=book.snapshot('sample',clock,{})
    assert book.sequence('sample')==5 and final['positions']=={} and final['option_positions']=={} and D(final['settled_cash'])==100386
    book.reconcile('sample',dict(account_id='sample',currency='USD',as_of=clock,cash_basis='settled',cash=100386,positions={},option_positions={},equity=100386))
    rid=book.connection.execute('SELECT max(id) FROM reconciliations').fetchone()[0];incident=status(book,'sample',clock)['incidents'][0]
    evidence=root/'review-evidence';evidence.mkdir();blob=(case/'engine-events.json').read_bytes();(evidence/'native-events.json').write_bytes(blob)
    request=dict(schema_version=1,request_id='native-review',incident_id=incident['incident_id'],expected_hash=incident['view_hash'],expected_sequence=5,as_of=clock,
        recovery_event_ids=[rows[4]['event_id']],reconciliation_id=rid,reviewer='synthetic-native-cli',reason='Native next-day long call exercise offsets assigned short; original prefix retained',
        evidence_type='test',evidence_files={'native-events.json':hashlib.sha256(blob).hexdigest()})
    (root/'review.json').write_text(json.dumps(request));review=['option-incident-review','--account-id','sample','--file','review.json','--evidence-directory','review-evidence']
    run('review-preview',review);accepted=run('review-commit',[*review,'--commit']);assert run('review-repeat',[*review,'--commit'])==accepted
    assert run('after-review',monitor)['status']=='NO_ACTION'
    run('backup',['backup-bundle','--destination',str(root/'bundle')]);run('verify',['verify-backup','--source',str(root/'bundle'),'--environment','demo'])
    run('restore',['restore','--source',str(root/'bundle'),'--environment','demo','--destination',str(root/'restored')])
    restored=Ledger(root/'restored/runtime/demo/account.sqlite','demo')
    try:assert restored.sequence('sample')==5 and D(restored.snapshot('sample',clock,{})['settled_cash'])==100386 and status(restored,'sample',clock)==status(book,'sample',clock)
    finally:restored.close();book.close()
    assert source_fingerprint()==source
    result=dict(status='PASSED',checks=checks,source_fingerprint=source,data_type='synthetic_native_engine_facts',engine_evidence_hash=hashlib.sha256(proof.read_bytes()).hexdigest(),
        engine_rerun=False,import_entrypoint='import-events' if args.generic else 'options import-facts',original_intermediate_stock_shares=-100,final_cash='100386',financial_sequence=5,no_user_account_writes=True,broker_orders=False)
    (root/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(dict(status='PASSED',checks=len(checks),verification=str(root/'verification.json'))))


if __name__=='__main__':main()
