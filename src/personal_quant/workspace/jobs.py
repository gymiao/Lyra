"""Subprocess jobs with durable receipts; no engine work during UI rerenders."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import hashlib
from uuid import uuid4
from ..common import QuantError,now_utc,write_json,digest,utc
from ..execution.daily import daily_lock
from ..research.service import process_identity,worker_alive
from .service import read_workspace
from ..processes import python_command,python_environment



def submission_lock(runtime,timeout=30):
    """Wait for the short registration section; never release another owner."""
    from contextlib import contextmanager,ExitStack
    @contextmanager
    def acquire():
        end=time.monotonic()+timeout
        with ExitStack() as stack:
            while True:
                try:
                    stack.enter_context(daily_lock(runtime/'.simulation-submit.lock'));break
                except QuantError as exc:
                    if exc.code!='DAILY_ALREADY_RUNNING':raise
                    if time.monotonic()>=end:raise QuantError('SIMULATION_SUBMISSION_BUSY','任务登记仍由另一进程持有，未抢占或释放锁') from exc
                    time.sleep(.02)
            yield
    return acquire()

def launch(directory,action,run_id=None,through=None,*,input_file=None,engine_root=None,dotnet=None,fee_per_contract=None,max_sessions=None,max_seconds=None,min_free_bytes=None,request_id=None):
    if action not in {'prepare','start','step','resume','batch','operation'}:raise QuantError('INVALID_SIMULATION_JOB','未知后台模拟任务')
    submitted=now_utc()
    root,body,config,_=read_workspace(directory)
    if action in {'step','resume','batch'} and (not run_id or input_file is not None or fee_per_contract is not None):
        raise QuantError('INVALID_SIMULATION_JOB','推进需要run-id，不覆盖冻结请求/费用')
    if action in {'prepare','start'} and (run_id or through):raise QuantError('INVALID_SIMULATION_JOB','配置/启动不接受run-id或through')
    budget={k:v for k,v in dict(max_sessions=max_sessions,max_seconds=max_seconds,min_free_bytes=min_free_bytes).items() if v is not None}
    if action!='batch':
        if max_sessions is not None or min_free_bytes is not None:raise QuantError('INVALID_BATCH_ARGUMENTS','交易日/容量预算只用于batch')
        from .task_budget import seconds
        seconds(max_seconds)
    if action=='batch':
        from .batch import limits
        limits(**budget)
        if not through:raise QuantError('INVALID_BATCH_ARGUMENTS','批次需要明确推进终点')
    if action=='prepare' and (body['kind']!='options' or not input_file or any(v is not None for v in (engine_root,dotnet,fee_per_contract))):
        raise QuantError('INVALID_OPTION_SETUP','后台prepare只接受options配置文件')
    if action=='start' and body['kind']=='options' and not all(v is not None and v!='' for v in (input_file,engine_root,dotnet,fee_per_contract)):
        raise QuantError('OPTION_INPUT_REQUIRED','期权启动需要配置请求、引擎、SDK与明确费用')
    if action=='operation' and (not input_file or run_id or through or any(v is not None for v in (engine_root,dotnet,fee_per_contract))):
        raise QuantError('INVALID_OPERATION','维护需独立请求文件，不混用模拟参数')
    if action!='operation' and body['kind']=='etf' and any(v is not None for v in (input_file,engine_root,dotnet,fee_per_contract)):
        raise QuantError('INVALID_ETF_ARGUMENTS','ETF后台任务不接受期权参数')
    if engine_root is not None or dotnet is not None:
        if body['kind']!='options':raise QuantError('INVALID_ETF_ARGUMENTS','ETF后台任务不接受期权引擎路径')
        if not engine_root or not dotnet:raise QuantError('SIMULATION_TOOL_PATHS_REQUIRED','迁移需同时提供LEAN与dotnet路径')
    runtime=root/config.runtime_dir
    if request_id is not None and (not isinstance(request_id,str) or not request_id.strip() or len(request_id)>200):
        raise QuantError('INVALID_REQUEST_ID','任务请求ID需1至200字')
    request_id=request_id or uuid4().hex
    payload={'action':action,'run_id':run_id,'through':through,'input_file':str(Path(input_file).absolute()) if input_file is not None else None,
             'input_sha256':hashlib.sha256(Path(input_file).read_bytes()).hexdigest() if input_file is not None and Path(input_file).is_file() else None,
             'fee_per_contract':fee_per_contract,'engine_root':str(engine_root) if engine_root else None,'dotnet':str(dotnet) if dotnet else None,'budget':budget}
    with submission_lock(runtime):
        prior=list_jobs(root,limit=None)
        for old in prior:
            if old.get('request_id')==request_id:
                if old.get('request_hash')!=digest(payload):raise QuantError('SIMULATION_REQUEST_CONFLICT','相同请求ID对应不同参数')
                return {**old,'repeated':True}
        if any(old['status'] in {'RUNNING','SUBMITTED','INTERRUPTED','UNVERIFIED'} for old in prior):
            raise QuantError('SIMULATION_ALREADY_RUNNING','有在途或未核实任务，请先查看进度或核对恢复')
        identity=uuid4().hex;folder=runtime/'simulation/jobs'/identity;folder.mkdir(parents=True)
        token=uuid4().hex
        frozen_file=None
        if payload['input_sha256'] is not None:
            content=Path(input_file).read_bytes()
            if hashlib.sha256(content).hexdigest()!=payload['input_sha256']:
                raise QuantError('SIMULATION_INPUT_CHANGED','提交前请求文件已变化')
            frozen_file=folder/'request-input.json'
            with frozen_file.open('xb') as stream:stream.write(content)
        command=[*python_command('personal_quant.workspace.worker'),action,'--requested-at',now_utc(),'--result-file',str(folder/'result.json'),
                 '--job-id',identity,'--job-token',token]
        if run_id:command.extend(['--run-id',run_id])
        if through:command.extend(['--through',through])
        if input_file is not None:command.extend(['--file',str(frozen_file or Path(input_file).absolute())])
        if fee_per_contract is not None:command.extend(['--fee-per-contract',str(fee_per_contract)])
        for key,value in budget.items():command.extend(['--'+key.replace('_','-'),str(value)])
        tool_paths={}
        if engine_root is not None:
            tool_paths={'engine_root':str(Path(engine_root).absolute()),'dotnet':str(Path(dotnet).absolute())}
            for key,value in tool_paths.items():command.extend(['--'+key.replace('_','-'),value])
        from .task_budget import deadline
        due=deadline(submitted,max_seconds if max_seconds is not None else 3600)
        if action=='batch':
            from datetime import timedelta
            due=(utc(due)+timedelta(seconds=5)).isoformat()
        record={'schema_version':2,'job_id':identity,'request_id':request_id,'request_hash':digest(payload),'token_hash':digest(token),
            'job_status':'SUBMITTED','action':action,'run_id':run_id,'through':through,'started_at':submitted,'queued_at':submitted,'deadline_at':due,'grace_seconds':5 if action=='batch' else 0,
            'owner':None,'tool_paths':tool_paths,'batch_limits':budget,
            'input_file':str(Path(input_file).absolute()) if input_file is not None else None,'fee_per_contract':fee_per_contract,
            'worker_input_file':str(frozen_file) if frozen_file else None,'input_sha256':payload['input_sha256']}
        # Intent exists before the process; the child waits for this owner handshake.
        write_json(folder/'job.json',record)
        child=None
        try:
            with (folder/'worker.log').open('w') as log:
                child=subprocess.Popen(command,cwd=root,env=python_environment(),stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            record.update(owner=process_identity(child.pid),job_status='RUNNING')
            write_json(folder/'job.json',record)
            try:
                from .job_index import write_index
                write_index(root,runtime,body['workspace_id'])
            except OSError:record['index_status']='REBUILD_REQUIRED'
        except BaseException:
            if child is not None:
                from .batch import _stop
                _stop(child)
            try:write_json(folder/'result.json',{'status':'FAILED','code':'WORKER_START_FAILED','phase':'SUBMISSION'})
            except OSError:pass # The durable intent remains visible and blocks a duplicate.
            raise
    return record


def list_jobs(directory,*,limit=100,offset=0):
    if (limit is not None and (type(limit) is not int or not 1<=limit<=1000)) or type(offset) is not int or offset<0:
        raise QuantError('INVALID_JOB_QUERY','任务分页需正整数limit和非负offset')
    root,body,config,_=read_workspace(directory);rows=[]
    from .job_index import paths as indexed_paths
    paths,index_status=indexed_paths(root,root/config.runtime_dir,body['workspace_id'])
    paths=paths[offset:] if limit is None else paths[offset:offset+limit]
    child_records=[]
    for file in (root/config.runtime_dir/'simulation/jobs').glob('batch-child-*/owner.json'):
        try:
            if file.is_symlink():continue
            record=json.loads(file.read_text())
            if isinstance(record,dict):child_records.append(record)
        except (OSError,ValueError,TypeError):continue
    for path in paths:
        try:
            if path.is_symlink():raise ValueError('linked task')
            item=json.loads(path.read_text());result=path.parent/'result.json'
            if not isinstance(item,dict) or item['job_id']!=path.parent.name or 'owner' not in item:raise ValueError('identity')
            if item['owner'] is not None and not isinstance(item['owner'],dict):raise ValueError('owner shape')
            if item.get('started_at') is not None:utc(item['started_at'])
            if item.get('deadline_at') is not None:utc(item['deadline_at'])
            if result.exists():
                if result.is_symlink():raise ValueError('linked result')
                item['result']=json.loads(result.read_text())
                if not isinstance(item['result'],dict) or not isinstance(item['result'].get('status'),str):raise ValueError('result')
                item['run_status']=item['result'].get('business_status',item['result']['status']);item['status']=item['result']['status']
                if item['status'] in {'PREPARED','CREATED','PAUSED','COMPLETED','SUCCEEDED'}:item['status']='SUCCESS'
                item['job_status']='SUCCEEDED' if item['result'].get('transport_status')=='SUCCEEDED' or item['status']=='SUCCESS' else 'FAILED'
            else:
                alive=worker_alive(item['owner'])
                pending=item.get('job_status')=='SUBMITTED' and item['owner'] is None and (utc(now_utc())-utc(item['started_at'])).total_seconds()<30
                item['status']='RUNNING' if alive else 'SUBMITTED' if pending else 'INTERRUPTED'
                if alive:item['owner_verified_at']=now_utc()
                item['job_status']=item['status']
        except (OSError,ValueError,KeyError,TypeError,QuantError):
            item={'job_id':path.parent.name,'status':'UNVERIFIED','job_status':'UNKNOWN','code':'CORRUPT_JOB_METADATA',
                  'meaning':'原始文件保留；核实在途任务和账本后显式恢复，不自动重新执行'}
        review=path.parent/'review.json'
        if review.is_file() and not review.is_symlink() and not worker_alive(item.get('owner')):
            try:
                checked=json.loads(review.read_text())
                if (checked['files_hash']==_receipt_hash(path.parent)
                        and digest({k:v for k,v in checked.items() if k!='review_hash'})==checked['review_hash']):
                    item.update(status='REVIEWED',job_status='REVIEWED',review=checked)
            except (OSError,ValueError,KeyError,TypeError):pass
        children=[child['owner'] for child in child_records if item.get('owner') and child.get('parent_owner')==item['owner'] and isinstance(child.get('owner'),dict) and worker_alive(child.get('owner'))]
        if children:
            item['active_descendants']=children
            if item['status'] not in {'RUNNING','SUBMITTED'}:item.update(status='INTERRUPTED',job_status='INTERRUPTED')
        phase=path.parent/'phase.json'
        try:
            stage=json.loads(phase.read_text()) if phase.is_file() and not phase.is_symlink() else {}
            if isinstance(stage,dict):
                item['phase']=stage.get('phase') if isinstance(stage.get('phase'),str) else 'UNVERIFIED'
                item['stage_events']=stage.get('events',[]) if isinstance(stage.get('events',[]),list) else []
        except (OSError,ValueError):item['phase']='UNVERIFIED'
        item['task_index']=index_status
        rows.append(item)
        item['files_hash']=_receipt_hash(path.parent)
    return rows


def claim(directory,job_id,token):
    """No financial work starts until the parent has persisted our identity."""
    root,_,config,_=read_workspace(directory)
    path=root/config.runtime_dir/'simulation/jobs'/job_id/'job.json'
    if len(job_id)!=32 or any(c not in '0123456789abcdef' for c in job_id):raise QuantError('INVALID_JOB_ID','任务ID无效')
    deadline=time.monotonic()+30
    while True:
        try:body=json.loads(path.read_text())
        except (OSError,ValueError) as exc:raise QuantError('CORRUPT_JOB_METADATA','任务提交记录缺失或损坏') from exc
        if not isinstance(body,dict):raise QuantError('CORRUPT_JOB_METADATA','任务提交记录需为对象')
        if body.get('token_hash')!=digest(token):raise QuantError('INVALID_JOB_TOKEN','任务认领令牌不一致')
        if body.get('job_status')=='RUNNING' and body.get('owner')==process_identity():
            frozen=body.get('worker_input_file')
            if frozen and (Path(frozen).is_symlink() or hashlib.sha256(Path(frozen).read_bytes()).hexdigest()!=body['input_sha256']):
                raise QuantError('SIMULATION_INPUT_CHANGED','提交后的冻结请求已变化')
            if body.get('action')=='start' and body.get('input_file'):
                origin=Path(body['input_file'])
                if (origin.parent/'setup-manifest.json').exists():
                    from .option_setup import load
                    from ..strategies.archive import source_fingerprint
                    setup=load(origin.parent)
                    if (setup['basis']['source_hash']!=source_fingerprint() or setup['basis']['workspace_id']!=read_workspace(root)[1]['workspace_id']
                            or hashlib.sha256(origin.read_bytes()).hexdigest()!=body['input_sha256']):
                        raise QuantError('SIMULATION_SOURCE_CHANGED','原冻结配置或源码已变化，不能绕过配置校验')
                    from ..common import decimal as D
                    if D(body['fee_per_contract'])!=D(setup['basis']['spec']['fee_per_contract']):raise QuantError('OPTION_SETUP_FEE_CHANGED','启动费用与冻结配置不同')
            return body
        if time.monotonic()>=deadline:raise QuantError('WORKER_NOT_CLAIMED','提交者未完成任务登记；没有执行财务操作')
        time.sleep(.02)


def _receipt_hash(folder):
    return digest({name:'SYMLINK' if (folder/name).is_symlink() else hashlib.sha256((folder/name).read_bytes()).hexdigest() if (folder/name).is_file() else None
                   for name in ('job.json','result.json')})


def review(directory,job_id,request):
    """Explicit local review closes submission uncertainty, never cancels money facts."""
    root,_,config,_=read_workspace(directory);runtime=root/config.runtime_dir
    if (not isinstance(job_id,str) or not job_id or Path(job_id).name!=job_id or job_id in {'.','..'}
            or not isinstance(request,dict) or set(request)!={'files_hash','reason','confirm_no_inflight'}
            or request['confirm_no_inflight'] is not True or not isinstance(request['reason'],str) or not request['reason'].strip()):
        raise QuantError('INVALID_JOB_REVIEW','需要确切任务ID、文件指纹、核对原因和明确无在途确认')
    folder=runtime/'simulation/jobs'/job_id
    with submission_lock(runtime):
        if folder.is_symlink() or any((folder/n).is_symlink() for n in ('job.json','result.json','review.json')):
            raise QuantError('UNSAFE_JOB_PATH','任务核对不接受链接')
        item=next((row for row in list_jobs(root,limit=None) if row['job_id']==job_id),None)
        if item and item.get('active_descendants'):raise QuantError('JOB_CHILD_RUNNING','原任务的子进程仍运行，不能核销或重新执行')
        if item is None or item['status'] in {'RUNNING','SUBMITTED'}:raise QuantError('JOB_STILL_RUNNING','任务不存在或仍在执行，不能核销')
        if _receipt_hash(folder)!=request['files_hash']:raise QuantError('JOB_REVIEW_CHANGED','核对期间任务文件已变化')
        if item.get('schema_version')==2 and item.get('owner') is None and (utc(now_utc())-utc(item['started_at'])).total_seconds()<30:
            raise QuantError('JOB_HANDSHAKE_PENDING','先等待启动握手期限结束，不能核销可能仍在认领的任务')
        body={'schema_version':1,'job_id':job_id,'files_hash':request['files_hash'],'reason':request['reason'],
              'reviewed_at':now_utc(),'financial_events_added':0,'meaning':'只核对本地任务提交，不释放计划资源或撤销实际事实'}
        body['review_hash']=digest(body);write_json(folder/'review.json',body)
        return body


def inventory(directory):
    root,_,config,_=read_workspace(directory);runtime=root/config.runtime_dir
    rows=[]
    for folder in sorted((runtime/'simulation/jobs').iterdir()) if (runtime/'simulation/jobs').is_dir() else []:
        if folder.is_symlink():rows.append({'directory':folder.name,'status':'UNVERIFIED_LINK','deletable':False});continue
        if not folder.is_dir():continue
        if (folder/'job.json').is_file():kind='REGISTERED_TASK'
        elif folder.name.startswith('batch-child-'):kind='BATCH_CHILD_EVIDENCE'
        else:kind='ORPHAN_REQUIRES_REVIEW'
        rows.append({'directory':folder.name,'status':kind,'deletable':False,
            'meaning':'保留原始日志/凭据；可能被批次、运行或备份引用，不自动删除'})
    return {'status':'PREVIEW_ONLY','records':rows,'read_only':True,'financial_events_added':0}

def retry(directory,job_id,*,files_hash,request_id):
    """Explicit new attempt using the original checked request; never guesses undo."""
    row=next((r for r in list_jobs(directory,limit=None) if r['job_id']==job_id),None)
    if row is None or row['status'] not in {'FAILED','SUCCESS'} or worker_alive(row.get('owner')):
        raise QuantError('JOB_RETRY_UNVERIFIED','只可重试已核实终态任务；未知/在途先核实')
    root,_,config,_=read_workspace(directory);folder=root/config.runtime_dir/'simulation/jobs'/job_id
    if _receipt_hash(folder)!=files_hash:raise QuantError('JOB_REVIEW_CHANGED','重试前任务凭据改变')
    file=row.get('input_file')
    if file and row.get('input_sha256') is not None:
        if not Path(file).is_file() or hashlib.sha256(Path(file).read_bytes()).hexdigest()!=row['input_sha256']:
            raise QuantError('SIMULATION_INPUT_CHANGED','原请求文件改变，需另行预检/冻结，不悄悄重试新内容')
    return launch(root,row['action'],row.get('run_id'),row.get('through'),input_file=file,
        fee_per_contract=row.get('fee_per_contract'),request_id=request_id,**row.get('tool_paths',{}),**row.get('batch_limits',{}))
