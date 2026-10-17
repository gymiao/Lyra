"""Public CLI native stock round trip, with explicitly synthetic funds/prices."""
import argparse,json,os,subprocess,sys
from pathlib import Path
import numpy as np
import pandas as pd
from personal_quant.common import decimal as D
from personal_quant.config import Config
from personal_quant.data.fixture import create_fixture
from personal_quant.data.calendar import Calendar
from personal_quant.data.store import DataStore
from personal_quant.data.catalog import DataCatalog
from personal_quant.portfolio import Ledger
from personal_quant.portfolio.reconciliation import ReconciliationRules
from personal_quant.hedging.allocation_store import resources
from personal_quant.strategies.archive import source_fingerprint


def main():
    p=argparse.ArgumentParser();p.add_argument('--workspace',type=Path,required=True);args=p.parse_args()
    root=args.workspace.absolute();root.mkdir(parents=True,exist_ok=False)
    project=Path(__file__).absolute().parents[1];sys.path.insert(0,str(project/'tests'))
    from test_hedging_intents_v19 import parent
    (root/'demo.toml').write_bytes((project/'configs/demo.toml').read_bytes());config=Config.load(root/'demo.toml')
    fingerprint=source_fingerprint();checks=[]
    def run(name,command,expected=0):
        r=subprocess.run([sys.executable,'-m','personal_quant.cli','--config','demo.toml',*command],cwd=root,
            capture_output=True,text=True,env=dict(os.environ,PYTHONPATH=str(project/'src')))
        (root/(name+'-stdout.json')).write_text(r.stdout);(root/(name+'-stderr.log')).write_text(r.stderr)
        assert r.returncode==expected,r.stderr
        checks.append(dict(name=name,command=command,exit_code=r.returncode))
        return json.loads(r.stdout if expected==0 else r.stderr)
    def call(name,command,request,expected=0):
        file=name+'.json';(root/file).write_text(json.dumps(request))
        return run(name,[*command,'--file',file],expected)
    run('enable',['v19-init'])
    book=Ledger(root/'runtime/demo/account.sqlite','demo');book.account('sample')
    common=dict(source='synthetic_cli_statement',evidence_type='test',effective_at='2024-07-01T20:00:00Z')
    book.import_events('sample',[dict(common,event_id='deposit',kind='DEPOSIT',amount=30000),
        dict(common,event_id='stock',kind='BUY',symbol='SPY',quantity=100,price=100,fee=0,settlement_at='2024-07-02T20:00:00Z')])
    prices,schedule=create_fixture(root/'fixtures');frame=pd.read_csv(prices);calendar=Calendar.csv(schedule,'synthetic_test_sessions')
    returns=.002*np.sin(np.arange(len(calendar.sessions)-1))+.0001
    for symbol,beta,end in [('SPY',.5,100),('IEF',1.5,200),('GLD',1,150)]:
        path=np.r_[1,np.cumprod(1+beta*returns)];path=path*end/path[-1]
        for field in ('open','high','low','close','adj_close'):frame.loc[frame.symbol==symbol,field]=path
    last=frame.loc[pd.to_datetime(frame.session_date)==calendar.sessions[-1]]
    later=Calendar.market('2025-01-16','2025-02-05');extra=[]
    for day in later.sessions:
        rows=last.copy();rows['session_date']=str(day.date());rows['available_at']=(later.close(day)+pd.Timedelta(minutes=30)).isoformat();extra.append(rows)
    frame=pd.concat([frame,*extra],ignore_index=True);calendar=Calendar(pd.concat([calendar.schedule,later.schedule]),calendar.kind)
    store=DataStore(book.path.parent/'data');snapshot=store.save(frame,calendar)['snapshot_id']
    catalog=DataCatalog(book);series=catalog.register(snapshot);catalog.bind('execution',series['series_id'],expected_revision=0)
    query=dict(schema_version=1,as_of='2025-01-15T21:30:00Z',knowledge_cutoff='2025-01-15T21:30:00Z',ledger_seq=2,ledger_view='restated',
        valuation_snapshot_id=snapshot,return_snapshot_id=snapshot,benchmark='GLD',window=126,min_r2=.9,max_standard_error=.1,
        max_mark_skew_seconds=120,max_greek_age_seconds=3600,greeks=[],option_valuation=None)
    original=call('parent',['hedge-intent','--account-id','sample','--commit'],parent((book,config,store,query,calendar)))
    draft=dict(schema_version=1,request_id='open-draft',hedge_id=original['hedge_id'],parent_version=original['version_hash'],
        expected_resource_hash=resources(book,'sample'),as_of=query['as_of'],snapshot_id=snapshot,reason='Synthetic native reduction')
    opening=call('open-draft',['hedge-stock-draft','--account-id','sample','--commit'],draft)
    closing=call('close-draft',['hedge-stock-draft','--account-id','sample','--commit'],dict(draft,request_id='close-draft',
        expected_resource_hash=resources(book,'sample'),reason='Frozen reverse after original window',
        exit=dict(opening_plan_id=opening['plan_id'],execution_session='2025-02-03')))
    group=call('group',['hedge-native-plans','--account-id','sample','--commit'],dict(schema_version=1,request_id='open-close',
        hedge_id=original['hedge_id'],parent_version=original['version_hash'],expected_resource_hash=resources(book,'sample'),as_of=query['as_of'],
        option_risk=None,include_option_close=False,stock_stages=[
            dict(stage_id='sale',plan_kind='stock',plan_id=opening['plan_id'],action='OPEN',depends_on=[]),
            dict(stage_id='restore',plan_kind='stock',plan_id=closing['plan_id'],action='CLOSE',depends_on=['sale'])],reason='Frozen reverse'))['group']
    rules=ReconciliationRules.from_config(config)
    def reconcile(clock,cash,shares):
        book.reconcile('sample',dict(account_id='sample',currency='USD',as_of=clock,cash_basis='settled',cash=cash,
            positions={'SPY':shares},equity=str(D(cash)+shares*100)),{'SPY':100},rules=rules)
    reconcile(query['as_of'],20000,100)
    def phase(name,stage,clock):
        risk=call(name+'-risk',['hedge-exposure','--account-id','sample','--archive'],dict(query,ledger_seq=book.sequence('sample'),as_of=clock,knowledge_cutoff=clock))
        return dict(group_id=group['group_id'],expected_group_hash=group['record_hash'],expected_resource_hash=resources(book,'sample'),
            stage_id=stage,exposure_id=risk['exposure_id'],option_snapshot_id=None,
            quote_limits=dict(max_age_seconds=3600,max_underlying_skew_seconds=120,max_spread_fraction=.2,max_leg_skew_seconds=10,max_underlying_price_fraction=.01),
            stress=dict(scenarios=[dict(name='down',horizon_date=clock[:10],benchmark_return=-.2,beta_multiplier=1,residual_returns={'SPY':0},volatility_multiplier=1)],models={},
                limits=dict(stock_cost_bps=7,option_fee_per_contract=2,adverse_slippage_fraction=0,cash_buffer=0,minimum_sample_equity=0,maximum_sample_loss=10000)))
    def activate(name,plan,stage,clock,expected=0):
        return call(name,['hedge-stock-activate','--account-id','sample','--commit'],dict(schema_version=1,request_id=name,plan_id=plan,
            as_of=clock,expected_resource_hash=resources(book,'sample'),hedge_stage_check=phase(name,stage,clock)),expected)
    assert activate('early',closing['plan_id'],'restore',query['as_of'],2)['code']=='UNRESOLVED_HEDGE_EXECUTION'
    activate('activate-open',opening['plan_id'],'sale',query['as_of'])
    def simulate(name,plan,stage,clock):
        file=name+'-phase.json';(root/file).write_text(json.dumps(phase(name,stage,clock)))
        return run(name,['simulate','--plan-id',plan,'--as-of',clock,'--hedge-stage-check',file])
    assert simulate('fill-open',opening['plan_id'],'sale','2025-01-16T21:30:00Z')['status']=='SUCCESS'
    assert activate('unsettled',closing['plan_id'],'restore','2025-01-16T21:30:00Z',2)['code']=='UNRESOLVED_HEDGE_EXECUTION'
    activate('activate-close',closing['plan_id'],'restore','2025-01-17T21:30:00Z')
    reconcile('2025-01-31T21:30:00Z','23997.2',60)
    assert simulate('fill-close',closing['plan_id'],'restore','2025-02-03T21:30:00Z')['status']=='SUCCESS'
    assert run('repeat-close',['simulate','--plan-id',closing['plan_id'],'--as-of','2025-02-03T21:30:00Z'])['status']=='NO_ACTION'
    state=book.snapshot('sample','2025-02-04T21:30:00Z',{'SPY':100})
    assert book.sequence('sample')==4 and state['positions']=={'SPY':'100'}
    assert D(state['settled_cash'])==D('19994.4') and D(state['equity'])==D('29994.4')
    book.close();assert fingerprint==source_fingerprint()
    proof=dict(status='PASSED',source_fingerprint=fingerprint,checks=checks,data_type='synthetic',
        no_user_account_writes=True,financial_sequence=4,stock_shares=100,final_cash='19994.4',final_equity='29994.4')
    (root/'verification.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2))
    print(json.dumps(dict(status='PASSED',checks=len(checks),verification=str(root/'verification.json'))))


if __name__=='__main__':main()
