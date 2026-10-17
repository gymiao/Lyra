"""Allowlisted durable operator tasks, isolated in the workspace worker cwd."""
import json
from pathlib import Path
from ..common import QuantError,digest,write_json
from .service import read_workspace

FIELDS={'backup':{'destination'},'verify':{'source'},'restore':{'source','destination'},
        'compare':{'members','destination'},'export':{'run_id','destination'},
        'scenario':{'spec','destination'},'verify-input':{'source'},'tool-verify':{'engine_root','dotnet'},'research-freeze':{'spec','destination'},'research-run':{'source','engine_root','dotnet'},'csv-import':{'source','mapping','destination','expected_preview','calendar_file','calendar_kind'},'capabilities':{'template_id','engine_evidence','input_bundle'}}


def normalize(request):
    if not isinstance(request,dict) or request.get('operation') not in FIELDS or set(request)!={'operation'}|FIELDS[request['operation']]:
        raise QuantError('INVALID_OPERATION','维护请求需已实现操作和全部显式参数')
    for key in {'destination','source','engine_root','dotnet'} & set(request):
        if not isinstance(request[key],str) or not Path(request[key]).is_absolute():
            raise QuantError('INVALID_OPERATION_PATH','操作路径需绝对路径')
    return request


def submit(directory,request,*,request_id,max_seconds=None):
    from .jobs import launch
    root,_,config,_=read_workspace(directory);request=normalize(request)
    file=root/config.runtime_dir/'simulation/operation-requests'/(digest(request)+'.json')
    write_json(file,request)
    return launch(root,'operation',input_file=file,request_id=request_id,max_seconds=max_seconds)


def execute(directory,request):
    root,identity,config,path=read_workspace(directory);request=normalize(request);op=request['operation']
    if Path.cwd().resolve()!=root.resolve():raise QuantError('WORKSPACE_CWD_REQUIRED','维护在独立工作区进程执行，不切换共享界面cwd')
    if op=='backup':
        from ..portfolio.backup import create_bundle
        result=create_bundle(Path(config.runtime_dir),path,Path(request['destination']))
    elif op in {'verify','restore'}:
        from .maintenance import verify
        result=verify(root,request['source'],destination=request.get('destination'))
    elif op=='compare':
        from .experiments import compare
        result=compare(request['members']);destination=Path(request['destination'])
        if destination.exists():raise QuantError('NONEMPTY_DESTINATION','比较输出需新文件')
        write_json(destination,result)
    elif op=='export':
        from .experiment_index import export
        result=export(root,request['run_id'],request['destination'])
    elif op=='scenario':
        from .scenarios import generate
        result=generate(request['spec'],request['destination'])
    elif op=='capabilities':
        from ..options.capabilities import describe
        result=describe(request['template_id'],request['engine_evidence'],request['input_bundle'])
    elif op=='csv-import':
        from .csv_package import commit
        result=commit(request['source'],request['mapping'],request['destination'],request['expected_preview'],calendar_file=request['calendar_file'],calendar_kind=request['calendar_kind'])
    elif op=='research-freeze':
        from .research_protocol import freeze
        result=freeze(request['destination'],request['spec'])
    elif op=='research-run':
        from .research_protocol import run
        result=run(request['source'],request['engine_root'],request['dotnet'])
    elif op=='verify-input':
        from .packages import verify
        result=verify(request['source'])
    else:
        from .portable_tools import fingerprint as tool_identity
        result=tool_identity(request['engine_root'],request['dotnet'])
    return {'status':'SUCCEEDED','business_status':result.get('status',result.get('check_status','COMPLETED')),'operation':op,'result':result,'request_hash':digest(request),
            'financial_events_added':0,'meaning':'维护回执；结果不赋予真实来源、账户或自动交易资格'}
