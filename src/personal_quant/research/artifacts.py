"""Whitelisted, versioned research packages. Verification never executes code."""
from __future__ import annotations
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from uuid import uuid4
from ..common import QuantError, digest, now_utc, write_json
from ..locks import publication_lock
from ..strategies.archive import source_fingerprint

LOCK_FILES = ('pyproject.toml','conda-linux-64.lock','requirements-linux-py311.lock','environment.yml',
              'requirements-options-linux-py311.lock')


def files(root):
    result = {}
    for p in sorted(Path(root).rglob('*')):
        if p.is_symlink():
            raise QuantError('UNSAFE_ARCHIVE', '归档不接受符号链接')
        if p.is_file() and p.name != 'package-manifest.json':
            result[p.relative_to(root).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return result


def code_hash(root):
    base = Path(root) / 'src/personal_quant'
    return digest({p.relative_to(base).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in sorted(base.rglob('*.py'))})


def capture_source(runtime):
    expected = source_fingerprint()
    destination = Path(runtime) / 'source-archives' / expected
    package = Path(__file__).resolve().parents[1]
    project = package.parent.parent
    if (project/'src/personal_quant').resolve()==package and (project/'pyproject.toml').is_file():
        locks=project
    else:
        locks=Path(sys.prefix)/'share/lyrax/locks'
    if any(not (locks/name).is_file() or (locks/name).is_symlink() for name in LOCK_FILES):
        raise QuantError('SOURCE_UNAVAILABLE','安装缺少源码归档所需的发布依赖锁；请安装完整wheel资源')
    from ..options.adapter_resources import adapter_root,source_hashes
    adapter=adapter_root();native=source_hashes(adapter)
    with publication_lock(runtime):
        if not destination.exists():
            pending = destination.parent / ('.pending-' + uuid4().hex)
            pending.mkdir(parents=True)
            try:
                sources=[(p,Path('src/personal_quant')/p.relative_to(package)) for p in package.rglob('*.py')]
                sources.extend((locks/name,Path(name)) for name in LOCK_FILES)
                sources.extend((adapter/name,Path('engines/lean')/name) for name in native)
                for source,relative in sources:
                    if source.is_symlink() or not source.is_file():
                        raise QuantError('SOURCE_UNAVAILABLE','源码/依赖锁白名单文件缺失')
                    target = pending / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source,target)
                if code_hash(pending) != expected or source_fingerprint() != expected:
                    raise QuantError('SOURCE_CHANGED','采集源码时工作树改变，未发布归档')
                write_json(pending/'source-manifest.json', {'source_hash':expected,'files':files(pending), 'captured_at':now_utc()})
                os.rename(pending,destination)
            finally:
                if pending.exists(): shutil.rmtree(pending)
        verify_source(destination,expected)
        for name in LOCK_FILES:
            if hashlib.sha256((locks/name).read_bytes()).hexdigest()!=hashlib.sha256((destination/name).read_bytes()).hexdigest():
                raise QuantError('SOURCE_LOCK_CHANGED','同一源码身份的依赖声明/锁文件已改变，请更新实现版本后提交研究')
        for name,expected_hash in native.items():
            archived=destination/'engines/lean'/name
            if not archived.is_file() or hashlib.sha256(archived.read_bytes()).hexdigest()!=expected_hash:
                raise QuantError('SOURCE_RESOURCE_CHANGED','同一Python身份的适配资源已变化，不能覆盖旧归档')
    return destination


def verify_source(root, expected):
    root=Path(root)
    if code_hash(root) != expected:
        raise QuantError('SOURCE_UNAVAILABLE','归档源码与原运行指纹不符')
    manifest=json.loads((root/'source-manifest.json').read_text()) if (root/'source-manifest.json').exists() else json.loads((root/'manifest.json').read_text())
    if manifest['source_hash'] != expected:
        raise QuantError('SOURCE_UNAVAILABLE','源码清单身份不一致')
    actual=files(root)
    actual.pop('source-manifest.json' if (root/'source-manifest.json').exists() else 'manifest.json',None)
    if actual!=manifest['files']:
        raise QuantError('CORRUPT_SOURCE','源码归档含缺失、额外或改变的文件，不允许自动打包')
    for relative,h in manifest['files'].items():
        safe_relative(relative)
        if hashlib.sha256((root/relative).read_bytes()).hexdigest() != h:
            raise QuantError('CORRUPT_SOURCE','归档源码/锁文件损坏')
    return manifest


def safe_relative(name):
    p=Path(name)
    if not isinstance(name,str) or p.is_absolute() or '..' in p.parts or '\\' in name or p.as_posix()!=name:
        raise QuantError('UNSAFE_ARCHIVE','归档路径越界')
    return p


def export_package(service, run_id, destination, *, source_archive=None):
    destination=Path(destination)
    if destination.exists(): raise QuantError('NONEMPTY_DESTINATION','研究包目标必须不存在')
    report=service.reports/run_id
    manifest=service._report(run_id)
    source=Path(source_archive) if source_archive else service.root/'source-archives'/manifest['source_hash']
    if not source.exists(): raise QuantError('SOURCE_UNAVAILABLE','缺少原运行源码，请提供匹配的基线归档')
    verify_source(source,manifest['source_hash'])
    bundle=manifest['data_bundle']
    destination.parent.mkdir(parents=True,exist_ok=True)
    pending=destination.with_name('.pending-package-'+uuid4().hex)
    pending.mkdir()
    try:
        shutil.copytree(source,pending/'code')
        shutil.copytree(report,pending/'report')
        workspace=pending/'workspace';runtime=workspace/manifest['config']['runtime_dir']
        for snapshot in {bundle['signal_snapshot_id'],bundle.get('execution_snapshot_id')} - {None}:
            shutil.copytree(service.root/'data'/snapshot,runtime/'data'/snapshot)
        if bundle.get('factor_snapshot_id'):
            shutil.copytree(service.root/'factors'/bundle['factor_snapshot_id'],runtime/'factors'/bundle['factor_snapshot_id'])
        write_json(workspace/'config.json',manifest['config'])
        body={'format_version':1,'kind':'research_only','run_id':run_id,'source_hash':manifest['source_hash'],
              'dependencies':manifest['dependencies'],'data_bundle':bundle,'source_permissions':'Local replay only; source/data licenses remain applicable',
              'contains_account_database':False,'offline_wheels_included':False,'files':files(pending)}
        body['archive_id']=digest(body)
        write_json(pending/'package-manifest.json',body)
        verify_package(pending)
        with publication_lock(service.root):
            os.rename(pending,destination)
            if service.ledger.connection.execute('SELECT version FROM schema_version').fetchone()[0]>=4:
                with service.ledger.transaction():
                    from ..common import canonical
                    service.ledger.connection.execute('INSERT OR IGNORE INTO research_archives VALUES(?,?,?,?)',(body['archive_id'],run_id,canonical(body),now_utc()))
        return {'status':'SUCCESS','archive_id':body['archive_id'],'path':str(destination),'source_hash':body['source_hash']}
    finally:
        if pending.exists(): shutil.rmtree(pending)


def verify_package(source):
    source=Path(source)
    if source.is_symlink(): raise QuantError('UNSAFE_ARCHIVE','不能使用链接归档')
    try:
        body=json.loads((source/'package-manifest.json').read_text())
        identity=body.pop('archive_id')
        if digest(body)!=identity or body['format_version']!=1 or body['kind']!='research_only' or body['contains_account_database']:
            raise ValueError('identity')
        body['archive_id']=identity
        if files(source)!=body['files']: raise ValueError('files')
        for name in body['files']: safe_relative(name)
        verify_source(source/'code',body['source_hash'])
        report=json.loads((source/'report/manifest.json').read_text())
        if report['run_id']!=body['run_id'] or report['source_hash']!=body['source_hash']: raise ValueError('report')
        return body
    except (OSError,KeyError,ValueError,TypeError) as exc:
        if isinstance(exc,QuantError): raise
        raise QuantError('CORRUPT_RESEARCH_PACKAGE','研究包清单/文件不完整或已改变') from exc


def restore_package(source,destination):
    body=verify_package(source);destination=Path(destination)
    if destination.exists(): raise QuantError('NONEMPTY_DESTINATION','恢复目标必须不存在')
    if destination.resolve().is_relative_to(Path(source).resolve()): raise QuantError('UNSAFE_ARCHIVE','恢复目录不能位于研究包内')
    pending=destination.with_name('.pending-restore-'+uuid4().hex)
    try:
        shutil.copytree(source,pending)
        verify_package(pending)
        os.rename(pending,destination)
        return {'status':'SUCCESS','archive_id':body['archive_id'],'path':str(destination),'code_executed':False}
    finally:
        if pending.exists(): shutil.rmtree(pending)


REPLAY_SCRIPT = '''
from pathlib import Path
import json
from personal_quant.config import Config
from personal_quant.data.store import DataStore
from personal_quant.data.factors import FactorStore
from personal_quant.strategies.spec import StrategySpec, DataBundle
from personal_quant.research.backtest import run_research
base=Path.cwd().parent
manifest=json.loads((base/'report/manifest.json').read_text())
config=Config.from_dict(manifest['config']);bundle=DataBundle(**manifest['data_bundle'])
factors=FactorStore(Path(config.runtime_dir)/'factors')
selector=(lambda spec,instant: factors.select(bundle.factor_snapshot_id,spec,instant)) if bundle.factor_snapshot_id else None
result=run_research(DataStore(Path(config.runtime_dir)/'data'),config,Path('replay-reports'),bundle.signal_snapshot_id,
 members={key:StrategySpec.from_dict(item) for key,item in manifest['members'].items()},benchmark=manifest['benchmark_member_id'],bundle=bundle,factor_selector=selector)
print(json.dumps({'run_id':result['run_id']}))
'''


def replay_package(source, destination):
    source=Path(source).absolute();body=verify_package(source)
    for name,version in body['dependencies'].items():
        if importlib.metadata.version(name)!=version:
            raise QuantError('REPLAY_ENVIRONMENT_MISMATCH','先按原包锁文件安装兼容依赖')
    restore_package(source, destination)
    source=Path(destination).absolute()
    env=dict(os.environ);env.pop('PYTHONHOME',None);env['PYTHONDONTWRITEBYTECODE']='1';env['PYTHONNOUSERSITE']='1';env['PYTHONPATH']=str(source/'code/src')
    result=subprocess.run([sys.executable,'-c',REPLAY_SCRIPT],cwd=source/'workspace',env=env,capture_output=True,text=True)
    if result.returncode:
        raise QuantError('REPLAY_FAILED',result.stderr[-3000:])
    lines=result.stdout.strip().splitlines();value=json.loads(lines[-1])
    return {'status':'SUCCESS','archive_id':body['archive_id'],'original_run_id':body['run_id'],
            'replay_run_id':value['run_id'],'report':str(source/'workspace/replay-reports'/value['run_id']),'research_only':True}
