"""Synthetic lifecycle facts through the actual CLI, in fresh demo workspaces."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from personal_quant.common import digest
from personal_quant.options.contracts import OptionContract
from personal_quant.options.ledger import register_contract
from personal_quant.portfolio import Ledger
from personal_quant.portfolio.schema import apply_workbench_schema,apply_v18_schema,apply_v19_schema
from personal_quant.strategies.archive import source_fingerprint

CLOCK='2026-10-10T00:00:00Z'
BODY={'contract_id':'TEST-SPY-P100-20261009','underlying':'SPY','right':'PUT','strike':100,
      'expiry':'2026-10-09','last_trade_at':'2026-10-09T20:00:00Z','exercise_cutoff_at':'2026-10-09T22:30:00Z',
      'listed_at':'2026-01-01T00:00:00Z','style':'AMERICAN','settlement':'PHYSICAL','currency':'USD',
      'quote_multiplier':100,'deliverable_shares':100,'deliverable_cash':0,'exercise_cash':10000,
      'tick_size':.01,'revision':'v1','evidence_hash':'synthetic_test_contract_terms'}


def fact(identity,kind,**kwargs):
    return {'event_id':identity,'kind':kind,'source':'explicit_synthetic_statement',
        'evidence_type':'test','effective_at':'2026-10-09T19:45:00Z',**kwargs}


def request(rows,seq,name):
    return {'request_id':name,'rows':rows,'expected_hash':digest(rows),'expected_sequence':seq}


def main():
    p=argparse.ArgumentParser();p.add_argument('--destination',type=Path,required=True);a=p.parse_args()
    destination=Path(os.path.abspath(a.destination));destination.mkdir(parents=True,exist_ok=False)
    project=Path(__file__).resolve().parents[1];fingerprint=source_fingerprint();checks=[]
    def workspace(name):
        work=destination/name;work.mkdir();(work/'demo.toml').write_bytes((project/'configs/demo.toml').read_bytes())
        book=Ledger(work/'runtime/demo/account.sqlite','demo');book.account('sample')
        # Isolated empty demo fixture only; real workspace migration uses v19-init.
        with book.transaction():
            apply_workbench_schema(book.connection);apply_v18_schema(book.connection);apply_v19_schema(book.connection)
        return work,book
    def call(work,name,batch,resolutions=None,status='SUCCESS'):
        file=work/(name+'.json');file.write_text(json.dumps(batch))
        command=[sys.executable,'-m','personal_quant.cli','--config','demo.toml','daily','--account-id','sample',
                 '--as-of',CLOCK,'--option-receipts',file.name]
        if resolutions is not None:
            r=work/(name+'-resolve.json');r.write_text(json.dumps(resolutions));command+=['--option-resolutions',r.name]
        run=subprocess.run(command,cwd=work,capture_output=True,text=True,env=os.environ.copy())
        (work/(name+'.stdout.json')).write_text(run.stdout);(work/(name+'.stderr.log')).write_text(run.stderr)
        assert run.returncode==3,(run.returncode,run.stderr)
        result=json.loads(run.stdout);assert result['option_receipts']['status']==status
        checks.append({'workspace':work.name,'case':name,'command':command,'exit_code':run.returncode,
                       'receipt_status':status,'ledger_sequence':result['ledger_seq']})
        return result
    for kind,side,cash,stock,expected_cash in [('OPTION_EXPIRY','BUY',10000,0,9800),
        ('OPTION_ASSIGNMENT','SELL',10000,0,200),('OPTION_EXERCISE','BUY',10200,100,10000)]:
        work,book=workspace(kind.lower());c=register_contract(book,BODY)
        rows=[fact('deposit','DEPOSIT',amount=cash)]
        if stock:rows.append(fact('stock','BUY',symbol='SPY',quantity=stock,price=100,settlement_at='2026-10-09T20:00:00Z'))
        rows.append(fact('open','OPTION_TRADE',contract_version=c.version_hash,quantity=1,action='OPEN',trade_side=side,
                         price=2,settlement_at='2026-10-09T20:00:00Z'))
        book.import_events('sample',rows)
        notice=fact('notice',kind,contract_version=c.version_hash,quantity=1,position_side='SHORT' if side=='SELL' else 'LONG',
                    settlement_at='2026-10-09T22:31:00Z')
        if kind=='OPTION_EXPIRY':notice['effective_at']='2026-10-09T22:31:00Z'
        batch=request([notice],book.sequence('sample'),'lifecycle');book.close()
        first=call(work,'execute',batch);repeat=call(work,'repeat',batch);assert first['report_id']==repeat['report_id']
        book=Ledger(work/'runtime/demo/account.sqlite','demo')
        try:
            state=book.snapshot('sample',CLOCK,{'SPY':90});assert float(state['settled_cash'])==expected_cash
            assert not state['option_positions'];assert book.sequence('sample')==len(rows)+1
            assert state['positions']==({'SPY':'100'} if kind=='OPTION_ASSIGNMENT' else {})
        finally:book.close()
    work,book=workspace('pending');c=OptionContract.from_dict({**BODY,'contract_id':'MISSING-TERMS'})
    raw=fact('late-contract','OPTION_TRADE',contract_version=c.version_hash,quantity=1,action='OPEN',trade_side='BUY',price=2,
             settlement_at='2026-10-09T20:00:00Z');batch=request([raw],0,'pending');book.close()
    blocked=call(work,'pending',batch,status='BLOCKED');assert blocked['ledger_seq']==0
    book=Ledger(work/'runtime/demo/account.sqlite','demo');register_contract(book,c.content());book.close()
    resolved=call(work,'resolve',batch,[{'event_id':raw['event_id'],'expected_sequence':0,'expected_hash':digest(raw)}])
    repeat=call(work,'repeat',batch);assert resolved['ledger_seq']==repeat['ledger_seq']==1
    assert source_fingerprint()==fingerprint
    output={'status':'PASSED','source_fingerprint':fingerprint,'checks':checks,
            'data_type':'synthetic_test_statements','limits':'Supplied facts only; no broker notice or genuine options feed.'}
    (destination/'verification.json').write_text(json.dumps(output,ensure_ascii=False,indent=2))
    print(json.dumps({'status':'PASSED','checks':len(checks),'verification':str(destination/'verification.json')}))


if __name__=='__main__':main()
