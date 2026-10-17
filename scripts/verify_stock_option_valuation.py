"""Actual CLI stock-plan flow with explicit synthetic option valuation inputs."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import pandas as pd
from personal_quant.common import decimal as D
from personal_quant.config import Config
from personal_quant.data.calendar import Calendar
from personal_quant.data.catalog import DataCatalog
from personal_quant.data.fixture import create_fixture
from personal_quant.data.store import DataStore
from personal_quant.options.data import OptionDataStore
from personal_quant.options.ledger import register_contract
from personal_quant.portfolio import Ledger
from personal_quant.portfolio.backup import create_bundle,verify_bundle,restore_bundle
from personal_quant.portfolio.reconciliation import ReconciliationRules
from personal_quant.portfolio.schema import apply_workbench_schema,apply_v18_schema,apply_v19_schema
from personal_quant.strategies.archive import source_fingerprint


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--destination',type=Path,required=True)
    root=parser.parse_args().destination.resolve();root.mkdir(parents=True,exist_ok=False)
    repo=Path(__file__).resolve().parents[1]
    text=(repo/'configs/demo.toml').read_text()
    overrides={'symbols':'["SPY"]','weights':'[0.5]','active_strategy':'"fixed"','commission_bps':'0.0',
               'slippage_bps':'0.0','max_weight':'1.0','cash_buffer':'0.0'}
    lines=[line.split(' = ')[0]+' = '+overrides[line.split(' = ')[0]]
           if line.split(' = ')[0] in overrides else line for line in text.splitlines()]
    path=root/'demo.toml';path.write_text('\n'.join(lines)+'\n');cfg=Config.load(path)
    prices,sessions=create_fixture(root/'fixture');calendar=Calendar.csv(sessions,'synthetic_test_sessions')
    frame=pd.read_csv(prices);frame[['open','high','low','close','adj_close']]=100.0
    book=Ledger(root/'runtime/demo/account.sqlite','demo');book.account('sample')
    with book.transaction():
        apply_workbench_schema(book.connection);apply_v18_schema(book.connection);apply_v19_schema(book.connection)
    stock=DataStore(book.path.parent/'data');meta=stock.save(frame,calendar)
    for role in ('signal','execution','valuation'):
        DataCatalog(book).bind(role,meta['snapshot_id'],expected_revision=0)
    terms=json.loads((repo/'examples/options/contracts.json').read_text())[0]
    terms.update(right='PUT',listed_at='2024-01-01T00:00:00Z');c=register_contract(book,terms)
    def event(identity,kind,**values):
        return dict(event_id=identity,kind=kind,source='synthetic_stock_option_verifier',evidence_type='test',
                    effective_at='2024-07-31T20:00:00Z',settlement_at='2024-07-31T20:00:00Z',**values)
    book.import_events('sample',[event('capital','DEPOSIT',amount=1000),
        event('put','OPTION_TRADE',contract_version=c.version_hash,quantity=1,action='OPEN',trade_side='BUY',price=2)])
    options=OptionDataStore(book.path.parent/'options/chains')
    limits={'max_age_seconds':7200,'max_underlying_skew_seconds':10,'max_spread_fraction':.2,'max_leg_skew_seconds':10}
    def mark(day,name):
        q={'contract_id':c.contract_id,'contract_version':c.version_hash,'exchange_timestamp':day+'T20:00:00Z',
           'available_at':day+'T20:00:02Z','received_at':day+'T20:00:04Z','bid':2,'ask':2.1,
           'bid_size':10,'ask_size':10,'last':2.05,'last_timestamp':day+'T20:00:00Z',
           'volume':100,'open_interest':200,'open_interest_available_at':day+'T12:00:00Z',
           'underlying_price':100,'underlying_timestamp':day+'T20:00:00Z','source':'synthetic_options_v1'}
        m={'schema_version':1,'source':'synthetic_options_v1','data_type':'synthetic','license_terms':'local test only',
           'unit_evidence':'synthetic terms, not OCC evidence','available_time_basis':'frozen synthetic timestamps'}
        sid=options.save([c],pd.DataFrame([q]),m)['snapshot_id']
        (root/name).write_text(json.dumps({'snapshot_id':sid,'limits':limits},indent=2))
    mark('2024-07-31','decision-marks.json');mark('2024-08-01','fill-marks.json')
    book.reconcile('sample',{'account_id':'sample','currency':'USD','as_of':'2024-07-31T21:00:00Z',
                   'cash_basis':'settled','cash':800,'positions':{},'option_positions':{c.contract_id:1},'equity':1005},
                   {c.contract_id:2.05},rules=ReconciliationRules.from_config(cfg));book.close()
    source=source_fingerprint();checks=[]
    def run(name,args,expected=0):
        cmd=[sys.executable,'-m','personal_quant.cli','--config','demo.toml',*args]
        r=subprocess.run(cmd,cwd=root,capture_output=True,text=True,env=dict(os.environ,PYTHONPATH=str(repo/'src')))
        (root/(name+'.stdout')).write_text(r.stdout);(root/(name+'.stderr')).write_text(r.stderr)
        assert r.returncode==expected,(r.returncode,r.stdout[-1000:],r.stderr)
        checks.append(dict(case=name,command=cmd,exit_code=r.returncode))
        return json.loads(r.stderr if expected==2 else r.stdout)
    blocked=run('missing-marks',['plan','--account-id','sample','--session','2024-07-31','--as-of','2024-07-31T21:00:00Z'],3)
    assert blocked['payload']['checks'][0]['code']=='OPTION_VALUATION_REQUEST_REQUIRED'
    ready=run('qualified-revision',['revise-plan','--plan-id',blocked['plan_id'],'--as-of','2024-07-31T21:00:00Z',
                                    '--option-valuation','decision-marks.json'])
    assert D(ready['payload']['snapshot']['equity'])==1005 and D(ready['payload']['sizing']['lines'][0]['quantity'])==5
    book=Ledger(root/'runtime/demo/account.sqlite','demo')
    previous_directory=Path.cwd()
    try:
        os.chdir(root)
        create_bundle(book.path.parent,path,root/'ready-backup')
        verify_bundle(root/'ready-backup','demo');restore_bundle(root/'ready-backup',root/'restored','demo')
    finally:
        os.chdir(previous_directory);book.close()
    restored=Ledger(root/'restored/runtime/demo/account.sqlite','demo')
    assert restored.sequence('sample')==2
    restored_plan=json.loads(restored.connection.execute('SELECT payload FROM plans WHERE plan_id=?',(ready['plan_id'],)).fetchone()[0])
    assert restored_plan['option_valuation']==ready['payload']['option_valuation'];restored.close()
    base=['simulate','--plan-id',ready['plan_id'],'--as-of','2024-08-01T21:00:00Z']
    assert run('fill-missing',base,2)['code']=='OPTION_VALUATION_REQUEST_REQUIRED'
    assert run('fill-qualified',[*base,'--option-valuation','fill-marks.json'])['status']=='SUCCESS'
    assert run('repeat-filled',base)['status']=='NO_ACTION'
    book=Ledger(root/'runtime/demo/account.sqlite','demo')
    state=book.snapshot('sample','2024-08-02T21:00:00Z',{'SPY':100,c.contract_id:2.05})
    assert D(state['settled_cash'])==300 and D(state['equity'])==1005 and D(state['positions']['SPY'])==5
    assert state['option_positions']=={c.contract_id:'1'} and book.sequence('sample')==3;book.close()
    assert source_fingerprint()==source
    proof=dict(status='PASSED',checks=checks,source_fingerprint=source,data_type='synthetic',
               initial_equity='1005',final_equity='1005',final_cash='300',shares=5,
               backup_restore='verified before fill',broker_orders=False)
    (root/'verification.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2))
    print(json.dumps(dict(status='PASSED',checks=len(checks),verification=str(root/'verification.json'))))


if __name__=='__main__':main()
