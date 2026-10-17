"""Actual CLI amendment checks on an isolated copied synthetic parent account."""
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
    parser=argparse.ArgumentParser();parser.add_argument('--workspace',type=Path,required=True)
    parser.add_argument('--destination',type=Path,required=True);args=parser.parse_args()
    root=args.destination.resolve();root.mkdir(parents=True,exist_ok=False)
    shutil.copytree(args.workspace/'runtime',root/'runtime');shutil.copy2(args.workspace/'demo.toml',root/'demo.toml')
    book=Ledger(root/'runtime/demo/account.sqlite','demo');parent=records(book,'sample')[0]
    t=parent['candidate']['trades'][0];total=abs(D(t['quantity']));first=total//2;rest=total-first
    clock=utc(parent['decision_at']);seq=book.sequence('sample');before=book.snapshot('sample',clock)
    def native(identity,q):
        body=dict(as_of=parent['decision_at'],data_type='synthetic',checks=['RESEARCH_ONLY'],
                  sizing=dict(lines=[dict(symbol=t['symbol'],side='SELL',quantity=str(q),price=t['execution_price'])]))
        book.connection.execute('INSERT INTO plans VALUES(?,?,?,?,?,?,?,?,?,?)',
                                (identity,identity,1,'sample','DRAFT','BLOCKED',canonical(body),'0','{}',0))
    native('old-native',total)
    original=dict(schema_version=1,request_id='original-group',hedge_id=parent['hedge_id'],parent_version=parent['version_hash'],
                  expected_resource_hash=resources(book,'sample'),stages=[dict(stage_id='sale',plan_kind='stock',plan_id='old-native',action='OPEN',depends_on=[])],reason='Synthetic original native stage')
    book.close();source=source_fingerprint();checks=[]
    def run(name,command,request=None,commit=False,as_of=None,expected=0):
        cmd=[sys.executable,'-m','personal_quant.cli','--config','demo.toml',command,'--account-id','sample']
        if request is not None:
            file=root/(name+'.json');file.write_text(json.dumps(request,ensure_ascii=False,indent=2));cmd+=['--file',file.name]
        if commit:cmd+=['--commit']
        if as_of:cmd+=['--as-of',as_of]
        result=subprocess.run(cmd,cwd=root,capture_output=True,text=True,
                              env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src')))
        (root/(name+'.stdout')).write_text(result.stdout);(root/(name+'.stderr')).write_text(result.stderr)
        assert result.returncode==expected,(result.stdout[-1000:],result.stderr)
        checks.append(dict(case=name,command=cmd,exit_code=result.returncode))
        return json.loads(result.stderr if expected==2 else result.stdout)
    group=run('original','hedge-group',original,True)
    def receipt(identity,plan_id,q,day):
        event=dict(event_id=identity,kind='SELL',symbol=t['symbol'],quantity=str(q),price=t['execution_price'],
                   plan_id=plan_id,effective_at=(clock+timedelta(days=day)).isoformat(),
                   settlement_at=(clock+timedelta(days=day+1)).isoformat(),source='synthetic_amendment_statement',evidence_type='test')
        b=Ledger(root/'runtime/demo/account.sqlite','demo');added=b.import_events('sample',[event]);repeat=b.import_events('sample',[event]);b.close()
        assert added['added']==1 and repeat['added']==0
        (root/(identity+'.json')).write_text(json.dumps(event,indent=2))
    receipt('first-fill','old-native',first,1)
    book=Ledger(root/'runtime/demo/account.sqlite','demo');native('new-native',rest)
    request=dict(schema_version=1,request_id='amend-group',previous_group_id=group['group_id'],expected_group_hash=group['record_hash'],
                 expected_resource_hash=resources(book,'sample'),as_of=(clock+timedelta(days=2)).isoformat(),
                 replacements={'sale':'new-native'},reason='Retain old actual fills and replace only remaining quantity')
    book.close()
    assert run('not-ended','hedge-group-revise',request,True,expected=2)['code']=='NATIVE_PLAN_NOT_RELEASED'
    book=Ledger(root/'runtime/demo/account.sqlite','demo');book.connection.execute("UPDATE plans SET execution_status='SUPERSEDED' WHERE plan_id='old-native'")
    request['expected_resource_hash']=resources(book,'sample');book.close()
    assert run('preview','hedge-group-revise',request)['status']=='PREVIEW'
    assert run('stale','hedge-group-revise',dict(request,expected_group_hash='old'),True,expected=2)['code']=='STALE_HEDGE_GROUP_REVISION'
    amended=run('commit','hedge-group-revise',request,True)
    assert amended['revision']==2 and not amended['creates_reservations']
    assert run('repeat','hedge-group-revise',request,True)==amended
    historic=run('historical-view','hedge-groups',as_of=parent['decision_at'])
    assert len(historic['groups'])==2 and historic['progress'][0]['group_id']==group['group_id']
    current=run('current-view','hedge-groups',as_of=(clock+timedelta(days=2)).isoformat())
    assert current['progress'][0]['group_id']==amended['group_id'] and current['progress'][0]['stages'][0]['status']=='COMPLETE'
    receipt('rest-fill','new-native',rest,3)
    assert run('complete','hedge-groups',as_of=(clock+timedelta(days=4)).isoformat())['progress'][0]['status']=='COMPLETE'
    book=Ledger(root/'runtime/demo/account.sqlite','demo');state=book.snapshot('sample',clock+timedelta(days=4))
    assert D(state['positions'][t['symbol']])==D(before['positions'][t['symbol']])-total
    assert D(state['settled_cash'])==D(before['settled_cash'])+total*D(t['execution_price'])
    assert book.sequence('sample')==seq+2
    assert all(D(r[0])==0 for r in book.connection.execute('SELECT reserved_cash FROM plans'));book.close()
    assert source_fingerprint()==source
    proof=dict(status='PASSED',checks=checks,source_fingerprint=source,data_type='synthetic',
               retained_quantity=str(first),replacement_quantity=str(rest),financial_facts_added_by_revision=0,
               final_sequence=seq+2,final_cash=state['settled_cash'],final_positions=state['positions'],executable=False)
    (root/'verification.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2))
    print(json.dumps(dict(status='PASSED',checks=len(checks),verification=str(root/'verification.json'))))


if __name__=='__main__':main()
