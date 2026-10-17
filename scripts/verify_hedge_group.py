"""Native stock group/partial receipts CLI flow on a copied synthetic research account."""
import argparse
from datetime import timedelta
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from personal_quant.common import canonical,decimal as D,utc
from personal_quant.hedging.allocation_store import resources
from personal_quant.hedging.intents import records
from personal_quant.portfolio import Ledger
from personal_quant.strategies.archive import source_fingerprint


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--workspace',type=Path,required=True)
    parser.add_argument('--destination',type=Path,required=True)
    args=parser.parse_args()
    root=args.destination.resolve();root.mkdir(parents=True,exist_ok=False)
    shutil.copytree(args.workspace/'runtime',root/'runtime')
    shutil.copy2(args.workspace/'demo.toml',root/'demo.toml')
    book=Ledger(root/'runtime/demo/account.sqlite','demo');parents=records(book,'sample')
    assert len(parents)==1
    parent=parents[0];trades=parent['candidate']['trades'];assert len(trades)==1 and D(trades[0]['quantity'])<0
    t=trades[0];quantity=abs(D(t['quantity']));side='SELL'
    body=dict(as_of=parent['decision_at'],sizing=dict(lines=[dict(symbol=t['symbol'],side=side,
        quantity=str(quantity),price=t['execution_price'])]),data_type='synthetic',checks=['RESEARCH_ONLY'])
    book.connection.execute('INSERT INTO plans VALUES(?,?,?,?,?,?,?,?,?,?)',
        ('synthetic-native-sale','synthetic-native-sale',1,'sample','DRAFT','BLOCKED',canonical(body),'0','{}',0))
    request=dict(schema_version=1,request_id='bind-native-group',hedge_id=parent['hedge_id'],
        parent_version=parent['version_hash'],expected_resource_hash=resources(book,'sample'),
        stages=[dict(stage_id='sale',plan_kind='stock',plan_id='synthetic-native-sale',action='OPEN',depends_on=[])],
        reason='Synthetic native-plan group integration')
    original_seq=book.sequence('sample');book.close()
    fingerprint=source_fingerprint();checks=[]
    def run(name,command,payload=None,commit=False,expected=0,as_of=None):
        cmd=[sys.executable,'-m','personal_quant.cli','--config','demo.toml',command,'--account-id','sample']
        if payload is not None:
            file=root/(name+'.json');file.write_text(json.dumps(payload));cmd+=['--file',file.name]
            if commit:cmd+=['--commit']
        if as_of is not None:cmd+=['--as-of',as_of]
        result=subprocess.run(cmd,cwd=root,text=True,capture_output=True,
                              env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src')))
        (root/(name+'.stdout')).write_text(result.stdout);(root/(name+'.stderr')).write_text(result.stderr)
        assert result.returncode==expected,result.stderr
        checks.append(dict(case=name,command=cmd,exit_code=result.returncode))
        return json.loads(result.stdout if expected==0 else result.stderr)
    preview=run('preview','hedge-group',request)
    assert run('stale','hedge-group',dict(request,expected_resource_hash='stale'),True,2)['code']=='STALE_HEDGE_RESOURCES'
    group=run('commit','hedge-group',request,True)
    assert group['group_id']==preview['group_id'] and run('repeat','hedge-group',request,True)==group
    assert run('request-conflict','hedge-group',dict(request,reason='changed'),True,2)['code']=='HEDGE_GROUP_REQUEST_CONFLICT'
    clock=utc(parent['decision_at'])+timedelta(days=1)
    assert run('waiting','hedge-groups',as_of=clock.isoformat())['progress'][0]['status']=='IN_PROGRESS'
    book=Ledger(root/'runtime/demo/account.sqlite','demo')
    close=dict(schema_version=1,request_id='close-parent',hedge_id=parent['hedge_id'],
        expected_version=parent['version_hash'],expected_resource_hash=resources(book,'sample'),
        action='CANCELLED',reason='Synthetic completed group')
    book.close()
    assert run('pending-close','hedge-intent-close',close,True,2)['code']=='UNRESOLVED_HEDGE_EXECUTION'
    def import_receipt(name,q,day):
        e=dict(event_id=name,kind='SELL',symbol=t['symbol'],quantity=str(q),price=t['execution_price'],
               effective_at=(clock+timedelta(days=day)).isoformat(),settlement_at=(clock+timedelta(days=day+1)).isoformat(),
               source='synthetic_group_verifier',evidence_type='test',plan_id='synthetic-native-sale')
        book=Ledger(root/'runtime/demo/account.sqlite','demo')
        result=book.import_events('sample',[e]);again=book.import_events('sample',[e])
        assert result['added']==1 and again['added']==0;book.close()
        (root/(name+'.json')).write_text(json.dumps(e))
    half=quantity//2
    import_receipt('partial',half,0)
    assert run('partial','hedge-groups',as_of=(clock+timedelta(days=1)).isoformat())['progress'][0]['stages'][0]['status']=='PARTIAL'
    import_receipt('remaining',quantity-half,1)
    assert run('settlement','hedge-groups',as_of=(clock+timedelta(days=1)).isoformat())['progress'][0]['stages'][0]['status']=='SETTLEMENT_PENDING'
    assert run('complete','hedge-groups',as_of=(clock+timedelta(days=2)).isoformat())['progress'][0]['status']=='COMPLETE'
    book=Ledger(root/'runtime/demo/account.sqlite','demo');close['expected_resource_hash']=resources(book,'sample');book.close()
    closed=run('close','hedge-intent-close',close,True)
    assert closed['status']=='CANCELLED' and not closed['releases_reservations']
    book=Ledger(root/'runtime/demo/account.sqlite','demo')
    assert book.sequence('sample')==original_seq+2 and records(book,'sample')==parents
    state=book.snapshot('sample',clock+timedelta(days=2))
    assert state['positions'][t['symbol']]=='63'
    assert state['settled_cash']=='7400'
    assert book.connection.execute("SELECT reserved_cash,reserved_positions FROM plans WHERE plan_id='synthetic-native-sale'").fetchone()[0]=='0'
    book.close();assert source_fingerprint()==fingerprint
    proof=dict(status='PASSED',checks=checks,source_fingerprint=fingerprint,data_type='synthetic',
               original_sequence=original_seq,final_sequence=original_seq+2,
               native_facts=2,duplicate_added=0,creates_reservations=False,executable=False)
    (root/'verification.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2))
    print(json.dumps(dict(status='PASSED',checks=len(checks),verification=str(root/'verification.json'))))


if __name__=='__main__':main()

