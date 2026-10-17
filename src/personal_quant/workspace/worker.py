"""Run in the workspace cwd; reuse existing daily transaction and report services."""
import argparse
import json
import sqlite3
from pathlib import Path
import pandas as pd
from ..common import QuantError,canonical,digest,now_utc,utc,write_json
from ..portfolio import Ledger
from ..data.store import DataStore
from ..execution.daily import DailyRunner,daily_lock
from ..strategies.archive import source_fingerprint
from ..locks import publication_lock
from .service import read_workspace

SCHEMA='''CREATE TABLE IF NOT EXISTS simulation_runs(
run_id TEXT PRIMARY KEY, status TEXT NOT NULL, through_session TEXT,
source_hash TEXT NOT NULL, updated_at TEXT NOT NULL, details TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS simulation_checkpoints(
run_id TEXT NOT NULL, session TEXT NOT NULL, details TEXT NOT NULL,
PRIMARY KEY(run_id,session));'''


def run(action,run_id=None,through=None,requested_at=None,**option_args):
    root,workspace,config,_=read_workspace(Path.cwd())
    if action=='operation':
        from .operations import execute
        return execute(root,json.loads(Path(option_args['input_file']).read_text()))
    if action=='batch':
        from .batch import run as batch_run
        if option_args.get('input_file') is not None or option_args.get('fee_per_contract') is not None:
            raise QuantError('INVALID_BATCH_ARGUMENTS','批次不修改冻结输入或费用')
        return batch_run(root,run_id,through,requested_at=requested_at,**{k:v for k,v in option_args.items() if k in
            {'max_sessions','max_seconds','min_free_bytes','engine_root','dotnet'} and v is not None})
    if action=='prepare':
        if workspace['kind']!='options' or not option_args.get('input_file') or run_id or through:
            raise QuantError('INVALID_OPTION_SETUP','prepare需要options工作区及明确配置文件，不接受run-id/through')
        if any(option_args.get(key) is not None for key in ('engine_root','dotnet','fee_per_contract')):
            raise QuantError('INVALID_OPTION_SETUP','prepare只冻结配置，费用来自配置文件，不接引擎或重复费用参数')
        from .option_setup import prepare
        return prepare(root,json.loads(Path(option_args['input_file']).read_text()))
    if workspace['kind']=='options':
        if action=='start' and option_args.get('input_file'):
            file=Path(option_args['input_file']).absolute()
            if (file.parent/'setup-manifest.json').exists():
                from .option_setup import load
                setup=load(file.parent)
                if file.name!='request.json' or setup['basis']['workspace_id']!=workspace['workspace_id']:
                    raise QuantError('WORKSPACE_ACCOUNT_MISMATCH','冻结配置不属于该工作区')
                if setup['basis']['source_hash']!=source_fingerprint():
                    raise QuantError('SIMULATION_SOURCE_CHANGED','冻结配置后源码变化，请准备新配置；不隐式升级旧配置')
                from ..common import decimal as D
                if D(option_args.get('fee_per_contract'))!=D(setup['basis']['spec']['fee_per_contract']):
                    raise QuantError('OPTION_SETUP_FEE_CHANGED','费用与冻结配置不同，请使用已冻结值或建立新配置')
        from .options_runner import run as options_run
        return options_run(action,run_id,through,requested_at,**option_args)
    if any(value is not None for value in option_args.values()):
        raise QuantError('INVALID_ETF_ARGUMENTS','ETF运行不接受期权输入/引擎参数')
    runtime=root/config.runtime_dir;store=DataStore(runtime/'data')
    _,meta,calendar=store.load_role('signal')
    days=calendar.sessions[(calendar.sessions>=config.evaluation_start)&(calendar.sessions<=config.evaluation_end)]
    source=source_fingerprint();identity=digest({'workspace':workspace['workspace_id'],'source':source})
    request_time=utc(requested_at or now_utc())
    book=Ledger(runtime/'account.sqlite','demo');owned=False
    try:
        if action=='pause':
            if not run_id or len(run_id)!=64 or any(c not in '0123456789abcdef' for c in run_id):raise QuantError('RUN_REQUIRED','需要有效run-id')
            row=book.connection.execute('SELECT * FROM simulation_runs WHERE run_id=?',(run_id,)).fetchone()
            if row is None:raise QuantError('UNKNOWN_SIMULATION','不存在此运行')
            write_json(runtime/'simulation/pauses'/(run_id+'.json'),{'requested_at':request_time.isoformat()})
            if row['status'] not in {'RUNNING','COMPLETED'}:book.connection.execute('UPDATE simulation_runs SET status=? WHERE run_id=?',('PAUSED',run_id))
            row=book.connection.execute('SELECT * FROM simulation_runs WHERE run_id=?',(run_id,)).fetchone()
            return {**dict(row),'pause_requested':True}
        with daily_lock(runtime/'.simulation.lock'):
            book.connection.executescript(SCHEMA)
            if action=='start':
                if book.connection.execute('SELECT 1 FROM simulation_runs WHERE source_hash<>?',(source,)).fetchone():
                    raise QuantError('SIMULATION_SOURCE_CHANGED','实现已变化，请建立独立新工作区，不在旧账本重置检查点')
                with publication_lock(runtime),book.transaction():
                    from .source_archive import bind
                    bind(book,runtime,identity,source)
                    book.connection.execute('INSERT OR IGNORE INTO simulation_runs VALUES(?,?,?,?,?,?)',(identity,'CREATED',None,source,now_utc(),'{}'))
                    from .inputs import bind as bind_inputs
                    bind_inputs(book,store,identity)
                run_id=identity
            if not run_id:raise QuantError('RUN_REQUIRED','需要明确run-id')
            row=book.connection.execute('SELECT * FROM simulation_runs WHERE run_id=?',(run_id,)).fetchone()
            if row is None:raise QuantError('UNKNOWN_SIMULATION','不存在此运行')
            if row['source_hash']!=source:raise QuantError('SIMULATION_SOURCE_CHANGED','实现已变化，保留旧运行并建立新实验')
            from .source_archive import require
            require(book,runtime,run_id,source)
            from .inputs import require as require_inputs, pinned, verify_checkpoints
            input_basis=require_inputs(book,store,run_id)
            verify_checkpoints(book,run_id,input_basis)
            store=pinned(store,input_basis)
            _,meta,calendar=store.load_role('signal')
            days=calendar.sessions[(calendar.sessions>=config.evaluation_start)&(calendar.sessions<=config.evaluation_end)]
            if action=='pause':
                if row['status']!='COMPLETED':book.connection.execute('UPDATE simulation_runs SET status=?,updated_at=? WHERE run_id=?',('PAUSED',now_utc(),run_id))
            elif action in {'step','resume'}:
                stop=pd.Timestamp(through).normalize() if through else days[-1]
                if stop not in days:raise QuantError('INVALID_SIMULATION_DAY','终点须为配置区间内明确交易日')
                if row['through_session'] and stop<pd.Timestamp(row['through_session']):raise QuantError('SIMULATION_TIME_REVERSED','运行只能前进，历史查看不会回滚账户')
                book.connection.execute('UPDATE simulation_runs SET status=?,updated_at=? WHERE run_id=?',('RUNNING',now_utc(),run_id))
                owned=True
                for day in days[days<=stop]:
                    pause=runtime/'simulation/pauses'/(run_id+'.json')
                    if pause.exists() and utc(json.loads(pause.read_text())['requested_at'])>request_time:
                        book.connection.execute('UPDATE simulation_runs SET status=? WHERE run_id=?',('PAUSED',run_id));break
                    session=str(day.date())
                    if book.connection.execute('SELECT 1 FROM simulation_checkpoints WHERE run_id=? AND session=?',(run_id,session)).fetchone():continue
                    clock=(calendar.close(day)+pd.Timedelta(minutes=config.publication_delay_minutes)).isoformat()
                    # DailyRunner slices signal history at decision time and freezes the
                    # plan before the next session's simulation. Already committed steps
                    # are recovered if process death precedes the checkpoint below.
                    result=DailyRunner(book,config,store).run(workspace['account_id'],as_of=clock,simulation_check=True)
                    result['input_bundle_id']=input_basis['input_bundle_id']
                    state='BLOCKED' if result['status'] in {'BLOCKED','FAILED','WAITING'} else 'RUNNING'
                    with book.transaction():
                        if state!='BLOCKED':book.connection.execute('INSERT INTO simulation_checkpoints VALUES(?,?,?)',(run_id,session,canonical(result)))
                        book.connection.execute('UPDATE simulation_runs SET status=?,through_session=?,updated_at=?,details=? WHERE run_id=?',
                            (state,session if state!='BLOCKED' else book.connection.execute('SELECT through_session FROM simulation_runs WHERE run_id=?',(run_id,)).fetchone()[0],now_utc(),canonical(result),run_id))
                    if state=='BLOCKED':break
                else:
                    book.connection.execute('UPDATE simulation_runs SET status=? WHERE run_id=?',('COMPLETED' if stop==days[-1] else 'PAUSED',run_id))
            result=dict(book.connection.execute('SELECT * FROM simulation_runs WHERE run_id=?',(run_id,)).fetchone())
            result['details']=json.loads(result['details']);result['data_type']='synthetic_historical_simulation'
            result['account_id']=workspace['account_id'];result['events']=book.sequence(workspace['account_id'])
            return result
    except BaseException as exc:
        if owned and run_id:
            book.connection.execute('UPDATE simulation_runs SET status=?,updated_at=?,details=? WHERE run_id=?',
                ('FAILED',now_utc(),canonical({'code':getattr(exc,'code','INTERRUPTED'),'reason':str(exc)}),run_id))
        raise
    finally:book.close()



def last_checkpoint(run_id):
    if not run_id:return {'run_id':None,'session':None,'status':'UNKNOWN_FROM_REQUEST'}
    try:
        root,identity,config,_=read_workspace(Path.cwd())
        book=Ledger.read_only(root/config.runtime_dir/'account.sqlite','demo')
        try:
            row=book.connection.execute('SELECT through_session FROM simulation_runs WHERE run_id=?',(run_id,)).fetchone()
            return {'run_id':run_id,'session':row[0] if row else None,'ledger_seq':book.sequence(identity['account_id']),'status':'READ_FROM_LEDGER' if row else 'UNKNOWN_RUN'}
        finally:book.close()
    except (QuantError,OSError,sqlite3.Error):return {'run_id':run_id,'session':None,'status':'UNAVAILABLE_REQUIRE_REVIEW'}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','start','step','pause','resume','batch','operation'])
    parser.add_argument('--run-id');parser.add_argument('--through');parser.add_argument('--requested-at');parser.add_argument('--result-file',type=Path)
    parser.add_argument('--file',dest='input_file');parser.add_argument('--engine-root');parser.add_argument('--dotnet');parser.add_argument('--fee-per-contract',type=float)
    parser.add_argument('--max-sessions',type=int);parser.add_argument('--max-seconds',type=float);parser.add_argument('--min-free-bytes',type=int)
    parser.add_argument('--job-id');parser.add_argument('--job-token')
    args=parser.parse_args()
    import time
    started=time.monotonic();started_at=now_utc()
    record=None
    try:
        if bool(args.job_id)!=bool(args.job_token):raise QuantError('INVALID_JOB_TOKEN','需要任务ID与认领令牌')
        if args.job_id:
            from .jobs import claim
            record=claim(Path.cwd(),args.job_id,args.job_token)
            from .task_progress import configure,phase
            root,_,config,_=read_workspace(Path.cwd())
            configure(root/config.runtime_dir/'simulation/jobs'/args.job_id)
            phase('CLAIMED')
        if args.result_file:
            target=args.result_file.absolute()
            if not target.resolve().is_relative_to((Path.cwd()/'runtime/demo/simulation/jobs').resolve()):
                raise QuantError('UNSAFE_JOB_PATH','结果文件须位于本工作区任务目录')
        budget={k:getattr(args,k) for k in ('max_sessions','max_seconds','min_free_bytes') if getattr(args,k) is not None}
        if args.action!='batch' and any(k in budget for k in ('max_sessions','min_free_bytes')):raise QuantError('INVALID_BATCH_ARGUMENTS','交易日/容量预算只用于batch')
        from .task_budget import enforce,deadline
        from .task_progress import phase
        due=record.get('deadline_at') if record else None
        if args.action!='batch' and due is None:due=deadline(started_at,args.max_seconds)
        phase('PRECHECK')
        with enforce(due):
            phase('EXECUTING')
            result=run(args.action,args.run_id,args.through,args.requested_at,input_file=args.input_file,
                       engine_root=args.engine_root,dotnet=args.dotnet,fee_per_contract=args.fee_per_contract,**(budget if args.action=='batch' else {}))
            phase('PUBLISHING')
            result={**result,'transport_status':'SUCCEEDED','last_committed_checkpoint':last_checkpoint(result.get('run_id')),'operation_timing':{'started_at':started_at,'finished_at':now_utc(),'seconds':time.monotonic()-started}}
            if args.result_file:
                from ..common import write_json
                target=args.result_file.absolute()
                write_json(target,result)
            print(canonical(result))
    except Exception as exc:
        known=isinstance(exc,(QuantError,ValueError,OSError,sqlite3.Error))
        failure_code=getattr(exc,'code','FAILED' if known else 'UNEXPECTED_WORKER_ERROR')
        if args.result_file:
            from ..common import write_json
            target=args.result_file.absolute()
            if target.resolve().is_relative_to((Path.cwd()/'runtime/demo/simulation/jobs').resolve()):
                try:
                    if not known:
                        import traceback
                        (target.parent/'worker-traceback.log').write_text(traceback.format_exc())
                    write_json(target,{'status':'FAILED','transport_status':'FAILED','last_committed_checkpoint':last_checkpoint(args.run_id),'reason':str(exc),'code':failure_code,
                        'persistence_notes':getattr(exc,'__notes__',[])})
                except Exception as logging_error:exc.add_note('任务结果未能落盘，需释放空间后核实：'+str(logging_error))
        message=str(exc)
        if getattr(exc,'__notes__',None):message+='；'+'；'.join(exc.__notes__)
        print(canonical({'status':'FAILED','code':failure_code,'reason':message,
                         'phase':'WORKER','retryability':'REQUIRES_REVIEW'}),file=__import__('sys').stderr);raise SystemExit(1)

if __name__=='__main__':main()
