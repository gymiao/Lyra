"""Freeze multi-month selections and a model execution path into an options run."""
import json
from pathlib import Path
import shutil
import tempfile
import pandas as pd
from ..common import QuantError,decimal as D,digest,write_json
from ..data.store import DataStore
from ..options.data import OptionDataStore
from ..options.catalog import MONTHLY_RESEARCH
from ..options.monthly import freeze_monthly
from ..execution.daily import daily_lock
from ..locks import publication_lock,publish_directory
from ..strategies.archive import source_fingerprint
from .service import read_workspace,status
from .packages import verify
from .option_setup import files,load,result


def prepare(workspace,spec):
    root,identity,config,_=read_workspace(workspace);runtime=root/config.runtime_dir
    required={'schema_version','template_id','underlying','packages','fee_per_contract','selection_parameters','plan_policy','input_bundle'}
    if (not isinstance(spec,dict) or not required<=set(spec) or set(spec)-required-{'max_cycles','retain_stock','engine_root','dotnet','cash_buffer'}
            or type(spec['schema_version']) is not int or spec['schema_version']!=1 or spec['template_id'] not in MONTHLY_RESEARCH|{'wheel'}
            or spec['underlying'] not in config.symbols or type(spec['packages']) is not int or not 1<=spec['packages']<=100
            or D(spec['fee_per_contract'])<0 or type(spec.get('max_cycles',24)) is not int or not 1<=spec.get('max_cycles',24)<=24
            or type(spec.get('retain_stock',True)) is not bool):
        raise QuantError('INVALID_OPTION_SETUP','通用配置需完整参数、输入包及明确周期/资金边界')
    wheel=spec['template_id']=='wheel'
    if wheel and (not spec.get('engine_root') or not spec.get('dotnet') or 'cash_buffer' not in spec or D(spec['cash_buffer'])<0 or spec['selection_parameters']['exit_days_before_expiry']!=0):
        raise QuantError('INVALID_WHEEL_SETUP','Wheel需显式引擎/SDK/现金缓冲及持有至到期规则')
    if identity['kind']!='options':raise QuantError('WORKSPACE_MODE_CONFLICT','期权配置需options工作区')
    package_root=Path(spec['input_bundle']).absolute();manifest=verify(package_root)
    if manifest['checks']:raise QuantError('INPUT_PACKAGE_BLOCKED','输入包仍有待核实事项')
    if not (package_root/'scenario.json').is_file():raise QuantError('MISSING_EXECUTION_PATH','需有明确冻结执行路径的场景包；链报价导入不等于完整成交路径')
    scenario=json.loads((package_root/'scenario.json').read_text())
    if config.evaluation_start<scenario['spec']['start'] or config.evaluation_end>scenario['spec']['end']:
        raise QuantError('INCOMPLETE_SIMULATION_RANGE','配置区间超出场景覆盖，不能静默截短实验')
    basis={'workspace_id':identity['workspace_id'],'spec':spec,'source_hash':source_fingerprint(),'input_bundle_id':manifest['input_bundle_id']}
    setup_id=digest(basis);parent=runtime/'simulation/setups';destination=parent/setup_id
    with daily_lock(runtime/'.simulation.lock'),publication_lock(runtime):
        if destination.exists():return result(destination,load(destination))
        if status(root)['runs']:raise QuantError('WORKSPACE_RUN_CONFLICT','已有运行，更改规则需独立实验')
        parent.mkdir(parents=True,exist_ok=True);pending=Path(tempfile.mkdtemp(prefix='.pending-',dir=parent))
        try:
            shutil.copytree(package_root,pending/'input-package')
            _,_,calendar=DataStore(pending/'input-package/data').load(manifest['roles']['signal'])
            store=OptionDataStore(pending/'input-package/chains');signals=[]
            months=[m for m in scenario['cycles'] if config.evaluation_start<=m['decision_session']<=config.evaluation_end][:spec.get('max_cycles',24)]
            if not months:raise QuantError('NO_MONTHLY_DECISIONS','配置区间内无冻结月末决策')
            path=scenario['execution_path']
            horizon=str(max(d for d in calendar.sessions if d<=pd.Timestamp(config.evaluation_end)).date()) if wheel else None
            if wheel and horizon>config.evaluation_end:raise QuantError('INCOMPLETE_WHEEL_HORIZON','场景需覆盖最后到期后的恢复交易日')
            wheel_decisions=[]
            for index,month in enumerate(months):
                template=spec['template_id']
                if wheel:
                    template='cash_secured_put'
                    if signals:
                        from ..options.monthly_replay import monthly_replay
                        from ..portfolio import Ledger
                        from ..options.wheel import decision
                        cutoff=month['decision_session']
                        identities={leg['contract']['contract_id'] for signal in signals for leg in signal['selection']['legs']}
                        known={**path,'stocks':{s:{d:p for d,p in values.items() if signals[0]['applicable_session']<=d<=cutoff} for s,values in path['stocks'].items() if s==spec['underlying']},
                            'options':{s:{d:p for d,p in values.items() if signals[0]['applicable_session']<=d<=cutoff} for s,values in path['options'].items() if s in identities}}
                        proof=monthly_replay(spec['engine_root'],spec['dotnet'],pending/'wheel-prefixes'/str(index),signals,
                            initial_cash=identity['initial_cash'],fee_per_contract=spec['fee_per_contract'],packages=[spec['packages']]*len(signals),
                            execution_path=known,wheel=True,through=cutoff,wheel_end_session=horizon)
                        book=Ledger.read_only(pending/'wheel-prefixes'/str(index)/'bridge.sqlite','demo')
                        try:phase=decision(book,'monthly-bridge',proof['ledger_bridge']['as_of'],{'underlying':spec['underlying'],'packages':spec['packages'],'cash_buffer':spec['cash_buffer']})
                        finally:book.close()
                        if phase['status']!='READY_FOR_SELECTION':raise QuantError('WHEEL_PHASE_BLOCKED','月末已有实际义务/结算或现金不足，不能凭未来价格选下一阶段')
                        template=phase['template_id'];wheel_decisions.append(phase)
                signal=freeze_monthly(store,month['snapshot_id'],{'template_id':template,'underlying':spec['underlying'],
                    'decision_at':(calendar.close(month['decision_session'])+pd.Timedelta(minutes=config.publication_delay_minutes)).isoformat(),
                    'parameters':spec['selection_parameters']},calendar,pending/'signals',scope=setup_id,publication_delay_minutes=config.publication_delay_minutes)
                if signal['status']!='FROZEN_FOR_RESEARCH':raise QuantError('OPTION_SETUP_SELECTION_BLOCKED','场景选约缺少符合期限/报价/行权价规则的组合')
                if signal['selection']['data_type']!='synthetic':raise QuantError('DEMO_ONLY','本地前缀只允许明确合成场景')
                signals.append(signal)
            if wheel:
                horizon=str(calendar.next(signals[-1]['selection']['expiry']).date())
                if horizon>config.evaluation_end:raise QuantError('INCOMPLETE_WHEEL_HORIZON','场景必须覆盖实际选约最后到期后的恢复交易日')
            path=scenario['execution_path'];start=signals[0]['applicable_session']
            market_end=horizon if wheel else min(config.evaluation_end,max(max(values) for values in path['stocks'].values()))
            world={**path,'stocks':{s:{d:p for d,p in values.items() if start<=d<=market_end} for s,values in path['stocks'].items() if s==spec['underlying']},
                   'options':{s:{d:p for d,p in values.items() if start<=d<=market_end} for s,values in path['options'].items()}}
            request={'signals':signals,'packages':[spec['packages']]*len(signals),'stock_basket':{},'execution_path':world}
            if wheel:
                request.update(wheel=True,wheel_end_session=market_end)
                write_json(pending/'wheel-decisions.json',wheel_decisions)
            stock=spec['template_id'] in {'protective_put','covered_call','collar'}
            if stock:
                if spec.get('retain_stock',True):request.update(prepare_stock=True,retain_stock=True,rolling_end_session=market_end)
                else:request.update(prepare_stock=True)
            if spec['plan_policy'] is not None:
                policy=spec['plan_policy']
                if not isinstance(policy,dict) or set(policy)!={'risk','engine_evidence_file','reconciliation_max_days','execution_window_sessions'}:
                    raise QuantError('INVALID_OPTION_SETUP','公共计划需完整风险/资格/对账窗口')
                from .option_policy import freeze_policy
                request['plan_policy']={'schema_version':1,'chain_root':str(pending/'input-package/chains'),
                    'engine_evidence_files':{s['selection']['template_id']:policy['engine_evidence_file'] for s in signals},
                    **{k:policy[k] for k in ('risk','reconciliation_max_days','execution_window_sessions')}}
                frozen=freeze_policy(request,pending,spec['fee_per_contract'])
                (pending/'plan-policy.json').unlink();shutil.rmtree(pending/'plan-chains')
                request['plan_policy']['chain_root']=str(destination.relative_to(root)/'input-package/chains')
                request['plan_policy']['engine_evidence_files']={k:str(destination.relative_to(root)/v) for k,v in frozen['engine_evidence_files'].items()}
            write_json(pending/'request.json',request);write_json(pending/'spec.json',spec)
            body={'schema_version':1,'setup_id':setup_id,'basis':basis,'data_type':'synthetic','executable':False,
                  'mode':'PUBLIC_PLANS' if spec['plan_policy'] else 'RESEARCH_SCHEDULE_ONLY','first_session':start,
                  'cycle_count':len(signals),
                  'last_market_session':market_end,'last_settlement_session':str(calendar.next(market_end).date()) if pd.Timestamp(market_end)!=calendar.sessions[-1] else 'UNKNOWN',
                  'request_hash':digest(request),'files':files(pending)}
            body['content_hash']=digest(body);write_json(pending/'setup-manifest.json',body);load(pending);publish_directory(pending,destination)
            return result(destination,body)
        except BaseException as exc:
            failed=runtime/'simulation/failed-setups'/pending.name.removeprefix('.pending-')
            failed.parent.mkdir(parents=True,exist_ok=True)
            write_json(pending/'failure.json',{'status':'FAILED','code':getattr(exc,'code','FAILED'),'reason':str(exc),'financial_events_added':0})
            pending.rename(failed)
            exc.add_note('失败配置与原生日志保留：'+str(failed))
            raise
        finally:
            if pending.exists():shutil.rmtree(pending)
