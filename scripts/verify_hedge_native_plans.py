"""Actual CLI native-reference generation and stress checks; all inputs synthetic."""
import argparse,json,os,shutil,subprocess,sys
from pathlib import Path
from zoneinfo import ZoneInfo
from personal_quant.common import canonical,decimal as D,utc
from personal_quant.portfolio import Ledger
from personal_quant.hedging.intents import records
from personal_quant.hedging.archive import load
from personal_quant.hedging.allocation_store import resources
from personal_quant.strategies.archive import source_fingerprint


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--workspace',type=Path,required=True)
    parser.add_argument('--destination',type=Path,required=True);args=parser.parse_args()
    root=args.destination.resolve();root.mkdir(parents=True,exist_ok=False)
    shutil.copytree(args.workspace/'runtime',root/'runtime');shutil.copy2(args.workspace/'demo.toml',root/'demo.toml')
    b=Ledger(root/'runtime/demo/account.sqlite','demo');parent=records(b,'sample')[0]
    risk=load(b.path.parent/'hedging/exposures',parent['exposure_id']);trade=parent['candidate']['trades'][0]
    q=abs(D(trade['quantity']));price=D(trade['execution_price'])
    body=dict(as_of=parent['decision_at'],sizing=dict(lines=[dict(symbol=trade['symbol'],side='SELL',quantity=str(q),price=str(price))]))
    b.connection.execute('INSERT INTO plans VALUES(?,?,?,?,?,?,?,?,?,?)',('stage-native','stage-native',1,'sample','DRAFT','BLOCKED',canonical(body),'0','{}',0))
    original=dict(schema_version=1,request_id='native-group',hedge_id=parent['hedge_id'],parent_version=parent['version_hash'],
        expected_resource_hash=resources(b,'sample'),as_of=parent['decision_at'],option_risk=None,include_option_close=False,
        stock_stages=[dict(stage_id='sale',plan_kind='stock',plan_id='stage-native',action='OPEN',depends_on=[])],reason='Synthetic existing stock reference generation')
    b.close();fingerprint=source_fingerprint();checks=[]
    def run(name,command,request,expected=0):
        (root/(name+'.json')).write_text(json.dumps(request,ensure_ascii=False,indent=2))
        cmd=[sys.executable,'-m','personal_quant.cli','--config','demo.toml',command,'--account-id','sample','--file',name+'.json']
        if command=='hedge-native-plans' and name!='preview':cmd+=['--commit']
        result=subprocess.run(cmd,cwd=root,capture_output=True,text=True,env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src')))
        (root/(name+'.stdout')).write_text(result.stdout);(root/(name+'.stderr')).write_text(result.stderr)
        assert result.returncode==expected,(result.stdout[-1000:],result.stderr[-1000:])
        checks.append(dict(case=name,command=cmd,exit_code=result.returncode))
        return json.loads(result.stderr if expected==2 else result.stdout)
    assert run('preview','hedge-native-plans',original)['status']=='PREVIEW'
    assert run('stale-generation','hedge-native-plans',{**original,'expected_resource_hash':'old'},2)['code']=='STALE_HEDGE_RESOURCES'
    generated=run('bind','hedge-native-plans',original)
    assert generated['status']=='GENERATED_DRAFTS' and generated['option_plan_id'] is None
    assert run('repeat-generation','hedge-native-plans',original)==generated
    group=generated['group']
    b=Ledger(root/'runtime/demo/account.sqlite','demo');basis=resources(b,'sample');sequence=b.sequence('sample');b.close()
    symbols=set(risk['account']['positions'])
    request=dict(group_id=group['group_id'],expected_group_hash=group['record_hash'],expected_resource_hash=basis,
        stage_id='sale',exposure_id=parent['exposure_id'],option_snapshot_id=None,
        quote_limits=dict(max_age_seconds=3600,max_underlying_skew_seconds=120,max_spread_fraction=.2,
                          max_leg_skew_seconds=10,max_underlying_price_fraction=.01),
        stress=dict(scenarios=[dict(name='decline',horizon_date=utc(risk['as_of']).astimezone(ZoneInfo('America/New_York')).date().isoformat(),
            benchmark_return=-.2,beta_multiplier=1,residual_returns={s:0 for s in symbols},volatility_multiplier=1)],
            models={},limits=dict(stock_cost_bps=10,option_fee_per_contract=2,adverse_slippage_fraction=0,
            cash_buffer=0,minimum_sample_equity=0,maximum_sample_loss=100000)))
    first=run('check','hedge-stage-check',request);assert first['status']=='CHECKED'
    assert run('repeat','hedge-stage-check',request)==first
    assert run('stale','hedge-stage-check',{**request,'expected_resource_hash':'old'},2)['code']=='STALE_HEDGE_RESOURCES'
    assert D(first['vertices'][1]['friction'])==q*price/D(1000)
    b=Ledger(root/'runtime/demo/account.sqlite','demo');assert b.sequence('sample')==sequence and resources(b,'sample')==basis;b.close()
    assert source_fingerprint()==fingerprint
    proof=dict(status='PASSED',checks=checks,source_fingerprint=fingerprint,data_type='synthetic',financial_events_added=0,
               stock_scope='existing_native_format_reference_only',vertex_count=2,friction=first['vertices'][1]['friction'],execution_qualification='NOT_GRANTED')
    (root/'verification.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2))
    print(json.dumps(dict(status='PASSED',checks=len(checks),verification=str(root/'verification.json'))))

if __name__=='__main__':main()
