"""Public CLI proof of a bound protective-put OPEN with delayed receipt clocks."""
import argparse,json,os,subprocess,sys
from pathlib import Path
import numpy as np
import pandas as pd
from personal_quant.common import decimal as D,now_utc
from personal_quant.config import Config
from personal_quant.data.fixture import create_fixture
from personal_quant.data.calendar import Calendar
from personal_quant.data.store import DataStore
from personal_quant.portfolio import Ledger
from personal_quant.hedging.allocation_store import resources
from personal_quant.hedging.securities import register
from personal_quant.strategies.archive import source_fingerprint


def main():
    p=argparse.ArgumentParser();p.add_argument('--workspace',type=Path,required=True)
    p.add_argument('--engine-evidence',type=Path,required=True)
    p.add_argument('--include-close',action='store_true');args=p.parse_args()
    root=args.workspace.absolute();root.mkdir(parents=True,exist_ok=False)
    project=Path(__file__).absolute().parents[1];sys.path.insert(0,str(project/'tests'))
    from test_options_activation_v19 import setup
    from test_options_simulation_v19 import closing_quotes
    from test_hedging_securities_v19 import identity
    from test_hedging_sizing_v19 import policy
    from personal_quant.options.monthly_report import load_monthly_report
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
        file=name+'.json';(root/file).write_text(json.dumps(request));return run(name,[*command,'--file',file],expected)
    run('enable',['v19-init']);book=Ledger(root/'runtime/demo/account.sqlite','demo');book.account('sample')
    store,plan,activation=setup(book,book.path.parent/'options',args.engine_evidence.absolute(),cash=100000,packages=1,template='protective_put',shares=100)
    prices,schedule=create_fixture(root/'fixtures');frame=pd.read_csv(prices);calendar=Calendar.csv(schedule,'synthetic_test_sessions')
    returns=.002*np.sin(np.arange(len(calendar.sessions)-1))+.0001
    for symbol,beta,end in [('SPY',.5,100),('IEF',1.5,200),('GLD',1,150)]:
        path=np.r_[1,np.cumprod(1+beta*returns)];path=path*end/path[-1]
        for field in ('open','high','low','close','adj_close'):frame.loc[frame.symbol==symbol,field]=path
    scale=100/frame.loc[(frame.symbol=='SPY')&(frame.session_date=='2024-10-31'),'close'].iloc[0]
    for field in ('open','high','low','close','adj_close'):frame.loc[frame.symbol=='SPY',field]*=scale
    data=DataStore(book.path.parent/'data');snapshot=data.save(frame,calendar)['snapshot_id']
    monthly=activation['monthly_signal'];clock=monthly['decision_at']
    query=dict(schema_version=1,as_of=clock,knowledge_cutoff=clock,ledger_seq=2,ledger_view='restated',
        valuation_snapshot_id=snapshot,return_snapshot_id=snapshot,benchmark='GLD',window=60,min_r2=.9,max_standard_error=.1,
        max_mark_skew_seconds=86400,max_greek_age_seconds=3600,greeks=[],option_valuation=None)
    risk=call('decision-risk',['hedge-exposure','--account-id','sample','--archive'],query)
    security=register(book.path.parent,'demo',identity())
    option=dict(snapshot_id=monthly['input']['snapshot_id'],selection_request=monthly['input']['request'],
        coverage_request=dict(schema_version=1,as_of=clock,knowledge_cutoff=now_utc(),ledger_seq=2,ledger_view='restated',
            security_ids={'SPY':'security-us-spy'},allocations=[],inflight_plan_ids=[]),greeks=[],funding_quote=None,
        limits=dict(adverse_slippage_fraction=0,early_assignment_cash_reserve=0,max_greek_age_seconds=3600,max_mark_skew_seconds=86400,
            proxy_exit_policy='sell_before_expiry',failed_exit_policy='block_and_require_verified_resolution'))
    spec=policy(scope=['SPY'],benchmark='GLD',mode='share_protection',target_beta=None,protection_fraction=1,tools=['protective_put'],max_days_to_expiry=80)
    parent=call('parent',['hedge-intent','--account-id','sample','--commit'],dict(schema_version=1,request_id='option-parent',expected_version=None,
        expected_resource_hash=resources(book,'sample'),preview_request=dict(exposure_id=risk['exposure_id'],spec=spec,method='protective_put',option=option),
        security_ids={'SPY':'security-us-spy'},security_versions={'SPY':security['record']['version_hash']},decision_at=clock,knowledge_cutoff=now_utc(),
        valid_until='2024-11-05T21:00:00Z',trigger='synthetic_monthly',base_strategy_version='MANUAL_HOLDINGS',timing='historical_research',reason='Synthetic bound replay'))
    group=call('native',['hedge-native-plans','--account-id','sample','--commit'],dict(schema_version=1,request_id='native-option',
        hedge_id=parent['hedge_id'],parent_version=parent['version_hash'],expected_resource_hash=resources(book,'sample'),as_of=activation['as_of'],
        option_risk=plan['request']['risk'],stock_stages=[],include_option_close=True,reason='Bound native option'))['group']
    def phase(exposure,snapshot):
        return dict(group_id=group['group_id'],expected_group_hash=group['record_hash'],expected_resource_hash=resources(book,'sample'),
            stage_id='option-open',exposure_id=exposure,option_snapshot_id=snapshot,
            quote_limits=dict(max_age_seconds=900,max_underlying_skew_seconds=120,max_spread_fraction=.25,max_leg_skew_seconds=10,max_underlying_price_fraction=.01),
            stress=dict(scenarios=[dict(name='down',horizon_date='2024-12-18',benchmark_return=-.2,beta_multiplier=1,residual_returns={'SPY':0},volatility_multiplier=1)],
                models={plan['selection']['legs'][0]['contract_version']:dict(volatility=.2,rate=0,dividend_yield=0)},
                limits=dict(stock_cost_bps=0,option_fee_per_contract=2,adverse_slippage_fraction=0,cash_buffer=0,minimum_sample_equity=0,maximum_sample_loss=100000)))
    current=call('activation-risk',['hedge-exposure','--account-id','sample','--archive'],dict(query,as_of=activation['as_of'],knowledge_cutoff=activation['as_of']))
    assert call('activate',['options','--action','plan-activate','--commit'],dict(activation,hedge_stage_check=phase(current['exposure_id'],activation['quote_snapshot_id'])))['status']=='ACTIVATED'
    signals=sorted((json.loads(f.read_text()) for f in (book.path.parent/'options/monthly').glob('*.json')),key=lambda s:s['decision_at'])
    destination=book.path.parent/'options/monthly-research/late-bound'
    call('compare',['options','--action','monthly-compare','--engine-root',str(project/'.tools/lean'),'--dotnet',str(project/'.tools/dotnet/dotnet'),
        '--destination',str(destination),'--capital','100000','--fee-per-contract','2','--stock-commission-bps','2'],signals)
    closing=closing_quotes(store,activation);contracts,rows,metadata,_=store.load(closing)
    selected={l['contract']['contract_id'] for l in plan['selection']['legs']}
    for row in rows:
        if row['contract_id'] in selected:row.update(available_at='2024-11-04T21:00:00Z',received_at='2024-11-04T21:00:00Z')
    closing=store.save(list(contracts.values()),pd.DataFrame(rows),metadata)['snapshot_id']
    processing='2024-11-04T21:30:00Z';execution=activation['valid_until']
    frozen=call('replay-risk',['hedge-exposure','--account-id','sample','--archive'],dict(query,as_of=execution,knowledge_cutoff=processing,
        execution_replay=dict(plan_kind='option',plan_id=plan['plan_id'],execution_at=execution,processing_at=processing)))
    book.reconcile('sample',dict(account_id='sample',currency='USD',as_of=processing,cash_basis='settled',cash=90000,positions={'SPY':100},equity=100000),{'SPY':100})
    request=dict(plan_id=plan['plan_id'],report_id='late-bound',execution_snapshot_id=closing,as_of=processing,expected_sequence=2,
        state_as_of=execution,hedge_stage_check=phase(frozen['exposure_id'],closing))
    assert call('missing-clock',['options','--action','plan-simulate','--commit'],{k:v for k,v in request.items() if k!='state_as_of'},2)['code']=='HEDGE_REPLAY_STATE_REQUIRED'
    filled=call('fill',['options','--action','plan-simulate','--commit'],request)
    assert call('repeat',['options','--action','plan-simulate','--commit'],request)==filled
    assert filled['status']=='SIMULATED' and filled['account']['positions']=={'SPY':'100'} and D(filled['account']['equity'])==99993
    assert book.sequence('sample')==3 and filled['rows'][0]['effective_at']==execution.replace('Z','+00:00')
    final_equity='99993';final_sequence=3
    if args.include_close:
        from test_options_exit_tasks_v19 import exit_quote
        mask=(frame.symbol=='SPY')&(frame.session_date>='2024-11-29')
        for field in ('open','high','low','close','adj_close'):frame.loc[mask,field]=100
        revised=data.save(frame,calendar)['snapshot_id']
        reference=exit_quote(store,activation,'2024-12-02T20:34:00Z')
        symbol=plan['selection']['legs'][0]['contract']['contract_id'];terms=plan['selection']['legs'][0]['contract_version']
        before_close='2024-12-02T20:35:00Z';close_at='2024-12-02T21:00:00Z';received='2024-12-05T21:30:00Z'
        marks={'SPY':100,symbol:'1.05'}
        def close_query(at,known,snapshot,**extra):
            return dict(query,as_of=at,knowledge_cutoff=known,ledger_seq=3,min_r2=0,max_standard_error=100,
                valuation_snapshot_id=revised,return_snapshot_id=revised,max_mark_skew_seconds=400000,
                greeks=[dict(contract_version=terms,unit='per_share',value=-.5,signed_contracts=1,
                    source='explicit_test',data_type='synthetic',as_of=at,available_at=at,received_at=known,model_inputs={})],
                option_valuation=dict(snapshot_id=snapshot,limits=dict(max_age_seconds=900,max_underlying_skew_seconds=120,
                    max_spread_fraction=.25,max_leg_skew_seconds=10)),**extra)
        book.reconcile('sample',dict(account_id='sample',currency='USD',as_of='2024-12-02T20:33:00Z',cash_basis='settled',
            cash=89888,positions={'SPY':100},option_positions={symbol:1},equity=99993),marks)
        pre=call('exit-risk',['hedge-exposure','--account-id','sample','--archive'],close_query(before_close,before_close,reference))
        closing_phase=dict(phase(pre['exposure_id'],reference),stage_id='option-close')
        review=dict(plan_id=plan['plan_id'],as_of=before_close,snapshot_id=reference,trigger='RISK_REDUCTION',exit_days=7,
            fee_per_contract=2,max_age_seconds=900,max_underlying_skew_seconds=120,max_spread_fraction=.25,
            max_leg_skew_seconds=10,max_underlying_price_fraction=.01,reconciliation_max_days=1)
        freeze_request=dict(request_id='bound-close',review=review,execution_at=close_at,
            purpose='PROTECTION_WITHDRAWAL',expected_sequence=3,hedge_stage_check=closing_phase)
        preview=call('preview-exit',['options','--action','exit-freeze'],freeze_request)
        frozen=call('freeze-exit',['options','--action','exit-freeze','--commit','--expected-hash',preview['preview_hash']],freeze_request)
        exit_id=frozen['proposal']['exit_id'];quote=exit_quote(store,activation,close_at)
        contracts,rows,metadata,_=store.load(quote)
        for row in rows:
            if row['contract_id']==symbol:row.update(available_at=received,received_at=received)
        quote=store.save(list(contracts.values()),pd.DataFrame(rows),metadata)['snapshot_id']
        replay=dict(plan_kind='option',plan_id=plan['plan_id'],exit_id=exit_id,execution_at=close_at,processing_at=received)
        assert call('unknown-exit-risk',['hedge-exposure','--account-id','sample','--archive'],
            close_query(close_at,received,quote,execution_replay=dict(replay,exit_id='unknown')),2)['code']=='UNKNOWN_OPTION_EXIT'
        risk=call('exit-replay-risk',['hedge-exposure','--account-id','sample','--archive'],close_query(close_at,received,quote,execution_replay=replay))
        book.reconcile('sample',dict(account_id='sample',currency='USD',as_of=received,cash_basis='settled',cash=89888,
            positions={'SPY':100},option_positions={symbol:1},equity=99993),marks)
        request=dict(exit_id=exit_id,report_id='late-bound',execution_snapshot_id=quote,as_of=received,expected_sequence=3,
            state_as_of=close_at,hedge_stage_check=dict(phase(risk['exposure_id'],quote),stage_id='option-close'))
        assert call('exit-missing-clock',['options','--action','exit-simulate','--commit'],
            {k:v for k,v in request.items() if k!='state_as_of'},2)['code']=='HEDGE_REPLAY_STATE_REQUIRED'
        assert call('exit-wrong-clock',['options','--action','exit-simulate','--commit'],
            dict(request,state_as_of='2024-12-02T21:01:00Z'),2)['code']=='INVALID_SIMULATION_STATE_TIME'
        exited=call('exit-fill',['options','--action','exit-simulate','--commit'],request)
        assert call('exit-repeat',['options','--action','exit-simulate','--commit'],request)==exited
        assert exited['account']['positions']=={'SPY':'100'} and exited['account']['option_positions']=={}
        assert D(exited['account']['equity'])==99986 and D(exited['account']['settled_cash'])==89986 and book.sequence('sample')==4
        assert exited['rows'][0]['effective_at']==close_at.replace('Z','+00:00')
        assert exited['hedge_stage_check']['processing_as_of']==received.replace('Z','+00:00')
        final_equity='99986';final_sequence=4
    book.close();assert source_fingerprint()==fingerprint
    assert load_monthly_report(destination)['source_fingerprint']==fingerprint
    proof=dict(status='PASSED',source_fingerprint=fingerprint,checks=checks,data_type='synthetic',no_user_account_writes=True,
        execution_at=execution,processing_at=processing,financial_sequence=final_sequence,stock_shares=100,equity=final_equity,
        includes_close=args.include_close)
    (root/'verification.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2))
    print(json.dumps(dict(status='PASSED',checks=len(checks),verification=str(root/'verification.json'))))


if __name__=='__main__':main()
