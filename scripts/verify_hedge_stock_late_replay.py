"""Actual CLI delayed stock execution with frozen clocks and future-price isolation."""
import argparse,json,os,shutil,subprocess,sys
from pathlib import Path
import pandas as pd
from personal_quant.common import decimal as D
from personal_quant.config import Config
from personal_quant.data.calendar import Calendar
from personal_quant.data.catalog import DataCatalog
from personal_quant.data.store import DataStore
from personal_quant.portfolio import Ledger
from personal_quant.hedging.archive import load
from personal_quant.hedging.groups import history
from personal_quant.hedging.allocation_store import resources
from personal_quant.strategies.archive import source_fingerprint


def main():
    p=argparse.ArgumentParser();p.add_argument('--workspace',type=Path,required=True)
    p.add_argument('--destination',type=Path,required=True);args=p.parse_args()
    root=Path(os.path.abspath(args.destination));root.mkdir(parents=True,exist_ok=False)
    shutil.copytree(args.workspace/'runtime',root/'runtime');shutil.copy2(args.workspace/'demo.toml',root/'demo.toml')
    project=Path(__file__).resolve().parents[1];fingerprint=source_fingerprint();checks=[]
    def run(name,command,expected=0):
        r=subprocess.run([sys.executable,'-m','personal_quant.cli','--config','demo.toml',*command],cwd=root,
            capture_output=True,text=True,env=dict(os.environ,PYTHONPATH=str(project/'src')))
        (root/(name+'-stdout.json')).write_text(r.stdout);(root/(name+'-stderr.log')).write_text(r.stderr)
        assert r.returncode==expected,r.stderr
        checks.append(dict(name=name,command=command,exit_code=r.returncode))
        return json.loads(r.stdout if expected==0 else r.stderr)
    assert run('upgrade-isolated',['v19-init'])['schema_version']==5
    b=Ledger(root/'runtime/demo/account.sqlite','demo')
    activated=json.loads(b.connection.execute("SELECT details FROM tasks WHERE task_id LIKE 'hedge-stock-activation:%'").fetchone()[0])
    plan_id=activated['plan_id'];old=load(b.path.parent/'hedging/exposures',activated['stage_assessment']['exposure_id'])
    assert b.environment=='demo'
    initial_sequence=b.sequence('sample');initial_equity=D(old['account']['equity'])
    expected_positions=dict(old['account']['positions']);expected_positions['IEF']=str(D(expected_positions['IEF'])-37)
    store=DataStore(b.path.parent/'data');frame,_,calendar=store.load(old['valuation_snapshot_id'])
    processing='2025-01-20T21:30:00Z';execution='2025-01-16T21:00:00Z'
    late=frame.loc[frame.session_date==calendar.sessions[-1]].copy()
    late['session_date']=pd.Timestamp('2025-01-16');late['available_at']=pd.Timestamp(processing)
    later=late.copy();later['session_date']=pd.Timestamp('2025-01-17');later['available_at']=pd.Timestamp('2025-01-17T21:30:00Z')
    for key in ('open','high','low','close','adj_close'):later.loc[later.symbol=='IEF',key]=400
    frame=pd.concat([frame,late,later],ignore_index=True)
    extra=pd.DataFrame({'close_time':[pd.Timestamp(execution),pd.Timestamp('2025-01-17T21:00:00Z')]},
        index=pd.to_datetime(['2025-01-16','2025-01-17']))
    calendar=Calendar(pd.concat([calendar.schedule,extra]),calendar.kind)
    metadata=store.save(frame,calendar);catalog=DataCatalog(b);entry=catalog.register(metadata['snapshot_id'])
    row=b.connection.execute("SELECT revision FROM data_roles WHERE role='execution'").fetchone()
    catalog.bind('execution',entry['series_id'],expected_revision=row[0] if row else 0)
    req=dict(old['request'],as_of=execution,knowledge_cutoff=processing,
        valuation_snapshot_id=metadata['snapshot_id'],return_snapshot_id=metadata['snapshot_id'],
        execution_replay=dict(plan_kind='stock',plan_id=plan_id,execution_at=execution,processing_at=processing))
    group=next(g for g in history(b,'sample') if any(s['plan_id']==plan_id for s in g['stages']));b.close()
    (root/'risk.json').write_text(json.dumps(req))
    published=run('freeze-risk',['hedge-exposure','--account-id','sample','--file','risk.json','--archive'])
    assert published['status']=='COMPLETE'
    b=Ledger(root/'runtime/demo/account.sqlite','demo');risk=load(b.path.parent/'hedging/exposures',published['exposure_id'])
    assert risk['valuation']['prices']['IEF']==200 and risk['as_of']==execution.replace('Z','+00:00')
    assert risk['knowledge_cutoff']==processing.replace('Z','+00:00')
    phase=dict(activated['request']['hedge_stage_check'],exposure_id=published['exposure_id'],
        expected_resource_hash=resources(b,'sample'),group_id=group['group_id'],expected_group_hash=group['record_hash'])
    phase['stress']=dict(phase['stress'],scenarios=[dict(s,horizon_date='2025-01-16') for s in phase['stress']['scenarios']]);b.close()
    (root/'phase.json').write_text(json.dumps(phase))
    assert run('check-stage',['hedge-stage-check','--account-id','sample','--file','phase.json'])['status']=='CHECKED'
    command=['simulate','--plan-id',plan_id,'--as-of',processing,'--hedge-stage-check','phase.json']
    assert run('missing-frozen-clock',command,2)['code']=='HEDGE_REPLAY_STATE_REQUIRED'
    filled=run('late-fill',command+['--state-as-of',execution])
    assert filled['status']=='SUCCESS' and filled['late_processing'] and filled['execution_session']=='2025-01-16'
    assert run('late-repeat',command+['--state-as-of',execution])['status']=='NO_ACTION'
    b=Ledger(root/'runtime/demo/account.sqlite','demo');state=b.snapshot('sample',execution,{**old['account']['prices'],'IEF':200})
    assert b.sequence('sample')==initial_sequence+1 and {s:D(q) for s,q in state['positions'].items()}=={s:D(q) for s,q in expected_positions.items()}
    assert D(state['receivables'])==D('7394.82') and D(state['equity'])==initial_equity-D('5.18')
    from personal_quant.hedging.stock_simulation_audit import validate_references
    validate_references(b);b.close();assert fingerprint==source_fingerprint()
    proof=dict(status='PASSED',source_fingerprint=fingerprint,checks=checks,data_type='synthetic',
        actual_user_account_writes=False,simulated_events_added=1,execution_at=execution,processing_at=processing,
        frozen_price=200,excluded_future_price=400,expected_equity=str(initial_equity-D('5.18')),expected_receivables='7394.82')
    (root/'verification.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2))
    print(json.dumps(dict(status='PASSED',checks=len(checks),verification=str(root/'verification.json'))))


if __name__=='__main__':main()
