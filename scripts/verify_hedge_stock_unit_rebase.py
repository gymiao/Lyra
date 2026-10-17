"""Public CLI supplied stock split, all-stage rebase and roundtrip, synthetic only."""
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
        assert r.returncode in (expected if isinstance(expected,tuple) else (expected,)),(r.returncode,r.stdout,r.stderr)
        checks.append(dict(name=name,command=command,exit_code=r.returncode))
        return json.loads(r.stdout or r.stderr)
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
    later=Calendar.market('2025-01-16','2025-01-31');extra=[]
    for day in later.sessions:
        rows=last.copy();rows['session_date']=str(day.date());rows['available_at']=(later.close(day)+pd.Timedelta(minutes=30)).isoformat()
        price=100 if str(day.date())=='2025-01-16' else 110 if day<=pd.Timestamp('2025-01-21') else 120
        for field in ('open','high','low','close','adj_close'):rows.loc[rows.symbol=='SPY',field]=price
        extra.append(rows)
    frame=pd.concat([frame,*extra],ignore_index=True);calendar=Calendar(pd.concat([calendar.schedule,later.schedule]),calendar.kind)
    store=DataStore(book.path.parent/'data');snapshot=store.save(frame,calendar)['snapshot_id']
    catalog=DataCatalog(book);series=catalog.register(snapshot);catalog.bind('execution',series['series_id'],expected_revision=0);catalog.bind('valuation',series['series_id'],expected_revision=0)
    query=dict(schema_version=1,as_of='2025-01-15T21:30:00Z',knowledge_cutoff='2025-01-15T21:30:00Z',ledger_seq=2,ledger_view='restated',
        valuation_snapshot_id=snapshot,return_snapshot_id=snapshot,benchmark='GLD',window=126,min_r2=0,max_standard_error=100,
        max_mark_skew_seconds=120,max_greek_age_seconds=3600,greeks=[],option_valuation=None)
    original=call('parent',['hedge-intent','--account-id','sample','--commit'],parent((book,config,store,query,calendar)))
    draft=dict(schema_version=1,request_id='open-draft',hedge_id=original['hedge_id'],parent_version=original['version_hash'],
        expected_resource_hash=resources(book,'sample'),as_of=query['as_of'],snapshot_id=snapshot,reason='Synthetic native reduction')
    opening=call('open-draft',['hedge-stock-draft','--account-id','sample','--commit'],draft)
    closing=call('close-draft',['hedge-stock-draft','--account-id','sample','--commit'],dict(draft,request_id='close-draft',
        expected_resource_hash=resources(book,'sample'),reason='Frozen reverse after original window',
        exit=dict(opening_plan_id=opening['plan_id'],execution_session='2025-01-21')))
    group=call('group',['hedge-native-plans','--account-id','sample','--commit'],dict(schema_version=1,request_id='open-close',
        hedge_id=original['hedge_id'],parent_version=original['version_hash'],expected_resource_hash=resources(book,'sample'),as_of=query['as_of'],
        option_risk=None,include_option_close=False,stock_stages=[
            dict(stage_id='sale',plan_kind='stock',plan_id=opening['plan_id'],action='OPEN',depends_on=[]),
            dict(stage_id='restore',plan_kind='stock',plan_id=closing['plan_id'],action='CLOSE',depends_on=['sale'])],reason='Frozen reverse'))['group']
    rules=ReconciliationRules.from_config(config)
    def reconcile(clock,cash,shares,price=100):
        book.reconcile('sample',dict(account_id='sample',currency='USD',as_of=clock,cash_basis='settled',cash=cash,
            positions={'SPY':shares},equity=str(D(cash)+shares*price)),{'SPY':price},rules=rules)
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
    def cancelled(name,plan):
        result=run(name,['manage-plan','--plan-id',plan,'--action','cancel'],(0,3))
        assert checks[-1]['exit_code']==(3 if result['check_status']=='BLOCKED' else 0)
        assert result['execution_status']=='CANCELLED' and result['reserved_cash']=='0' and not result['reserved_positions'] and not result['manual_pending']
        return result
    def import_bill(name,rows,clock):
        bill=root/(name+'.csv');pd.DataFrame(rows).to_csv(bill,index=False)
        preview=run(name+'-preview',['import-events','--account-id','sample','--file',bill.name,'--as-of',clock])
        result=run(name,['import-events','--account-id','sample','--file',bill.name,'--as-of',clock,'--commit',
            '--expected-sequence',str(preview['expected_sequence']),'--expected-hash',preview['batch_hash']])
        assert result['added']==len(rows)
    common=dict(account_id='sample',source='synthetic_cli_statement',evidence_type='test',currency='USD',
        amount=0,ratio=1,reference_event_id='')
    import_bill('partial-and-split',[
        dict(common,event_id='original-sale',kind='SELL',effective_at='2025-01-16T21:00:00Z',symbol='SPY',quantity=20,price=100,
            fee='1.4',settlement_at='2025-01-17T21:00:00Z',plan_id=opening['plan_id']),
        dict(common,event_id='split-two',kind='SPLIT',effective_at='2025-01-17T14:30:00Z',symbol='SPY',ratio=2)],'2025-01-17T21:30:00Z')
    cancelled('cancel-old-sale',opening['plan_id']);cancelled('cancel-old-close',closing['plan_id'])
    dates=pd.to_datetime(frame.session_date)
    selected=(frame.symbol=='SPY')&(dates>=pd.Timestamp('2025-01-17'))
    for field in ('open','high','low','close'):frame.loc[selected,field]/=2
    frame.loc[(frame.symbol=='SPY')&(dates==pd.Timestamp('2025-01-17')),'split_ratio']=2
    snapshot=store.save(frame,calendar)['snapshot_id'];catalog.register(snapshot)
    query.update(valuation_snapshot_id=snapshot,return_snapshot_id=snapshot)
    reconcile('2025-01-17T21:30:00Z','21998.6',160,55)
    from personal_quant.hedging.stock_units import stage_quantities
    def unit_draft(name,old,stage,target):
        clock='2025-01-17T21:30:00Z';check=phase(name,stage,clock)
        body=json.loads(book.connection.execute('SELECT payload FROM plans WHERE plan_id=?',(old,)).fetchone()[0])
        lines=next(s['lines'] for s in group['stages'] if s['stage_id']==stage)
        actions=stage_quantities(book.active_events('sample',clock),old,lines,body['as_of'],clock,origin_seq=body['snapshot']['ledger_seq'])['actions']
        request=dict(schema_version=1,request_id=name,plan_id=old,group_id=group['group_id'],expected_group_hash=group['record_hash'],
            expected_resource_hash=resources(book,'sample'),exposure_id=check['exposure_id'],as_of=clock,execution_session=target,
            reason='Explicit actual test split; preserve original economic quantity',unit_actions=actions)
        before=book.sequence('sample')
        preview=call(name+'-preview',['hedge-stock-unit-rebase','--account-id','sample'],request)
        new=call(name,['hedge-stock-unit-rebase','--account-id','sample','--commit'],request)
        assert call(name+'-repeat',['hedge-stock-unit-rebase','--account-id','sample','--commit'],request)==new
        assert new['plan_id']==preview['plan_id'] and not new['creates_reservations'] and book.sequence('sample')==before
        return new['plan_id']
    sale=unit_draft('sale-units',opening['plan_id'],'sale','2025-01-21')
    close=unit_draft('close-units',closing['plan_id'],'restore','2025-01-21')
    revision=dict(schema_version=1,request_id='units-bind',previous_group_id=group['group_id'],expected_group_hash=group['record_hash'],
        expected_resource_hash=resources(book,'sample'),as_of='2025-01-17T21:30:00Z',replacements={'sale':sale},reason='All unit obligations')
    assert call('reject-incomplete',['hedge-group-revise','--account-id','sample','--commit'],revision,2)['code']=='INCOMPLETE_STOCK_UNIT_REVISION'
    revision['replacements']['restore']=close
    group=call('unit-group',['hedge-group-revise','--account-id','sample','--commit'],revision)
    assert call('unit-group-repeat',['hedge-group-revise','--account-id','sample','--commit'],revision)==group
    activate('activate-sale',sale,'sale','2025-01-17T21:30:00Z')
    assert simulate('fill-sale',sale,'sale','2025-01-21T21:30:00Z')['status']=='SUCCESS'
    # Closing must wait for settlement. Record a test partial exit at a later
    # explicit session by first repricing the original frozen closing window.
    cancelled('cancel-close-price',close);reconcile('2025-01-22T21:30:00Z','24197.06',120,60)
    check=phase('close-quote','restore','2025-01-22T21:30:00Z')
    request=dict(schema_version=1,request_id='close-quote',plan_id=close,group_id=group['group_id'],expected_group_hash=group['record_hash'],
        expected_resource_hash=resources(book,'sample'),exposure_id=check['exposure_id'],as_of='2025-01-22T21:30:00Z',execution_session='2025-01-23',
        reason='New quote, retain rebased close quantity and fixed window')
    new=call('close-quote',['hedge-stock-reprice','--account-id','sample','--commit'],request)['plan_id']
    group=call('close-quote-bind',['hedge-group-revise','--account-id','sample','--commit'],dict(schema_version=1,request_id='close-quote-bind',
        previous_group_id=group['group_id'],expected_group_hash=group['record_hash'],expected_resource_hash=resources(book,'sample'),
        as_of='2025-01-22T21:30:00Z',replacements={'restore':new},reason='Keep split units, original obligation'))
    activate('activate-close',new,'restore','2025-01-22T21:30:00Z')
    assert simulate('fill-close',new,'restore','2025-01-23T21:30:00Z')['status']=='SUCCESS'
    assert run('repeat-close',['simulate','--plan-id',new,'--as-of','2025-01-23T21:30:00Z'])['status']=='NO_ACTION'
    state=book.snapshot('sample','2025-01-24T21:30:00Z',{'SPY':60})
    assert book.sequence('sample')==6 and set(state['positions'])=={'SPY'} and D(state['positions']['SPY'])==200
    assert D(state['settled_cash'])==D('19393.70') and D(state['equity'])==D('31393.70')
    from personal_quant.hedging.groups import progress
    assert progress(book,'sample',group,'2025-01-24T21:30:00Z')['status']=='COMPLETE'
    run('backup',['backup-bundle','--destination',str(root/'bundle')])
    run('verify',['verify-backup','--source',str(root/'bundle'),'--environment','demo'])
    run('restore',['restore','--source',str(root/'bundle'),'--environment','demo','--destination',str(root/'restored')])
    recovered=Ledger(root/'restored/runtime/demo/account.sqlite','demo')
    try:
        assert D(recovered.snapshot('sample','2025-01-24T21:30:00Z',{'SPY':60})['settled_cash'])==D('19393.70')
        assert progress(recovered,'sample',group,'2025-01-24T21:30:00Z')['status']=='COMPLETE'
    finally:recovered.close()
    book.close();assert fingerprint==source_fingerprint()
    proof=dict(status='PASSED',source_fingerprint=fingerprint,checks=checks,data_type='synthetic',no_user_account_writes=True,
        financial_sequence=6,stock_shares=200,final_cash='19393.70',final_equity='31393.70')
    (root/'verification.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2))
    print(json.dumps(dict(status='PASSED',checks=len(checks),verification=str(root/'verification.json'))))


if __name__=='__main__':main()
