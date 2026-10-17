"""Explicit metadata-only diagnostic export; no account rows, receipts or config values."""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
from uuid import uuid4
from ..common import QuantError,digest,now_utc,write_json
from ..portfolio import Ledger
from ..strategies.archive import source_fingerprint
from .service import read_workspace

ERROR_CODES={'UNEXPECTED_WORKER_ERROR','TASK_DEADLINE_LIMIT','TASK_INTERRUPTED','SIMULATION_SUBMISSION_BUSY','JOB_CHILD_RUNNING','CORRUPT_JOB_METADATA','LEAN_REPLAY_FAILED','SIMULATION_SOURCE_CHANGED','SIMULATION_EXTERNAL_FACTS','UNRESOLVED_ACCOUNT_FACTS',
    'SOURCE_CHANGED','SIMULATION_ACCOUNT_MISMATCH','BATCH_TIME_LIMIT','BATCH_DISK_LIMIT','BATCH_SESSION_LIMIT',
    'BATCH_MARKET_BOUNDARY','BATCH_CHILD_FAILED','WAITING_FOR_SIGNAL','WAITING_FOR_EXECUTION','INCOMPLETE_LEAN_PATH','STALE_DATA','FAILED'}


def view(directory):
    root,identity,config,_=read_workspace(directory);runtime=root/config.runtime_dir
    book=Ledger.read_only(runtime/'account.sqlite','demo')
    try:
        exists=book.connection.execute("SELECT 1 FROM sqlite_master WHERE name='simulation_runs'").fetchone()
        runs=[dict(row) for row in book.connection.execute('SELECT run_id,status,through_session,source_hash FROM simulation_runs')] if exists else []
        pending=book.connection.execute('SELECT count(*) FROM pending_option_events').fetchone()[0]
        events=book.connection.execute('SELECT count(*) FROM events').fetchone()[0]
    finally:book.close()
    # Deliberate allowlist: do not serialize identity/config/details/settings or
    # exception text. Those can contain account names, paths and credentials.
    versions={}
    for name in ('lyra-personal-quant','bt','ffn','pandas','numpy','streamlit','QuantLib'):
        try:versions[name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:versions[name]='NOT_INSTALLED'
    inputs={}
    errors=[]
    for folder in (runtime/'simulation/options',runtime/'simulation/setups'):
        for name in ('settings.json','request.json','setup-manifest.json'):
            for path in folder.glob('*/'+name):
                if path.is_file() and not path.is_symlink():inputs[digest(str(path.relative_to(runtime)))]=hashlib.sha256(path.read_bytes()).hexdigest()
    failures=[*(runtime/'simulation/options').glob('*/last-failure.json'),*(runtime/'simulation/jobs').glob('*/result.json')]
    for path in failures:
        try:
            if path.is_symlink():continue
            body=json.loads(path.read_text())
            if not isinstance(body,dict):raise ValueError('invalid receipt')
            if body.get('status') not in {None,'FAILED','BLOCKED','WAITING_FOR_DATA'}:continue
            code=body.get('code','FAILED')
            errors.append({'receipt_hash':hashlib.sha256(path.read_bytes()).hexdigest(),
                'code':code if isinstance(code,str) and code in ERROR_CODES else 'UNCLASSIFIED_ERROR'})
        except (OSError,ValueError,TypeError):errors.append({'code':'UNREADABLE_ERROR_METADATA'})
    budget_pauses=[]
    for file in (runtime/'simulation/batches').glob('*.json'):
        try:
            if file.is_symlink():continue
            body=json.loads(file.read_text())
            if not isinstance(body,dict) or not isinstance(body.get('batch'),dict):raise ValueError('invalid batch receipt')
            batch=body['batch'];reason=batch.get('reason')
            if reason in {'BATCH_TIME_LIMIT','BATCH_DISK_LIMIT','BATCH_SESSION_LIMIT','BATCH_MARKET_BOUNDARY'}:
                budget_pauses.append({'receipt_hash':hashlib.sha256(file.read_bytes()).hexdigest(),'reason':reason})
        except (OSError,ValueError,TypeError):errors.append({'code':'UNREADABLE_ERROR_METADATA'})
    from .jobs import inventory
    task_files=[{'directory_hash':digest(row['directory']),'status':row['status'],'deletable':False} for row in inventory(root)['records']]
    return {'schema_version':1,'generated_at':now_utc(),'data_type':'synthetic_workspace_diagnostics',
        'workspace_hash':digest(identity['workspace_id']),'kind':identity['kind'],'source_hash':source_fingerprint(),
        'budget_pauses':budget_pauses,'task_files':task_files,'dependencies':versions,'runs':runs,'event_count':events,'pending_option_receipts':pending,'errors':errors,
        'configuration':{'hash':config.hash,'environment':config.environment,'market':config.market,'currency':config.currency},
        'input_hashes':inputs,'storage_free_bytes':shutil.disk_usage(runtime).free,
        'schedule_installation':'UNVERIFIED','read_only':True,
        'privacy':'白名单元数据；不含账单、账户名称、配置值、自由错误文本、密钥或数据库'}


def export(directory,destination):
    root,_,config,_=read_workspace(directory);destination=Path(destination).absolute()
    if destination.exists() or destination.is_symlink():raise QuantError('NONEMPTY_DESTINATION','诊断导出需新目录')
    if destination.resolve().is_relative_to((root/config.runtime_dir).resolve()):
        raise QuantError('INVALID_DIAGNOSTIC_DESTINATION','诊断包放在运行目录外，避免改变运行清单')
    result=view(directory);destination.parent.mkdir(parents=True,exist_ok=True)
    pending=destination.parent/('.pending-diagnostic-'+uuid4().hex);pending.mkdir()
    try:
        write_json(pending/'diagnostic.json',result)
        write_json(pending/'manifest.json',{'schema_version':1,'source_hash':result['source_hash'],
            'files':{'diagnostic.json':hashlib.sha256((pending/'diagnostic.json').read_bytes()).hexdigest()}})
        os.rename(pending,destination)
    finally:
        if pending.exists():shutil.rmtree(pending)
    return {'status':'EXPORTED','directory':str(destination),'source_hash':result['source_hash'],'financial_events_added':0}
