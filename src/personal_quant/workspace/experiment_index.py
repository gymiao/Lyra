"""Explicit workspace indexes and notes; no automatic filesystem discovery."""
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from datetime import date
import re
from ..common import QuantError,digest,now_utc
from ..locks import publication_lock
from ..portfolio import Ledger
from ..processes import python_command,python_environment
from .service import read_workspace,status


def index(request):
    if (not isinstance(request,dict) or set(request)-{'workspaces','filters'}
            or not isinstance(request.get('workspaces'),list) or not 1<=len(request['workspaces'])<=100):
        raise QuantError('INVALID_EXPERIMENT_INDEX','需要1至100个显式工作区及可选筛选条件')
    filters=request.get('filters',{})
    if not isinstance(filters,dict) or set(filters)-{'kind','status','template_id','data_type','strategy_version','source_hash','start_on_or_after','end_on_or_before'}:
        raise QuantError('INVALID_EXPERIMENT_INDEX','未知实验筛选字段')
    if any(not isinstance(v,str) or not v for v in filters.values()):
        raise QuantError('INVALID_EXPERIMENT_INDEX','实验筛选值须为非空字符串')
    try:
        for key in ('start_on_or_after','end_on_or_before'):
            if key in filters:
                if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',filters[key]):raise ValueError()
                date.fromisoformat(filters[key])
        if filters.get('start_on_or_after','0001-01-01')>filters.get('end_on_or_before','9999-12-31'):raise ValueError()
    except ValueError:raise QuantError('INVALID_EXPERIMENT_INDEX','区间筛选须为有效YYYY-MM-DD，开始不得晚于结束')
    rows=[];errors=[];seen=set()
    for name in request['workspaces']:
        try:
            if not isinstance(name,str) or not name:raise QuantError('INVALID_WORKSPACE','工作区路径须为非空字符串')
            root,identity,config,_=read_workspace(name)
            if identity['workspace_id'] in seen:continue
            seen.add(identity['workspace_id'])
            observer=Ledger.read_only(root/config.runtime_dir/'account.sqlite','demo');con=observer.connection
            try:
                accounts=con.execute('SELECT id FROM accounts').fetchall()
                if len(accounts)!=1 or accounts[0][0]!=identity['account_id']:raise QuantError('WORKSPACE_ACCOUNT_MISMATCH','实验工作区须为明确的单账户')
                runs=con.execute('SELECT * FROM simulation_runs ORDER BY updated_at DESC').fetchall() if con.execute("SELECT 1 FROM sqlite_master WHERE name='simulation_runs'").fetchone() else []
                for run in runs or [{'run_id':None,'status':'NOT_STARTED','through_session':None}]:
                    templates=[config.active_strategy] if identity['kind']=='etf' else [];source=None;versions=[]
                    requested_start=config.evaluation_start;requested_end=config.evaluation_end
                    observed_start=observed_end=None
                    if run['run_id']:
                        source=run['source_hash']
                        observed_start,observed_end=con.execute('SELECT min(session),max(session) FROM simulation_checkpoints WHERE run_id=?',(run['run_id'],)).fetchone()
                        if identity['kind']=='options':
                            body=json.loads((root/config.runtime_dir/'simulation/options'/run['run_id']/'request.json').read_text())
                            templates=sorted({s['selection']['template_id'] for s in body['signals']})
                            versions=sorted({s['selection']['strategy_version'] for s in body['signals']})
                            dates=[day for prices in body['execution_path']['stocks'].values() for day in prices]
                            requested_start,requested_end=min(dates),max(dates)
                        else:
                            for record in con.execute('SELECT payload,content_hash FROM strategy_signals'):
                                signal=json.loads(record[0]);basis=signal.get('request',{})
                                if basis.get('source_hash')==source and basis.get('config_hash')==config.hash:
                                    if digest(signal)!=record[1]:raise QuantError('CORRUPT_SIGNAL','实验索引的信号记录哈希改变')
                                    versions.append(signal['signal']['version'])
                            versions=sorted(set(versions))
                    notes=[]
                    for note in con.execute("SELECT details FROM tasks WHERE task_id LIKE 'simulation-note:%' ORDER BY task_id"):
                        body=json.loads(note[0])
                        if body['run_id']==run['run_id']:notes.append(body)
                    row={'workspace':str(root),'workspace_id':identity['workspace_id'],'kind':identity['kind'],
                        'account_id':identity['account_id'],'initial_cash':identity['initial_cash'],'currency':config.currency,
                        'data_type':identity['data_type'],'run_id':run['run_id'],'status':run['status'],
                        'through_session':run['through_session'],'source_hash':source,'templates':templates,'notes':notes,
                        'rule_versions':versions,'config_hash':config.hash,'configured_start':requested_start,'configured_end':requested_end,
                        'observed_start':observed_start,'observed_end':observed_end,
                        'period_basis':'observed' if observed_start else 'configured','rule_status':'RECORDED' if versions else 'NO_SIGNAL_YET'}
                    def matches(key,value):
                        if key=='template_id':return value in templates
                        if key=='strategy_version':return value in versions
                        if key=='start_on_or_after':return (observed_start or requested_start)>=value
                        if key=='end_on_or_before':return (observed_end or requested_end)<=value
                        return row.get(key)==value
                    if all(matches(key,value) for key,value in filters.items()):rows.append(row)
            finally:observer.close()
        except (QuantError,OSError,ValueError,KeyError,TypeError,sqlite3.Error) as exc:
            errors.append({'workspace':str(name),'reason':str(exc)})
    return {'schema_version':1,'read_only':True,'data_type':'synthetic_workspace_index','experiments':rows,
            'errors':errors,'status':'PARTIAL' if errors else 'PASSED','meaning':'独立模拟实验索引，金额不合并，列表不是收益排名'}


def annotate(directory,request):
    if (not isinstance(request,dict) or set(request)!={'run_id','request_id','note'}
            or any(not isinstance(request[k],str) or not request[k].strip() for k in request)
            or len(request['note'])>2000 or len(request['request_id'])>200):
        raise QuantError('INVALID_EXPERIMENT_NOTE','批注需要run_id、稳定request_id及1至2000字说明')
    root,identity,config,_=read_workspace(directory);runtime=root/config.runtime_dir
    book=Ledger(runtime/'account.sqlite','demo')
    try:
        with publication_lock(runtime),book.transaction():
            if not book.connection.execute("SELECT 1 FROM sqlite_master WHERE name='simulation_runs'").fetchone() or not book.connection.execute('SELECT 1 FROM simulation_runs WHERE run_id=?',(request['run_id'],)).fetchone():
                raise QuantError('UNKNOWN_SIMULATION','批注必须关联已有模拟运行')
            key='simulation-note:'+digest({'workspace_id':identity['workspace_id'],'run_id':request['run_id'],'request_id':request['request_id']})
            old=book.connection.execute('SELECT details FROM tasks WHERE task_id=?',(key,)).fetchone()
            if old:
                body=json.loads(old[0])
                if any(body[k]!=v for k,v in request.items()):raise QuantError('EXPERIMENT_NOTE_CONFLICT','相同批注请求ID已记录不同内容')
                return {**body,'repeated':True}
            body={**request,'workspace_id':identity['workspace_id'],'recorded_at':now_utc()}
            book.record_task(key,'SUCCESS',body);return {**body,'repeated':False}
    finally:book.close()


def export(directory,run_id,destination):
    root,identity,config,path=read_workspace(directory)
    if run_id not in {row['run_id'] for row in status(root)['runs']}:
        raise QuantError('UNKNOWN_SIMULATION','导出必须关联明确的已有运行')
    # Reuse the complete validated backup through an isolated child cwd; never
    # change the Streamlit process working directory or build a second format.
    command=[*python_command('personal_quant'),'--config',str(path),'backup-bundle','--destination',str(Path(destination).absolute())]
    result=subprocess.run(command,cwd=root,env=python_environment(),capture_output=True,text=True)
    if result.returncode:raise QuantError('EXPERIMENT_EXPORT_FAILED',result.stderr.strip() or result.stdout.strip())
    return {**json.loads(result.stdout),'run_id':run_id,'data_type':'synthetic_simulation_bundle',
        'meaning':'包含模拟账本、冻结规格、源码及引用的完整备份；使用既有restore恢复，不是默认诊断包'}
