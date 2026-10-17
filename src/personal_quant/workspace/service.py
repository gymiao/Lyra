"""Workspace lifecycle. Creation publishes an independently funded demo atomically."""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from uuid import uuid4
import pandas as pd
from ..common import QuantError, canonical, decimal as D, digest, now_utc, write_json
from ..config import Config
from ..data.fixture import create_fixture
from ..data.calendar import Calendar
from ..data.store import DataStore
from ..data.catalog import DataCatalog
from ..portfolio import Ledger
from ..portfolio.schema import apply_workbench_schema,apply_v18_schema,apply_v19_schema
from ..portfolio.report import account_report
from ..execution.daily import daily_lock
from ..processes import python_command,python_environment


def read_workspace(directory):
    root=Path(directory).absolute()
    path=root/'runtime/demo/simulation/workspace.json'
    if root.is_symlink() or path.is_symlink():raise QuantError('UNSAFE_WORKSPACE','工作区不可为符号链接')
    try:body=json.loads(path.read_text())
    except (OSError,ValueError) as exc:raise QuantError('UNKNOWN_WORKSPACE','请先建立独立工作区') from exc
    if body.get('schema_version')!=1 or body.get('environment')!='demo' or digest({k:v for k,v in body.items() if k!='content_hash'})!=body.get('content_hash'):
        raise QuantError('CORRUPT_WORKSPACE','工作区身份/配置清单不一致')
    config_path=root/'config.json'
    if not config_path.exists():config_path=root/'configs/recovered.toml'
    config=Config.load(config_path)
    if config.hash!=body['config_hash']:raise QuantError('WORKSPACE_CONFIG_CHANGED','冻结配置已改变，请复制新实验')
    return root,body,config,config_path


def create(directory,spec,config):
    required={'schema_version','account_id','initial_cash','kind'}
    if (not isinstance(spec,dict) or not required<=set(spec) or set(spec)-required-{'input_bundle'} or spec['schema_version']!=1
            or spec['kind'] not in {'etf','options'} or not isinstance(spec['account_id'],str)
            or not spec['account_id'] or D(spec['initial_cash'])<=0):
        raise QuantError('INVALID_WORKSPACE_SPEC','需要schema1、账户ID、正模拟资金和etf/options类型')
    if config.environment!='demo':raise QuantError('DEMO_ONLY','本地历史模拟工作区需明确demo配置')
    if 'input_bundle' in spec and (not isinstance(spec['input_bundle'],str) or not spec['input_bundle']):
        raise QuantError('INVALID_INPUT_PACKAGE','input_bundle需明确目录路径')
    config=replace(config,demo_deposit=float(D(spec['initial_cash'])))
    config.validate();config.require_execution()
    request_hash=digest({'spec':spec,'config':config.content()})
    root=Path(directory).absolute()
    if root.exists():
        _,old,_,_=read_workspace(root)
        if old['request_hash']!=request_hash:raise QuantError('WORKSPACE_CONFLICT','目录已有不同实验，不覆盖或重置资金')
        return status(root)
    root.parent.mkdir(parents=True,exist_ok=True)
    temporary=root.parent/('.workspace-'+uuid4().hex)
    temporary.mkdir()
    try:
        runtime=temporary/'runtime/demo';runtime.mkdir(parents=True)
        write_json(temporary/'config.json',config.content())
        saved=None;imported_roles=None
        if spec.get('input_bundle'):
            from .packages import verify,copy_prices
            bundle=verify(spec['input_bundle'])
            if bundle['checks']:raise QuantError('INPUT_PACKAGE_BLOCKED','先解决输入包中的未核实事项')
            if spec['kind']=='options':
                shutil.copytree(spec['input_bundle'],runtime/'simulation/input-package')
            else:imported_roles=copy_prices(spec['input_bundle'],runtime)
        if spec['kind']=='etf':
            store=DataStore(runtime/'data')
            if imported_roles:
                frame,saved,calendar=store.load(imported_roles['signal'])
                if not set(config.symbols)<=set(frame.symbol):raise QuantError('MISSING_SYMBOLS','输入包未覆盖配置中的全部标的，请显式调整配置')
                expected_end=(Calendar.market(config.evaluation_start,config.evaluation_end).sessions[-1]
                              if calendar.kind=='verified_market_sessions' else pd.Timestamp(config.evaluation_end))
                if calendar.sessions[0]>pd.Timestamp(config.evaluation_start) or calendar.sessions[-1]<expected_end:
                    raise QuantError('INCOMPLETE_SIMULATION_RANGE','冻结输入日历未覆盖完整配置区间；请显式调整区间或输入包')
            else:
                price,dates=create_fixture(runtime/'fixtures')
                calendar=Calendar.csv(dates,'synthetic_test_sessions')
                frame=pd.read_csv(price);saved=store.save(frame,calendar)
        else:
            calendar=Calendar.market(config.evaluation_start,config.evaluation_end)
        days=calendar.sessions[(calendar.sessions>=config.evaluation_start)&(calendar.sessions<=config.evaluation_end)]
        if not len(days):raise QuantError('NO_SIMULATION_SESSIONS','样本日历不覆盖配置区间')
        clock=(calendar.close(days[0])+pd.Timedelta(minutes=config.publication_delay_minutes)).isoformat()
        workspace_id=uuid4().hex
        book=Ledger(runtime/'account.sqlite','demo')
        try:
            with book.transaction():
                apply_workbench_schema(book.connection);apply_v18_schema(book.connection);apply_v19_schema(book.connection)
            book.account(spec['account_id'])
            book.import_events(spec['account_id'],[{'event_id':'workspace:'+workspace_id+':opening','kind':'DEPOSIT',
                'amount':str(D(spec['initial_cash'])),'effective_at':clock,'source':'lyrax_simulation_assumption','evidence_type':'test'}])
            if saved:
                catalog=DataCatalog(book)
                for role in ('signal','execution','valuation'):catalog.bind(role,imported_roles[role] if imported_roles else saved['snapshot_id'],expected_revision=0)
            body={'schema_version':1,'workspace_id':workspace_id,'environment':'demo','account_id':spec['account_id'],
                  'kind':spec['kind'],'initial_cash':str(D(spec['initial_cash'])),'config_hash':config.hash,
                  'request_hash':request_hash,'created_at':now_utc(),'view_at':clock,'data_type':saved['data_type'] if saved else 'synthetic',
                  'price_snapshot_id':saved['snapshot_id'] if saved else None,'runtime_dir':'runtime/demo'}
            body['content_hash']=digest(body);write_json(runtime/'simulation/workspace.json',body)
            account_report(book,spec['account_id'],clock,{},runtime/'reports/account-latest')
        finally:book.close()
        os.rename(temporary,root)
    finally:
        if temporary.exists():shutil.rmtree(temporary)
    return status(root)


def status(directory):
    root,body,config,path=read_workspace(directory)
    database=root/body['runtime_dir']/'account.sqlite'
    connection=sqlite3.connect(database.as_uri()+'?mode=ro',uri=True);connection.row_factory=sqlite3.Row
    try:
        connection.execute('BEGIN')
        accounts=[dict(r) for r in connection.execute('SELECT * FROM accounts')]
        if len(accounts)!=1 or accounts[0]['id']!=body['account_id']:raise QuantError('WORKSPACE_ACCOUNT_MISMATCH','工作区需单一明确账户')
        runs=[]
        if connection.execute("SELECT 1 FROM sqlite_master WHERE name='simulation_runs'").fetchone():
            runs=[dict(r) for r in connection.execute('SELECT run_id,status,through_session,updated_at FROM simulation_runs ORDER BY updated_at DESC')]
        return {'status':'READY','workspace':str(root),'identity':body,'accounts':accounts,'runs':runs,
                'events':connection.execute('SELECT count(*) FROM events').fetchone()[0],'read_only':True,'config':str(path)}
    finally:connection.close()


def worker(directory,action,run_id=None,through=None,*,input_file=None,engine_root=None,dotnet=None,fee_per_contract=None,max_sessions=None,max_seconds=None,min_free_bytes=None):
    root,body,config,path=read_workspace(directory)
    command=[*python_command('personal_quant.workspace.worker'),action,'--requested-at',now_utc()]
    if run_id:command.extend(['--run-id',run_id])
    if through:command.extend(['--through',through])
    for name,value in (('file',input_file),('engine-root',engine_root),('dotnet',dotnet),('fee-per-contract',fee_per_contract)):
        if value is not None:command.extend(['--'+name,str(Path(value).absolute()) if name!='fee-per-contract' else str(value)])
    for name,value in (('max-sessions',max_sessions),('max-seconds',max_seconds),('min-free-bytes',min_free_bytes)):
        if value is not None:command.extend(['--'+name,str(value)])
    from ..processes import run_owned
    process=run_owned(command,cwd=root,timeout_seconds=max_seconds if max_seconds is not None else 3600)
    if process.returncode:
        message=process.stderr.strip() or process.stdout.strip()
        try:failure=json.loads(message)
        except ValueError:failure={}
        raise QuantError(failure.get('code','SIMULATION_FAILED'),failure.get('reason',message))
    return json.loads(process.stdout)


def launch_ui(directory,port=8501):
    root,body,config,path=read_workspace(directory)
    app=Path(__file__).absolute().parents[1]/'ui/app.py'
    return subprocess.call([*python_command('streamlit'),'run',str(app),'--server.address','127.0.0.1',
        '--server.port',str(port),'--server.headless','true','--server.fileWatcherType','none',
        '--browser.gatherUsageStats','false','--','--config',str(path)],cwd=root,env=python_environment())
