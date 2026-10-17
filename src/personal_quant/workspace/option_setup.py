"""Prepare immutable synthetic monthly requests through the public selector."""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import pandas as pd
from ..common import QuantError,decimal as D,digest,write_json
from ..data.calendar import Calendar
from ..data.option_fixture import create as create_fixture,VERSION
from ..execution.daily import daily_lock
from ..locks import publication_lock,publish_directory
from ..options.catalog import MONTHLY_RESEARCH
from ..options.monthly import freeze_monthly
from ..options.plans import RISK_FIELDS
from ..options.qualification import assess_engine
from ..strategies.archive import source_fingerprint
from .service import read_workspace,status


def files(root):
    result={}
    for file in sorted(root.rglob('*')):
        if file.is_symlink():raise QuantError('UNSAFE_OPTION_SETUP','配置包不接受链接')
        if file.is_file() and file!=root/'setup-manifest.json':
            with file.open('rb') as stream:result[file.relative_to(root).as_posix()]=hashlib.file_digest(stream,'sha256').hexdigest()
    return result


def load(directory):
    root=Path(directory)
    try:
        body=json.loads((root/'setup-manifest.json').read_text())
        if (body.get('schema_version')!=1 or body.get('data_type')!='synthetic' or body.get('executable') is not False
                or digest({k:v for k,v in body.items() if k!='content_hash'})!=body['content_hash'] or files(root)!=body['files']):
            raise QuantError('CORRUPT_OPTION_SETUP','已冻结的期权配置或文件改变')
        request=json.loads((root/'request.json').read_text())
        if digest(body['basis'])!=body['setup_id'] or digest(request)!=body['request_hash']:
            raise QuantError('CORRUPT_OPTION_SETUP','配置身份或冻结请求哈希不一致')
        return body
    except QuantError:raise
    except (OSError,ValueError,KeyError,TypeError) as exc:raise QuantError('CORRUPT_OPTION_SETUP','期权配置不完整：'+str(exc)) from exc


def prepare(workspace,spec):
    if isinstance(spec,dict) and 'input_bundle' in spec:
        from .scenario_setup import prepare as prepare_scenario
        return prepare_scenario(workspace,spec)
    root,identity,config,_=read_workspace(workspace);runtime=root/config.runtime_dir
    required={'schema_version','template_id','underlying','packages','fee_per_contract','selection_parameters','plan_policy'}
    if (not isinstance(spec,dict) or set(spec)!=required or type(spec['schema_version']) is not int or spec['schema_version']!=1
            or not isinstance(spec['template_id'],str) or spec['template_id'] not in MONTHLY_RESEARCH or spec['underlying'] not in config.symbols
            or type(spec['packages']) is not int or not 1<=spec['packages']<=100 or D(spec['fee_per_contract'])<0):
        raise QuantError('INVALID_OPTION_SETUP','配置需schema1、支持模板/配置内标的、1至100包、非负费用及完整选约参数')
    if identity['kind']!='options':raise QuantError('WORKSPACE_MODE_CONFLICT','期权配置只能用于独立options合成工作区')
    policy=spec['plan_policy'];evidence_hash=None
    if policy is not None:
        if (not isinstance(policy,dict) or set(policy)!={'risk','engine_evidence_file','reconciliation_max_days','execution_window_sessions'}
                or not isinstance(policy['risk'],dict) or set(policy['risk'])!=RISK_FIELDS):
            raise QuantError('INVALID_OPTION_SETUP','公共计划需全部风险参数、资格文件及对账/执行窗口')
        if type(policy['execution_window_sessions']) is not int or policy['execution_window_sessions']<2:
            raise QuantError('INVALID_OPTION_EXECUTION_WINDOW','两周期/股票准备需至少2个交易日执行窗口；不更改原信号')
        if D(policy['risk']['maximum_contracts'])<spec['packages']:raise QuantError('INVALID_OPTION_RISK','包数超过明确的张数上限')
        evidence=assess_engine(policy['engine_evidence_file'],spec['template_id'])
        if evidence['status']!='PASSED':raise QuantError('ENGINE_LIFECYCLE_UNQUALIFIED','公共计划需要该模板当前源码生命周期资格')
        evidence_hash=evidence['evidence_hash']
    basis={'workspace_id':identity['workspace_id'],'spec':spec,'source_hash':source_fingerprint(),
        'fixture_version':VERSION,'engine_evidence_hash':evidence_hash}
    setup_id=digest(basis);parent=runtime/'simulation/setups';destination=parent/setup_id
    with daily_lock(runtime/'.simulation.lock'),publication_lock(runtime):
        if destination.exists():return result(destination,load(destination))
        if status(root)['runs']:raise QuantError('WORKSPACE_RUN_CONFLICT','已有冻结运行，修改配置请复制独立工作区；不重置原账户')
        parent.mkdir(parents=True,exist_ok=True);pending=Path(tempfile.mkdtemp(prefix='.pending-',dir=parent))
        try:
            calendar=Calendar.market('2024-10-01','2025-02-10');store,months,quotes=create_fixture(pending/'chains',spec['underlying'],calendar)
            signals=[]
            for month in months:
                request={'template_id':spec['template_id'],'underlying':spec['underlying'],
                    'decision_at':(calendar.close(month['session'])+pd.Timedelta(minutes=config.publication_delay_minutes)).isoformat(),
                    'parameters':spec['selection_parameters']}
                signal=freeze_monthly(store,month['snapshot_id'],request,calendar,pending/'signals',
                    scope=setup_id,publication_delay_minutes=config.publication_delay_minutes)
                if signal['status']!='FROZEN_FOR_RESEARCH':
                    rejected=signal.get('selection',{}).get('rejected',[])
                    issues=sorted({code for row in rejected for code in row.get('issues',[])})
                    raise QuantError('OPTION_SETUP_SELECTION_BLOCKED','选约未通过：'+str(signal.get('reason','NO_ACTION'))
                        +'；检查 '+(', '.join(issues) if issues else '期限/行权价/腿间同步参数'))
                signals.append(signal)
            cutoff=pd.Timestamp(signals[-1]['selection']['expiry'])-pd.Timedelta(days=int(D(spec['selection_parameters']['exit_days_before_expiry'])))
            exit_day=max(day for day in calendar.sessions if day<=cutoff)
            stock=spec['template_id'] in {'protective_put','covered_call','collar'}
            end=calendar.next(exit_day) if stock else exit_day
            days=calendar.sessions[(calendar.sessions>=signals[0]['applicable_session'])&(calendar.sessions<=end)]
            world={'schema_version':1,'data_type':'synthetic','stocks':{spec['underlying']:{str(day.date()):'100' for day in days}},
                'options':{name:{str(day.date()):{'bid':quote['bid'],'ask':quote['ask']} for day in days
                    if quote['known_session']<=str(day.date())<=quote['expiry']} for name,quote in quotes.items()}}
            request={'signals':signals,'packages':[spec['packages']]*2,'stock_basket':{},'execution_path':world}
            if stock:request.update(prepare_stock=True,retain_stock=True,rolling_end_session=str(end.date()))
            if policy is not None:
                from .option_policy import freeze_policy
                request['plan_policy']={'schema_version':1,'chain_root':str(pending/'chains'),
                    'engine_evidence_files':{spec['template_id']:policy['engine_evidence_file']},
                    **{key:policy[key] for key in ['risk','reconciliation_max_days','execution_window_sessions']}}
                frozen=freeze_policy(request,pending,spec['fee_per_contract'])
                (pending/'plan-policy.json').unlink();shutil.rmtree(pending/'plan-chains')
                request['plan_policy']['chain_root']=str(destination.relative_to(root)/'chains')
                request['plan_policy']['engine_evidence_files']={key:str(destination.relative_to(root)/value) for key,value in frozen['engine_evidence_files'].items()}
            write_json(pending/'request.json',request);write_json(pending/'spec.json',spec)
            body={'schema_version':1,'setup_id':setup_id,'basis':basis,'data_type':'synthetic','executable':False,
                'mode':'PUBLIC_PLANS' if policy is not None else 'RESEARCH_SCHEDULE_ONLY','first_session':str(days[0].date()),
                'last_market_session':str(end.date()),'last_settlement_session':str(calendar.next(end).date()),
                'request_hash':digest(request),'files':files(pending)}
            body['content_hash']=digest(body);write_json(pending/'setup-manifest.json',body)
            load(pending);publish_directory(pending,destination)
            return result(destination,body)
        finally:
            if pending.exists():shutil.rmtree(pending)


def result(directory,body):
    return {'status':'PREPARED','setup_id':body['setup_id'],'setup_directory':str(directory),
        'request_file':str(directory/'request.json'),'mode':body['mode'],'data_type':'synthetic','executable':False,
        'first_session':body['first_session'],'last_market_session':body['last_market_session'],
        'last_settlement_session':body['last_settlement_session'],'cycle_count':body.get('cycle_count',2),
        'meaning':'合成历史配置，仅冻结输入；未入金/成交/授予真实权限'}
