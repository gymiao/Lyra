"""Read-only local replay schedule preflight; never installs cron or submits orders."""
import shutil
import shlex
import subprocess
from pathlib import Path
from ..common import QuantError,digest
from ..strategies.archive import source_fingerprint
from ..processes import python_command
from .service import read_workspace,status
from .batch import limits


def preview(directory,request):
    fields={'run_id','through','cron','max_sessions','max_seconds','min_free_bytes'}
    if not isinstance(request,dict) or set(request)!=fields or not isinstance(request['cron'],str):
        raise QuantError('INVALID_SCHEDULE','预检需运行ID、终点、cron及全部批次预算')
    pieces=request['cron'].split()
    import re
    if len(pieces)!=5 or any(not re.fullmatch(r'[0-9*,/\-]+',v) for v in pieces):raise QuantError('INVALID_CRON','只接受五段数字cron表达式')
    for value,(minimum,maximum) in zip(pieces,[(0,59),(0,23),(1,31),(1,12),(0,7)]):
        for part in value.split(','):
            chunks=part.split('/')
            if len(chunks)>2 or (len(chunks)==2 and (not chunks[1].isdigit() or not 1<=int(chunks[1])<=maximum+1)):
                raise QuantError('INVALID_CRON','cron步长须为有效正整数')
            item=chunks[0]
            if item=='*':continue
            values=item.split('-')
            if len(values)>2 or not all(x.isdigit() and minimum<=int(x)<=maximum for x in values) or (len(values)==2 and int(values[0])>int(values[1])):
                raise QuantError('INVALID_CRON','cron取值或区间无效')
    root,identity,config,_=read_workspace(directory);budget=limits(**{k:request[k] for k in ('max_sessions','max_seconds','min_free_bytes')})
    runs=status(root)['runs']
    if request['run_id'] not in {r['run_id'] for r in runs}:raise QuantError('UNKNOWN_SIMULATION','预检需已有明确运行')
    from ..portfolio import Ledger
    book=Ledger.read_only(root/config.runtime_dir/'account.sqlite','demo')
    try:
        row=book.connection.execute('SELECT source_hash FROM simulation_runs WHERE run_id=?',(request['run_id'],)).fetchone()
        if row[0]!=source_fingerprint():raise QuantError('SIMULATION_SOURCE_CHANGED','代码改变后不能安装旧运行的定时命令')
        if identity['kind']=='etf':
            from .inputs import require,verify_checkpoints
            from ..data.store import DataStore
            basis=require(book,DataStore(root/config.runtime_dir/'data'),request['run_id']);verify_checkpoints(book,request['run_id'],basis)
    finally:book.close()
    import pandas as pd
    try:
        target=pd.Timestamp(request['through'])
        if target.strftime('%Y-%m-%d')!=request['through']:raise ValueError('date')
    except (TypeError,ValueError) as exc:raise QuantError('INVALID_SIMULATION_DAY','调度终点需有效YYYY-MM-DD') from exc
    current=next(row for row in runs if row['run_id']==request['run_id'])
    if current['through_session'] and request['through']<current['through_session']:raise QuantError('SIMULATION_TIME_REVERSED','调度终点不能回退已提交事实')
    tag='LyraX-'+digest(identity['workspace_id'])[:16]
    cmd=[*python_command('personal_quant'),'simulation','batch','--workspace',str(root),'--run-id',request['run_id'],'--through',request['through']]
    for key,value in budget.items():cmd.extend(['--'+key.replace('_','-'),str(value)])
    script='cd '+shlex.quote(str(root))+' && '+shlex.join(cmd)
    cron=' '.join(pieces)+' '+script+' # '+tag
    binary=shutil.which('crontab');installation='UNAVAILABLE';registered=[]
    if binary:
        result=subprocess.run([binary,'-l'],capture_output=True,text=True,timeout=5)
        installation='PRESENT' if result.returncode==0 else 'NO_READABLE_CRONTAB'
        registered=[line for line in result.stdout.splitlines() if line.endswith('# '+tag)]
    checks=[]
    if shutil.disk_usage(root).free<budget['min_free_bytes']:checks.append('INSUFFICIENT_FREE_SPACE')
    return {'status':'PREVIEW_ONLY','check_status':'BLOCKED' if checks else 'PASSED','checks':checks,'cron_line':cron,
            'tag':tag,'source_hash':source_fingerprint(),'installed':False,'installation_performed':False,'installation_status':'MATCHING_LINES_REQUIRE_REVIEW' if registered else 'NO_MATCH_OBSERVED','observed_crontab':installation,'matching_lines':registered,
            'dry_run':True,'financial_events_added':0,'natural_forward_verified':False,
            'disable':'由用户crontab -e移除此精确tag行；不停止其他任务，已提交事实不变',
            'resume':'重新预检当前源码/输入后，由用户恢复精确行；不把历史回放计为自然前向证据'}
