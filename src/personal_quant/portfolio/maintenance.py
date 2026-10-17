"""Explicit local backup inventory, retention and isolated recovery drills."""
from pathlib import Path
import shutil
from uuid import uuid4
from ..common import QuantError, now_utc
from ..locks import publication_lock
from .backup import create_bundle, restore_bundle, verify_bundle, _runtime_files


def inventory(directory, environment):
    directory = Path(directory)
    rows = []
    if directory.is_symlink():
        raise QuantError('UNSAFE_BACKUP_FILE', '备份目录不能是链接')
    for item in sorted(directory.iterdir()) if directory.exists() else []:
        if not item.is_dir() or item.name.startswith('.'):
            continue
        try:
            manifest = verify_bundle(item, environment)
            rows.append({'path': str(item), 'backup_id': manifest['backup_id'], 'status': 'VERIFIED',
                         'created_at': manifest['created_at'], 'bytes': sum(v['bytes'] for v in manifest['files'].values())})
        except (QuantError, OSError) as exc:
            rows.append({'path': str(item), 'status': 'INVALID', 'reason': str(exc)})
    return rows


def retention_preview(directory, environment, keep=3, protected_ids=()):
    if type(keep) is not int or keep < 1:
        raise QuantError('INVALID_RETENTION', '至少保留一个已验证备份')
    rows = inventory(directory, environment)
    valid = sorted((r for r in rows if r['status'] == 'VERIFIED'), key=lambda r: (r['created_at'], r['backup_id']), reverse=True)
    retained = {r['backup_id'] for r in valid[:keep]} | set(protected_ids)
    return {'status': 'PREVIEW', 'read_only': True, 'keep': keep, 'inventory': rows,
            'delete': [r for r in valid if r['backup_id'] not in retained],
            'preserve': [r for r in rows if r['status'] != 'VERIFIED' or r['backup_id'] in retained]}


def managed_backup(runtime, config_path, directory, *, keep=3, protected_ids=(), min_free_bytes=0):
    directory, runtime = Path(directory), Path(runtime)
    if type(keep) is not int or keep < 1 or type(min_free_bytes) is not int or min_free_bytes < 0:
        raise QuantError('INVALID_RETENTION', '保留数量和剩余容量阈值无效')
    directory.mkdir(parents=True, exist_ok=True)
    with publication_lock(directory):
        estimated = sum(v['bytes'] for v in _runtime_files(runtime).values())
        estimated += (runtime / 'account.sqlite').stat().st_size + Path(config_path).stat().st_size
        free = shutil.disk_usage(directory).free
        if free < estimated + min_free_bytes:
            raise QuantError('INSUFFICIENT_BACKUP_SPACE', f'备份约需{estimated}字节，另需预留{min_free_bytes}；可用{free}')
        destination = directory / ('backup-' + uuid4().hex)
        result = create_bundle(runtime, config_path, destination)
        manifest = verify_bundle(destination, result['environment'])
        protected = set(protected_ids) | {manifest['backup_id']}
        preview = retention_preview(directory, result['environment'], keep, protected)
        removed = []
        for row in preview['delete']:
            # Revalidate immediately before deleting; invalid bundles stay for diagnosis.
            current = verify_bundle(Path(row['path']), result['environment'])
            if current['backup_id'] != row['backup_id']:
                raise QuantError('BACKUP_CHANGED', '轮换前备份身份改变，停止清理')
            shutil.rmtree(row['path'])
            removed.append(row['backup_id'])
        return {**result, 'removed': removed, 'capacity': {'estimated_bytes': estimated, 'free_before': free},
                'protected_ids': sorted(protected), 'completed_at': now_utc()}


def recovery_drill(source, destination, environment):
    result = restore_bundle(source, destination, environment)
    verified = verify_bundle(Path(destination), environment)
    return {**result, 'status': 'VERIFIED', 'isolated': True, 'original_modified': False,
            'checks': {'event_counts': verified['database']['table_counts'],
                       'account_states': verified['database']['accounts'], 'references': verified['references']}}
