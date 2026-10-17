"""Public stock draft/activation CLI verification in an isolated synthetic workspace."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from personal_quant.common import decimal as D
from personal_quant.config import Config
from personal_quant.portfolio import Ledger
from personal_quant.portfolio.reconciliation import ReconciliationRules
from personal_quant.hedging.intents import records
from personal_quant.hedging.archive import load, publish
from personal_quant.hedging.allocation_store import resources
from personal_quant.data.store import DataStore
from personal_quant.strategies.archive import source_fingerprint


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--workspace',type=Path,required=True)
    parser.add_argument('--destination',type=Path,required=True);args=parser.parse_args()
    root=args.destination.resolve();root.mkdir(parents=True,exist_ok=False)
    shutil.copytree(args.workspace/'runtime',root/'runtime')
    # Explicit synthetic verification limit; never modify a user's risk config.
    config_text=(args.workspace/'demo.toml').read_text().replace('max_weight = 0.6','max_weight = 0.8')
    (root/'demo.toml').write_text(config_text)
    config=Config.load(root/'demo.toml');assert config.environment=='demo'
    fingerprint=source_fingerprint();checks=[]
    project=Path(__file__).resolve().parents[1]
    def run(name,command,expected=0):
        result=subprocess.run([sys.executable,'-m','personal_quant.cli','--config','demo.toml',*command],cwd=root,
            capture_output=True,text=True,env=dict(os.environ,PYTHONPATH=str(project/'src')))
        (root/(name+'-stdout.json')).write_text(result.stdout);(root/(name+'-stderr.log')).write_text(result.stderr)
        assert result.returncode==expected,result.stderr
        value=json.loads(result.stdout if expected==0 else result.stderr)
        checks.append(dict(name=name,command=command,exit_code=result.returncode));return value
    def book():return Ledger(root/'runtime/demo/account.sqlite','demo')
    b=book();parent=records(b,'sample')[0];risk=load(b.path.parent/'hedging/exposures',parent['exposure_id'])
    request=dict(schema_version=1,request_id='cli-stock-draft',hedge_id=parent['hedge_id'],parent_version=parent['version_hash'],
        expected_resource_hash=resources(b,'sample'),as_of=parent['decision_at'],snapshot_id=risk['valuation_snapshot_id'],reason='Explicit synthetic stock stage')
    sequence=b.sequence('sample');b.close()
    (root/'draft.json').write_text(json.dumps(request));command=['hedge-stock-draft','--account-id','sample','--file','draft.json']
    preview=run('draft-preview',command);assert preview['status']=='PREVIEW'
    (root/'stale.json').write_text(json.dumps(dict(request,expected_resource_hash='old')))
    failed=run('draft-stale',['hedge-stock-draft','--account-id','sample','--file','stale.json','--commit'],2)
    assert failed['code']=='STALE_HEDGE_RESOURCES'
    draft=run('draft-commit',command+['--commit']);assert draft['status']=='DRAFT'
    assert run('draft-repeat',command+['--commit'])==draft
    review=run('draft-review',['execution-review','--plan-id',draft['plan_id'],'--as-of',request['as_of']])
    assert review['target_weights']=={}
    b=book();binding=dict(schema_version=1,request_id='cli-native-stock-bind',hedge_id=parent['hedge_id'],parent_version=parent['version_hash'],
        expected_resource_hash=resources(b,'sample'),as_of=request['as_of'],option_risk=None,include_option_close=False,
        stock_stages=[dict(stage_id='sale',plan_kind='stock',plan_id=draft['plan_id'],action='OPEN',depends_on=[])],reason='Native generated stock reference')
    b.close();(root/'bind.json').write_text(json.dumps(binding))
    group=run('bind-generated',['hedge-native-plans','--account-id','sample','--file','bind.json','--commit'])['group']
    b=book();marks=risk['account']['prices'];state=b.snapshot('sample',request['as_of'],marks)
    b.reconcile('sample',dict(account_id='sample',currency='USD',as_of=request['as_of'],cash_basis='settled',
        cash=state['settled_cash'],positions=state['positions'],equity=state['equity']),marks,rules=ReconciliationRules.from_config(config))
    new_risk=publish(b,config,DataStore(b.path.parent/'data'),'sample',risk['request'])
    phase=dict(group_id=group['group_id'],expected_group_hash=group['record_hash'],expected_resource_hash=resources(b,'sample'),
        stage_id='sale',exposure_id=new_risk['exposure_id'],option_snapshot_id=None,
        quote_limits=dict(max_age_seconds=3600,max_underlying_skew_seconds=120,max_spread_fraction=.2,max_leg_skew_seconds=10,max_underlying_price_fraction=.01),
        stress=dict(scenarios=[dict(name='down',horizon_date=request['as_of'][:10],benchmark_return=-.2,beta_multiplier=1,
            residual_returns={s:0 for s in state['positions']},volatility_multiplier=1)],models={},
            limits=dict(stock_cost_bps=config.commission_bps+config.slippage_bps,option_fee_per_contract=2,
                adverse_slippage_fraction=0,cash_buffer=0,minimum_sample_equity=0,maximum_sample_loss=10000)))
    activation=dict(schema_version=1,request_id='cli-stock-activate',plan_id=draft['plan_id'],as_of=request['as_of'],
        expected_resource_hash=resources(b,'sample'),hedge_stage_check=phase)
    b.close();(root/'activate.json').write_text(json.dumps(activation))
    command=['hedge-stock-activate','--account-id','sample','--file','activate.json']
    assert run('activation-preview',command)['status']=='PREVIEW'
    activated=run('activation-commit',command+['--commit']);assert activated['status']=='READY'
    assert run('activation-repeat',command+['--commit'])==activated
    b=book();assert b.sequence('sample')==sequence
    assert D(b.snapshot('sample',request['as_of'])['reserved_cash'])==0
    assert b.snapshot('sample',request['as_of'])['positions']==state['positions'];b.close()
    assert source_fingerprint()==fingerprint
    proof=dict(status='PASSED',source_fingerprint=fingerprint,checks=checks,data_type='synthetic',
        financial_events_added=0,no_user_account_writes=True,plan_id=draft['plan_id'],group_id=group['group_id'])
    (root/'verification.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2))
    print(json.dumps(dict(status='PASSED',checks=len(checks),verification=str(root/'verification.json'))))


if __name__=='__main__':main()
