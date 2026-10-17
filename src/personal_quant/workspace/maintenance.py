"""Explicit backup checks and recovery drills; operational receipts, no money events."""
import hashlib
import json
from pathlib import Path
from ..common import QuantError,digest,now_utc,utc,write_json
from ..locks import publication_lock
from ..portfolio.backup import verify_bundle
from ..portfolio.maintenance import recovery_drill
from .service import read_workspace


def verify(directory,source,*,destination=None):
    root,identity,config,_=read_workspace(directory);runtime=root/config.runtime_dir
    source=Path(source).absolute()
    if source.resolve().is_relative_to(runtime.resolve()):
        raise QuantError('INVALID_BACKUP_LOCATION','备份放在运行目录外，避免递归引用')
    manifest=verify_bundle(source,'demo')
    frozen=source/manifest['runtime_path']/'simulation/workspace.json'
    if not frozen.is_file() or json.loads(frozen.read_text()).get('workspace_id')!=identity['workspace_id']:
        raise QuantError('BACKUP_WORKSPACE_MISMATCH','备份必须属于当前模拟工作区，不能用其他账户的核验替代')
    restored=None
    if destination is not None:
        destination=Path(destination).absolute()
        if destination.resolve().is_relative_to(runtime.resolve()):
            raise QuantError('INVALID_RECOVERY_LOCATION','恢复演练放在运行目录外的新目录')
        recovery_drill(source,destination,'demo');restored=str(destination)
    body={'schema_version':1,'kind':'RECOVERY_DRILL' if restored else 'BACKUP_VERIFICATION',
        'workspace_id':identity['workspace_id'],'backup_id':manifest['backup_id'],
        'backup_created_at':manifest['created_at'],'verified_at':now_utc(),
        'source':str(source),'source_manifest_sha256':hashlib.sha256((source/'manifest.json').read_bytes()).hexdigest(),
        'restored_to':restored,'financial_events_added':0}
    receipt={**body,'receipt_id':digest(body)}
    try:
        with publication_lock(runtime):
            folder=runtime/'maintenance/receipts'
            if folder.is_symlink() or folder.parent.is_symlink():raise QuantError('UNSAFE_MAINTENANCE_RECORD','维护记录目录不能是链接')
            write_json(folder/(receipt['receipt_id']+'.json'),receipt)
    except (OSError,QuantError) as exc:
        # The full check/restore already happened. Do not hide that fact or
        # invite another restore into the now nonempty destination.
        return {**receipt,'status':'VERIFIED_RECORD_PENDING','record_error_type':type(exc).__name__}
    return {**receipt,'status':'VERIFIED'}


def summary(directory):
    root,identity,config,_=read_workspace(directory);folder=root/config.runtime_dir/'maintenance/receipts'
    if folder.is_symlink() or folder.parent.is_symlink():raise QuantError('UNSAFE_MAINTENANCE_RECORD','维护记录目录不能是链接')
    rows=[]
    for file in folder.glob('*.json'):
        try:
            if file.is_symlink():raise ValueError('record link')
            body=json.loads(file.read_text());key=body['receipt_id']
            if (key!=file.stem or digest({k:v for k,v in body.items() if k!='receipt_id'})!=key
                    or body['workspace_id']!=identity['workspace_id'] or body['schema_version']!=1
                    or body['kind'] not in {'RECOVERY_DRILL','BACKUP_VERIFICATION'}):raise ValueError('record identity')
            if not all(isinstance(body[field],str) for field in ('verified_at','backup_created_at')):raise ValueError('record time')
            utc(body['verified_at']);utc(body['backup_created_at'])
            source=Path(body['source'])/'manifest.json'
            reference=('MANIFEST_UNCHANGED' if source.is_file() and not source.is_symlink()
                and hashlib.sha256(source.read_bytes()).hexdigest()==body['source_manifest_sha256'] else 'REFERENCE_MISSING_OR_CHANGED')
            rows.append({'kind':body['kind'],'backup_id':body['backup_id'],'verified_at':body['verified_at'],
                'backup_created_at':body['backup_created_at'],'status':'HISTORICALLY_VERIFIED',
                'reference':reference,'full_contents_rechecked':False})
        except (OSError,ValueError,KeyError,TypeError) as exc:
            rows.append({'kind':'INVALID_RECEIPT','status':'INVALID','error_type':type(exc).__name__})
    return {'records':sorted(rows,key=lambda row:row.get('verified_at',''),reverse=True),
        'schedule_installation':'UNVERIFIED','read_only':True,
        'meaning':'历史完整核验时点；查看仅核对清单身份，不重新校验备份全部内容，不证明调度已安装'}
