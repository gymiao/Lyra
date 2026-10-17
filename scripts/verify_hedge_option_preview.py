"""Actual CLI quantity checks using frozen synthetic stocks and option quotes."""
import argparse
from datetime import timedelta,datetime,time
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from zoneinfo import ZoneInfo
import pandas as pd
from personal_quant.common import now_utc,utc
from personal_quant.portfolio import Ledger
from personal_quant.data.store import DataStore
from personal_quant.options.contracts import OptionContract
from personal_quant.options.data import OptionDataStore
from personal_quant.strategies.archive import source_fingerprint

def main():
    p=argparse.ArgumentParser();p.add_argument('--workspace',type=Path,required=True);p.add_argument('--destination',type=Path,required=True)
    a=p.parse_args();root=a.destination.resolve();root.mkdir(parents=True,exist_ok=False)
    shutil.copytree(a.workspace/'runtime',root/'runtime');shutil.copy2(a.workspace/'demo.toml',root/'demo.toml')
    runtime=root/'runtime/demo';book=Ledger(runtime/'account.sqlite','demo')
    old=json.loads((a.workspace/'preview.json').read_text())
    risk=json.loads((runtime/'hedging/exposures'/old['exposure_id']/'exposure.json').read_text())
    assert risk['data_types']==['synthetic'] and risk['ledger_seq']==book.sequence('sample')
    _,_,cal=DataStore(runtime/'data').load(risk['valuation_snapshot_id'])
    close=cal.close(risk['valuation']['quotes']['SPY']['session']);stamp=close.isoformat()
    expiry=utc(risk['as_of']).astimezone(ZoneInfo('America/New_York')).date()+timedelta(days=45)
    expiry+=timedelta(days=(4-expiry.weekday())%7)
    last=datetime.combine(expiry,time(16),ZoneInfo('America/New_York')).astimezone(ZoneInfo('UTC'))
    cs=[];rows=[]
    for right,strike in [('PUT',95),('CALL',105)]:
        c=OptionContract.from_dict(dict(contract_id='SYNTHETIC-SPY-'+right,underlying='SPY',right=right,strike=strike,
            expiry=expiry.isoformat(),last_trade_at=last.isoformat(),exercise_cutoff_at=(last+timedelta(minutes=90)).isoformat(),
            listed_at='2024-01-01T00:00:00Z',style='AMERICAN',settlement='PHYSICAL',currency='USD',
            quote_multiplier=100,deliverable_shares=100,deliverable_cash=0,exercise_cash=strike*100,
            tick_size=.01,revision='synthetic-only',evidence_hash='synthetic_test_contract_terms'))
        cs.append(c);rows.append(dict(contract_id=c.contract_id,contract_version=c.version_hash,exchange_timestamp=stamp,
            available_at=(close+timedelta(seconds=2)).isoformat(),received_at=(close+timedelta(seconds=4)).isoformat(),
            bid=1,ask=1.1,bid_size=10,ask_size=10,last=1.05,last_timestamp=stamp,volume=100,open_interest=200,
            open_interest_available_at=stamp,underlying_price=100,underlying_timestamp=stamp,source='synthetic_hedge_options_v1'))
    meta=dict(schema_version=1,source='synthetic_hedge_options_v1',data_type='synthetic',
              license_terms='local synthetic test only',unit_evidence='fictional standard units',
              available_time_basis='frozen synthetic timestamps')
    snapshot=OptionDataStore(runtime/'options/chains').save(cs,pd.DataFrame(rows),meta)['snapshot_id']
    spec=json.loads((Path(__file__).resolve().parents[1]/'templates/demo-hedge-spec.json').read_text())
    spec.update(scope=['SPY','IEF'],benchmark='GLD',tools=['protective_put','collar','proxy_put'],
        funding='sell_scope',funding_symbol='IEF',mode='share_protection',target_beta=None,protection_fraction=1,
        min_days_to_expiry=30,max_days_to_expiry=60,exit_days_before_expiry=7,residual_beta_tolerance=.01)
    params=dict(target_dte=45,minimum_dte=30,maximum_dte=60,put_moneyness=.95,call_moneyness=1.05,
        exit_days_before_expiry=7,max_age_seconds=3600,max_underlying_skew_seconds=60,max_spread_fraction=.25,
        max_leg_skew_seconds=10,max_underlying_price_fraction=.01)
    limits=dict(adverse_slippage_fraction=0,early_assignment_cash_reserve=0,max_greek_age_seconds=3600,
        max_mark_skew_seconds=3600,proxy_exit_policy='sell_before_expiry',failed_exit_policy='block_and_require_verified_resolution')
    cov=dict(schema_version=1,as_of=risk['as_of'],knowledge_cutoff=now_utc(),ledger_seq=risk['ledger_seq'],ledger_view=risk['ledger_view'],
        security_ids={'SPY':'synthetic-SPY','IEF':'synthetic-IEF'},allocations=[],inflight_plan_ids=[])
    option=dict(snapshot_id=snapshot,selection_request=dict(template_id='protective_put',underlying='SPY',decision_at=risk['as_of'],parameters=params),
        coverage_request=cov,greeks=[],limits=limits,funding_quote=dict(symbol='IEF',execution_price=200,market_price=200,
        beta=1.5,trade_unit=1,product_type='etf',product_evidence='synthetic research funding declaration'))
    base=dict(exposure_id=old['exposure_id'],spec=spec,method='protective_put',option=option)
    before=(book.sequence('sample'),book.connection.execute('SELECT count(*) FROM tasks').fetchone()[0]);book.close()
    cases=[('put',base),('repeat',base),('collar',dict(base,method='collar',
        option=dict(option,selection_request=dict(option['selection_request'],template_id='collar'))))]
    greek=dict(contract_version=cs[0].version_hash,unit='per_share',value=-.5,signed_contracts=1,
        source='synthetic_reference',data_type='synthetic',as_of=stamp,available_at=rows[0]['available_at'],
        received_at=rows[0]['received_at'],model_inputs={})
    proxy=dict(base,method='proxy_put',spec=dict(spec,mode='beta_target',target_beta=.8,protection_fraction=None),
               option=dict(option,greeks=[greek]))
    cases.extend([('proxy',proxy),('missing_greek',dict(proxy,option=dict(proxy['option'],greeks=[])))])
    cases.append(('put_beta',dict(base,spec=dict(spec,mode='beta_target',target_beta=1.075,protection_fraction=None),
        option=dict(option,greeks=[greek]))))
    call_greek=dict(greek,contract_version=cs[1].version_hash,value=.5,signed_contracts=-1)
    cases.append(('collar_beta',dict(base,method='collar',
        spec=dict(spec,mode='beta_target',target_beta=.99,protection_fraction=None),
        option=dict(option,greeks=[greek,call_greek],selection_request=dict(option['selection_request'],template_id='collar')))))
    checks=[];fingerprint=source_fingerprint();results={}
    for name,body in cases:
        file=root/(name+'.json');file.write_text(json.dumps(body))
        command=[sys.executable,'-m','personal_quant.cli','--config','demo.toml','hedge-preview','--account-id','sample','--file',file.name]
        result=subprocess.run(command,cwd=root,capture_output=True,text=True,env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src')))
        (root/(name+'.stdout')).write_text(result.stdout);(root/(name+'.stderr')).write_text(result.stderr)
        assert result.returncode==0,result.stderr
        value=json.loads(result.stdout);results[name]=value;assert not value['executable']
        if name=='missing_greek':assert value['status']=='NO_FEASIBLE_HEDGE' and 'MODEL_INPUT_REQUIRED' in value['checks']
        else:
            assert value['status']=='SELECTED_FOR_RESEARCH'
            assert value['incremental_packages']==('4' if name=='proxy' else '1')
            assert abs(float(value['E_post'])-({'collar':29986,'collar_beta':29986,'proxy':29972}.get(name,29993)))<1e-6
            if name in {'put_beta','collar_beta'}:
                assert abs(float(value['B_post'])-({'put_beta':32200,'collar_beta':29700}[name]))<1e-6
        checks.append(dict(case=name,command=command,exit_code=0,status=value['status']))
    assert results['put']['preview_hash']==results['repeat']['preview_hash']
    book=Ledger(runtime/'account.sqlite','demo')
    assert before==(book.sequence('sample'),book.connection.execute('SELECT count(*) FROM tasks').fetchone()[0]);book.close()
    assert source_fingerprint()==fingerprint
    (root/'verification.json').write_text(json.dumps(dict(status='PASSED',checks=checks,source_fingerprint=fingerprint,
        data_type='synthetic_restated_account_research',executable=False,account_unchanged=True),ensure_ascii=False,indent=2))
    print(json.dumps(dict(status='PASSED',checks=len(checks),verification=str(root/'verification.json'))))

if __name__=='__main__':main()
