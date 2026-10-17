"""Explicit v1.9 migration after a verified full backup."""
import json
from pathlib import Path
from uuid import uuid4
from ..common import QuantError
from ..config import Config
from ..execution.daily import daily_lock
from ..locks import publication_lock
from ..strategies.store import enable_v18
from .backup import create_bundle, _database_info
from .schema import _version, apply_v19_schema


def enable_v19(ledger,config_path):
    enable_v18(ledger,config_path)
    if _version(ledger.connection)==5:return {'status':'READY','schema_version':5,'backup':None}
    config=Config.load(config_path);root=Path(config.runtime_dir)
    if ledger.path.resolve()!=(root/'account.sqlite').resolve() or config.environment!=ledger.environment:
        raise QuantError('ENVIRONMENT_MISMATCH','升级配置/数据库不一致')
    destination=Path('reports/v19-migrations')/uuid4().hex
    with daily_lock(root/'.daily.lock'),publication_lock(root):
        if _version(ledger.connection)==5:return {'status':'READY','schema_version':5,'backup':None}
        backup=create_bundle(root,Path(config_path),destination,_already_locked=True)
        manifest=json.loads((destination/'manifest.json').read_text())
        with ledger.transaction():
            if _database_info(ledger,manifest['as_of'])['logical_hash']!=manifest['database']['logical_hash']:
                raise QuantError('MIGRATION_SOURCE_CHANGED','备份后事实改变，停止升级')
            apply_v19_schema(ledger.connection)
    return {'status':'READY','schema_version':5,'backup':str(destination),'backup_id':backup['backup_id']}
