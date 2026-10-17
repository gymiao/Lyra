"""Frozen strategy versions and explicit, backed-up workbench schema migration."""
from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from ..common import QuantError, canonical, now_utc
from ..config import Config
from ..portfolio.schema import _version, apply_workbench_schema
from .spec import StrategySpec


def enable_workbench(ledger, config_path):
    if _version(ledger.connection) >= 3:
        return {"status": "READY", "schema_version": _version(ledger.connection), "backup": None}
    from ..execution.daily import daily_lock
    from ..portfolio.backup import create_bundle, _database_info
    config = Config.load(config_path)
    root = Path(config.runtime_dir)
    if ledger.path.resolve() != (root / "account.sqlite").resolve() or ledger.environment != config.environment:
        raise QuantError("ENVIRONMENT_MISMATCH", "升级配置与账户数据库不一致")
    destination = Path("reports/v15-migrations") / uuid4().hex
    with daily_lock(root / ".daily.lock"):
        if _version(ledger.connection) >= 3:
            return {"status": "READY", "schema_version": _version(ledger.connection), "backup": None}
        backup = create_bundle(root, Path(config_path), destination, _already_locked=True)
        manifest = json.loads((destination / "manifest.json").read_text())
        with ledger.transaction():
            current = _database_info(ledger, manifest["as_of"])
            if current["logical_hash"] != manifest["database"]["logical_hash"]:
                raise QuantError("MIGRATION_SOURCE_CHANGED", "备份后数据库改变，禁止使用过期备份升级")
            apply_workbench_schema(ledger.connection)
    return {"status": "READY", "schema_version": 3, "backup": str(destination), "backup_id": backup["backup_id"]}


class StrategyStore:
    def __init__(self, ledger):
        self.ledger = ledger
        if _version(ledger.connection) < 3:
            raise QuantError("WORKBENCH_NOT_INITIALIZED", "先执行workbench-init，完成完整备份和v3升级")

    def publish(self, spec):
        spec = StrategySpec.from_dict(spec.export())
        value = spec.content()
        with self.ledger.transaction():
            row = self.ledger.connection.execute("SELECT * FROM strategy_versions WHERE strategy_id=? AND revision=?",
                                                 (value["strategy_id"], value["revision"])).fetchone()
            if row:
                if row["spec_hash"] != spec.spec_hash:
                    raise QuantError("STRATEGY_VERSION_CONFLICT", "该版本已冻结，修改参数需要新的修订号")
                return self.get(value["strategy_id"], value["revision"])
            self.ledger.connection.execute("INSERT INTO strategy_versions VALUES(?,?,?,?,?,?)",
                (value["strategy_id"], value["revision"], value["name"], spec.spec_hash, canonical(spec.export()), now_utc(),))
        return spec

    def get(self, strategy_id, revision):
        row = self.ledger.connection.execute("SELECT * FROM strategy_versions WHERE strategy_id=? AND revision=?",
                                             (strategy_id, revision)).fetchone()
        if row is None:
            raise QuantError("UNKNOWN_STRATEGY_VERSION", "冻结策略版本不存在")
        spec = StrategySpec.from_dict(json.loads(row["payload"]))
        body = spec.content()
        if spec.spec_hash != row["spec_hash"] or body["strategy_id"] != strategy_id or body["revision"] != revision:
            raise QuantError("CORRUPT_STRATEGY_SPEC", "策略记录身份或内容不匹配")
        return spec

    def list(self):
        return [{**self.get(row["strategy_id"], row["revision"]).export(), "display_name": row["display_name"],
                 "created_at": row["created_at"]} for row in self.ledger.connection.execute(
                     "SELECT * FROM strategy_versions ORDER BY strategy_id,revision")]

    def rename(self, strategy_id, revision, name):
        self.get(strategy_id, revision)
        if not isinstance(name, str) or not name.strip():
            raise QuantError("INVALID_STRATEGY_NAME", "展示名不能为空")
        with self.ledger.transaction():
            self.ledger.connection.execute("UPDATE strategy_versions SET display_name=? WHERE strategy_id=? AND revision=?",
                                           (name, strategy_id, revision))


def enable_v18(ledger, config_path):
    from ..portfolio.schema import apply_v18_schema
    from ..portfolio.backup import create_bundle, _database_info
    from ..execution.daily import daily_lock
    from ..locks import publication_lock
    enable_workbench(ledger, config_path)
    if _version(ledger.connection) >= 4:
        return {'status':'READY','schema_version':_version(ledger.connection),'backup':None}
    config = Config.load(config_path)
    root = Path(config.runtime_dir)
    if ledger.path.resolve() != (root/'account.sqlite').resolve() or config.environment != ledger.environment:
        raise QuantError('ENVIRONMENT_MISMATCH','升级配置/数据库不一致')
    destination = Path('reports/v18-migrations') / uuid4().hex
    with daily_lock(root/'.daily.lock'), publication_lock(root):
        if _version(ledger.connection) >= 4:
            return {'status':'READY','schema_version':_version(ledger.connection),'backup':None}
        backup = create_bundle(root, Path(config_path), destination, _already_locked=True)
        manifest = json.loads((destination/'manifest.json').read_text())
        with ledger.transaction():
            if _database_info(ledger, manifest['as_of'])['logical_hash'] != manifest['database']['logical_hash']:
                raise QuantError('MIGRATION_SOURCE_CHANGED','备份后事实改变，未升级')
            apply_v18_schema(ledger.connection)
    return {'status':'READY','schema_version':4,'backup':str(destination),'backup_id':backup['backup_id']}
