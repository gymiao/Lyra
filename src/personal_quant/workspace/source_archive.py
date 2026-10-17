"""Run-to-source evidence; verification reads archived code without executing it."""
import json
import importlib.metadata
import platform
from pathlib import Path
from ..common import QuantError,digest
from ..research.artifacts import capture_source,verify_source


def environment():
    packages={}
    for name in ('pandas','numpy','pyarrow','bt','ffn','streamlit','yfinance','exchange-calendars','QuantLib','pyxirr'):
        try:packages[name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:packages[name]=None
    from ..options.adapter_resources import source_hashes
    return {'python':platform.python_version(),'implementation':platform.python_implementation(),'packages':packages,'adapter_sources':source_hashes()}


def bind(book,runtime,run_id,source_hash):
    archive=capture_source(runtime)
    if archive.name!=source_hash:raise QuantError('SIMULATION_SOURCE_CHANGED','归档时源码发生变化')
    manifest=json.loads((archive/'source-manifest.json').read_text())
    body={'schema_version':1,'run_id':run_id,'source_hash':source_hash,'manifest_hash':digest(manifest),'environment':environment()}
    key='simulation-source:'+run_id
    old=book.connection.execute('SELECT details FROM tasks WHERE task_id=?',(key,)).fetchone()
    if old and json.loads(old[0])!=body:raise QuantError('SIMULATION_SOURCE_CHANGED','运行已绑定另一份源码/锁归档')
    if not old:book.record_task(key,'SUCCESS',body)
    return archive


def require(book,runtime,run_id,source_hash,*,check_environment=True):
    row=book.connection.execute('SELECT details FROM tasks WHERE task_id=?',('simulation-source:'+run_id,)).fetchone()
    if row is None:raise QuantError('SOURCE_UNAVAILABLE','运行缺少已登记的源码归档，不能猜测恢复版本')
    body=json.loads(row[0]);archive=Path(runtime)/'source-archives'/source_hash
    if body.get('schema_version')!=1 or body.get('run_id')!=run_id or body.get('source_hash')!=source_hash:
        raise QuantError('CORRUPT_SOURCE','运行与源码归档身份不一致')
    manifest=verify_source(archive,source_hash)
    if digest(manifest)!=body.get('manifest_hash'):raise QuantError('CORRUPT_SOURCE','已登记的源码/锁归档清单改变')
    if check_environment and body.get('environment')!=environment():
        raise QuantError('SIMULATION_ENVIRONMENT_CHANGED','Python或依赖版本已变化；恢复原锁环境或创建独立实验')
    return archive
