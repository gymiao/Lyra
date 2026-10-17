"""Bound a public resume by trading sessions, wall time and free disk space."""
import json
import math
import os
from pathlib import Path
import re
import signal
import shutil
import subprocess
from subprocess import Popen as _OwnedProcess
import sys
import time
from uuid import uuid4
import pandas as pd
from ..common import QuantError,now_utc,write_json,utc
from ..data.calendar import Calendar
from ..execution.daily import daily_lock
from ..portfolio import Ledger
from ..strategies.archive import source_fingerprint
from .service import read_workspace
from ..processes import python_command,python_environment


def limits(max_sessions=128,max_seconds=3600,min_free_bytes=67108864):
    if (type(max_sessions) is not int or not 1<=max_sessions<=10000
            or isinstance(max_seconds,bool) or not isinstance(max_seconds,(int,float))
            or not math.isfinite(max_seconds) or not 0<max_seconds<=86400
            or type(min_free_bytes) is not int or min_free_bytes<0):
        raise QuantError('INVALID_BATCH_LIMITS','批次需1–10000交易日、有限正秒数（最多86400）、非负剩余字节')
    return {'max_sessions':max_sessions,'max_seconds':max_seconds,'min_free_bytes':min_free_bytes}


def _row(runtime,run_id):
    book=Ledger.read_only(runtime/'account.sqlite','demo')
    try:
        if not book.connection.execute("SELECT 1 FROM sqlite_master WHERE name='simulation_runs'").fetchone():
            raise QuantError('UNKNOWN_SIMULATION','先建立模拟运行，再按run-id推进')
        row=book.connection.execute('SELECT * FROM simulation_runs WHERE run_id=?',(run_id,)).fetchone()
        if row is None:raise QuantError('UNKNOWN_SIMULATION','批量推进需要已经建立的运行')
        return {**dict(row),'events':book.sequence(book.connection.execute('SELECT id FROM accounts').fetchone()[0])}
    finally:book.close()


def _stop(process):
    # Only the process group we created for this attempt, never a port owner.
    if not isinstance(process,_OwnedProcess):return
    try:
        os.killpg(process.pid,signal.SIGTERM)
    except ProcessLookupError:return
    try:process.wait(timeout=5)
    except subprocess.TimeoutExpired:pass
    # A launcher can exit before its engine. Reap our group as well as its leader.
    try:os.killpg(process.pid,signal.SIGKILL)
    except ProcessLookupError:pass
    process.wait()


def run(directory,run_id,through,*,max_sessions=128,max_seconds=3600,min_free_bytes=67108864,
        engine_root=None,dotnet=None,requested_at=None):
    total_started=time.monotonic()
    submitted_at=utc(requested_at or now_utc()).isoformat()
    budget=limits(max_sessions,max_seconds,min_free_bytes)
    if not isinstance(run_id,str) or not re.fullmatch('[0-9a-f]{64}',run_id):raise QuantError('RUN_REQUIRED','需要有效run-id')
    if not isinstance(through,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',through):raise QuantError('INVALID_SIMULATION_DAY','需要YYYY-MM-DD交易日')
    root,identity,config,_=read_workspace(directory);runtime=root/config.runtime_dir
    if bool(engine_root)!=bool(dotnet):raise QuantError('SIMULATION_TOOL_PATHS_REQUIRED','同时提供两个工具路径')
    if identity['kind']=='etf' and engine_root:raise QuantError('INVALID_ETF_ARGUMENTS','ETF不接受期权工具路径')
    with daily_lock(runtime/'.batch.lock'):
        before=_row(runtime,run_id)
        if before['source_hash']!=source_fingerprint():raise QuantError('SIMULATION_SOURCE_CHANGED','代码变化，请保留旧运行并建立新实验')
        if identity['kind']=='etf':
            from .inputs import require as require_inputs,pinned
            from ..data.store import DataStore
            store=DataStore(runtime/'data');book=Ledger.read_only(runtime/'account.sqlite','demo')
            try:basis=require_inputs(book,store,run_id)
            finally:book.close()
            calendar=pinned(store,basis).load_role('signal')[2]
            calendar=Calendar(calendar.schedule.loc[config.evaluation_start:config.evaluation_end],calendar.kind)
        else:
            request=json.loads((runtime/'simulation/options'/run_id/'request.json').read_text())
            start=request['signals'][0]['applicable_session']
            market_end=max(max(rows) for rows in request['execution_path']['stocks'].values())
            end=str((pd.Timestamp(market_end)+pd.Timedelta(days=10)).date())
            calendar=Calendar.market(start,end)
        target=pd.Timestamp(through)
        if target not in calendar.sessions:raise QuantError('INVALID_SIMULATION_DAY','批次终点必须在运行支持区间的交易日')
        if before['through_session'] and target<pd.Timestamp(before['through_session']):raise QuantError('SIMULATION_TIME_REVERSED','不能回退运行时钟')
        days=calendar.sessions[calendar.sessions<=target]
        if before['through_session']:days=days[days>pd.Timestamp(before['through_session'])]
        cutoff=str(days[min(len(days),max_sessions)-1].date()) if len(days) else through
        if identity['kind']=='options' and cutoff>market_end and (not before['through_session'] or before['through_session']<market_end):
            cutoff=market_end
        attempt=uuid4().hex;folder=runtime/'simulation/jobs'/('batch-child-'+attempt);folder.mkdir(parents=True)
        command=[*python_command('personal_quant.workspace.worker'),'resume','--run-id',run_id,'--through',cutoff,'--requested-at',submitted_at,
                 '--result-file',str(folder/'result.json')]
        for key,value in (('engine-root',engine_root),('dotnet',dotnet)):
            if value:command.extend(['--'+key,str(Path(value).absolute())])
        started=time.monotonic();reason=None;process=None
        if started-total_started>=max_seconds:reason='BATCH_TIME_LIMIT'
        elif shutil.disk_usage(runtime).free<min_free_bytes:reason='BATCH_DISK_LIMIT'
        else:
            with (folder/'stdout.log').open('w') as stdout,(folder/'stderr.log').open('w') as stderr:
                process=subprocess.Popen(command,cwd=root,env=python_environment(),stdout=stdout,stderr=stderr,start_new_session=True)
                try:
                    from ..research.service import process_identity
                    write_json(folder/'owner.json',{'parent_owner':process_identity(),'owner':process_identity(process.pid),'run_id':run_id})
                    while process.poll() is None:
                        if time.monotonic()-total_started>=max_seconds:reason='BATCH_TIME_LIMIT';break
                        if shutil.disk_usage(runtime).free<min_free_bytes:reason='BATCH_DISK_LIMIT';break
                        try:process.wait(timeout=min(.2,max(.001,max_seconds-(time.monotonic()-total_started))))
                        except subprocess.TimeoutExpired:pass
                finally:
                    _stop(process)
        receipt=folder/'result.json';child=json.loads(receipt.read_text()) if receipt.is_file() else {}
        if reason:
            # A killed daily task can have committed facts before its checkpoint.
            # Existing recovery handles that prefix; do not edit any money facts.
            with daily_lock(runtime/'.simulation.lock'):
                book=Ledger(runtime/'account.sqlite','demo')
                try:book.connection.execute("UPDATE simulation_runs SET status='PAUSED',updated_at=? WHERE run_id=? AND status IN ('CREATED','RUNNING','FAILED')",(now_utc(),run_id))
                finally:book.close()
        after=_row(runtime,run_id)
        if not reason and process.returncode:
            code=child.get('code','BATCH_CHILD_FAILED')
            state=('WAITING_FOR_DATA' if code in {'WAITING_FOR_SIGNAL','WAITING_FOR_EXECUTION','INCOMPLETE_LEAN_PATH','MISSING_PRICES','STALE_DATA'}
                   else 'FAILED' if code in {'FAILED','BATCH_CHILD_FAILED','LEAN_REPLAY_FAILED'} else 'BLOCKED')
            reason=code
            with daily_lock(runtime/'.simulation.lock'):
                book=Ledger(runtime/'account.sqlite','demo')
                try:book.connection.execute('UPDATE simulation_runs SET status=?,updated_at=? WHERE run_id=? AND status NOT IN (?,?)',(state,now_utc(),run_id,'COMPLETED','REPORT_PENDING'))
                finally:book.close()
            after=_row(runtime,run_id)
        elif not reason and cutoff!=through:reason='BATCH_MARKET_BOUNDARY' if identity['kind']=='options' and cutoff==market_end else 'BATCH_SESSION_LIMIT'
        result={**after,'details':json.loads(after['details']),'requested_through':through,
            'batch':{'attempt_id':attempt,'limits':budget,'reason':reason,'effective_through':cutoff,
                     'elapsed_seconds':time.monotonic()-total_started,'preflight_seconds':started-total_started,'execution_seconds':time.monotonic()-started,'child_directory':str(folder.relative_to(runtime)),
                     'grace_seconds':5,'meaning':'按交易日截断；耗时/容量停止自有子进程组，保留已提交事实，恢复时由原流程核对检查点'},
            'status':after['status']}
        write_json(runtime/'simulation/batches'/(attempt+'.json'),result)
        return result
