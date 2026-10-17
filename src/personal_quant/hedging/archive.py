"""Immutable risk artifacts; publishing an artifact never reserves account funds."""
import hashlib
import json
import os
from pathlib import Path
import shutil
from uuid import uuid4
from ..common import QuantError,digest,now_utc,write_json
from ..locks import publication_lock
from .service import exposure


def load(root,identity):
    if not isinstance(identity,str) or len(identity)!=64 or any(c not in '0123456789abcdef' for c in identity):
        raise QuantError('INVALID_EXPOSURE_ID','风险快照ID必须是内容哈希')
    directory=Path(root)/identity
    try:
        if directory.is_symlink():raise QuantError('CORRUPT_EXPOSURE_ARCHIVE','风险归档不能是链接')
        file=directory/'exposure.json';manifest=directory/'manifest.json'
        if file.is_symlink() or manifest.is_symlink():raise QuantError('CORRUPT_EXPOSURE_ARCHIVE','归档文件不能是链接')
        body=json.loads(file.read_text());meta=json.loads(manifest.read_text())
        if (meta['schema_version']!=1 or meta['exposure_id']!=identity or body['exposure_id']!=identity
                or digest({k:v for k,v in body.items() if k!='exposure_id'})!=identity
                or meta['sha256']!=hashlib.sha256(file.read_bytes()).hexdigest()
                or body['artifact_type']!='hedge_exposure'):
            raise QuantError('CORRUPT_EXPOSURE_ARCHIVE','风险归档身份、文件哈希或类型不一致')
        return body
    except (OSError,KeyError,TypeError,ValueError) as exc:
        if isinstance(exc,QuantError):raise
        raise QuantError('CORRUPT_EXPOSURE_ARCHIVE','风险归档缺失或结构错误') from exc


def publish(book,config,store,account_id,request):
    body=exposure(book,config,store,account_id,request)
    root=book.path.parent/'hedging/exposures';identity=body['exposure_id'];destination=root/identity
    with publication_lock(book.path.parent):
        root.mkdir(parents=True,exist_ok=True)
        if destination.exists():load(root,identity)
        else:
            pending=root/('.pending-'+uuid4().hex);pending.mkdir()
            try:
                write_json(pending/'exposure.json',body)
                write_json(pending/'manifest.json',{'schema_version':1,'exposure_id':identity,
                    'sha256':hashlib.sha256((pending/'exposure.json').read_bytes()).hexdigest(),'archived_at':now_utc()})
                os.rename(pending,destination)
            finally:
                if pending.exists():shutil.rmtree(pending)
    return {'exposure_id':identity,'status':body['status'],'checks':body['checks'],
            'archive':str(destination),'executable':False,'meaning':'仅归档已冻结风险输入和结果，不生成交易或新增预留'}


def validate_references(root,book):
    from ..data.store import DataStore
    from ..options.data import OptionDataStore
    directory=Path(root)/'hedging/exposures'
    if not directory.exists():return
    for item in directory.iterdir():
        if item.name.startswith('.pending-'):continue
        body=load(directory,item.name)
        if body['environment']!=book.environment or body['ledger_seq']>book.sequence(body['account_id']):
            raise QuantError('CORRUPT_EXPOSURE_ARCHIVE','风险归档账户/环境/账本依据不匹配')
        book._require_account(body['account_id'])
        basis=digest([dict(row) for row in book.connection.execute(
            'SELECT seq,event_id,content_hash,effective_at,recorded_at,payload FROM events WHERE account_id=? AND seq<=? ORDER BY seq',
            (body['account_id'],body['ledger_seq']))])
        if basis!=body['ledger_basis_hash']:
            raise QuantError('CORRUPT_EXPOSURE_ARCHIVE','风险归档所引用的原账本前缀改变')
        store=DataStore(Path(root)/'data')
        try:
            for key in ('valuation_snapshot_id','return_snapshot_id'):store.load(body[key])
            marks=body.get('option_valuation')
            if marks and marks.get('snapshot_id'):
                OptionDataStore(Path(root)/'options/chains').load(marks['snapshot_id'])
        except (OSError,ValueError,KeyError) as exc:
            raise QuantError('CORRUPT_EXPOSURE_ARCHIVE','风险归档行情引用缺失或改变') from exc
