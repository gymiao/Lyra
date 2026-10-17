"""Actual daily CLI proof using explicitly synthetic lifecycle statements."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from personal_quant.common import digest
from personal_quant.options.ledger import register_contract
from personal_quant.options.receipt_risk import history
from personal_quant.portfolio import Ledger
from personal_quant.portfolio.schema import apply_workbench_schema,apply_v18_schema,apply_v19_schema
from personal_quant.strategies.archive import source_fingerprint


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--destination',type=Path,required=True)
    root=parser.parse_args().destination.resolve();root.mkdir(parents=True,exist_ok=False)
    repo=Path(__file__).resolve().parents[1]
    shutil.copy2(repo/'configs/demo.toml',root/'demo.toml')
    book=Ledger(root/'runtime/demo/account.sqlite','demo');book.account('sample')
    with book.transaction():
        apply_workbench_schema(book.connection);apply_v18_schema(book.connection);apply_v19_schema(book.connection)
    base=json.loads((repo/'examples/options/contracts.json').read_text())[0]
    base.update(expiry='2026-10-09',last_trade_at='2026-10-09T20:00:00Z',
                exercise_cutoff_at='2026-10-09T22:30:00Z',strike='100',exercise_cash='10000')
    terms=[]
    for right in ('PUT','CALL'):
        body={**base,'right':right,'contract_id':'SPY-SYNTHETIC-RISK-'+right}
        terms.append(register_contract(book,body))
    def fact(identity,kind,**kw):
        return dict(event_id=identity,kind=kind,source='synthetic_prefix_verifier',evidence_type='test',
                    effective_at='2026-10-09T19:45:00Z',settlement_at='2026-10-09T20:00:00Z',**kw)
    book.import_events('sample',[fact('deposit','DEPOSIT',amount=20000)]+[
        fact('open-'+c.right,'OPTION_TRADE',contract_version=c.version_hash,quantity=1,
             action='OPEN',trade_side='BUY',price=2) for c in terms])
    rows=[fact('exercise-'+c.right,'OPTION_EXERCISE',contract_version=c.version_hash,
               quantity=1,position_side='LONG') for c in terms]
    request=dict(request_id='synthetic-statement',rows=rows,expected_sequence=3,expected_hash=digest(rows))
    (root/'receipt.json').write_text(json.dumps(request,indent=2));book.close()
    source=source_fingerprint();checks=[]
    def run(name,filename):
        cmd=[sys.executable,'-m','personal_quant.cli','--config','demo.toml','daily',
             '--account-id','sample','--as-of','2026-10-10T00:00:00Z','--option-receipts',filename]
        result=subprocess.run(cmd,cwd=root,capture_output=True,text=True,
                              env=dict(os.environ,PYTHONPATH=str(repo/'src')))
        (root/(name+'.stdout')).write_text(result.stdout);(root/(name+'.stderr')).write_text(result.stderr)
        # Deliberately no execution-data binding: daily must remain blocked.
        assert result.returncode==3,result.stderr
        output=json.loads(result.stdout)
        assert output['status']=='BLOCKED' and output['data']['code']=='UNASSIGNED_DATA_ROLE'
        assert output['option_receipts']['status']=='SUCCESS'
        checks.append(dict(case=name,command=cmd,exit_code=result.returncode,daily_status=output['status']))
        return output['option_receipts']['audits'][0]
    original=run('import','receipt.json');repeat=run('repeat','receipt.json')
    assert original==repeat
    risk=original['risk_history'];first,second=risk['prefixes']
    assert first['snapshot']['positions']=={'SPY':'-100'} and first['status']=='REVIEW_REQUIRED'
    assert second['snapshot']['positions']=={} and risk['final_snapshot']['settled_cash']=='19600'
    assert risk['has_intermediate_anomaly'] and not risk['current_account_anomaly']
    duplicate={**request,'request_id':'second-synthetic-file','expected_sequence':5}
    (root/'duplicate.json').write_text(json.dumps(duplicate,indent=2))
    assert run('duplicate-file','duplicate.json')['risk_history']['prefixes']==[]
    book=Ledger(root/'runtime/demo/account.sqlite','demo')
    assert book.sequence('sample')==5 and len(history(book,'sample'))==2
    assert book.snapshot('sample','2026-10-10T00:00:00Z')['settled_cash']=='19600';book.close()
    assert source_fingerprint()==source
    proof=dict(status='PASSED',checks=checks,source_fingerprint=source,data_type='synthetic',
               ledger_sequence=5,intermediate_position='-100',final_cash='19600',
               market_data='not_downloaded; missing daily data remains explicitly blocked',
               valuation_qualification='NOT_EVALUATED',broker_orders=False)
    (root/'verification.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2))
    print(json.dumps(dict(status='PASSED',checks=len(checks),verification=str(root/'verification.json'))))


if __name__=='__main__':main()
