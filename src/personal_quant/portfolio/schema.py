"""Transactional local schema upgrades; account facts are never rewritten."""
from __future__ import annotations

from pathlib import Path
import sqlite3
from uuid import uuid4

from ..common import QuantError

CORE_VERSION = 2
CURRENT_VERSION = 5
DAILY_SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_runs(run_id TEXT PRIMARY KEY, account_id TEXT NOT NULL,
 environment TEXT NOT NULL, business_date TEXT NOT NULL, config_hash TEXT NOT NULL, source_hash TEXT NOT NULL,
 status TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS daily_attempts(attempt_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES daily_runs(run_id),
 status TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT, details TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS daily_steps(step_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES daily_runs(run_id),
 name TEXT NOT NULL, input_hash TEXT NOT NULL, status TEXT NOT NULL, output TEXT NOT NULL, committed_at TEXT NOT NULL,
 UNIQUE(run_id,name,input_hash));
"""


def _version(connection):
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not tables - {"sqlite_sequence"}:
        return None
    if "schema_version" not in tables:
        raise QuantError("INVALID_DATABASE_SCHEMA", "已有数据库缺少版本信息，禁止猜测并写入")
    rows = connection.execute("SELECT version FROM schema_version").fetchall()
    if len(rows) != 1 or type(rows[0][0]) is not int or rows[0][0] < 1:
        raise QuantError("INVALID_DATABASE_SCHEMA", "数据库版本信息无效，禁止写入")
    if rows[0][0] > CURRENT_VERSION:
        raise QuantError("NEWER_DATABASE_SCHEMA", "数据库由更高版本创建，请使用兼容程序；不会降级或改写")
    return rows[0][0]


def _apply_schema(connection, base_schema):
    # DDL is a fixed internal schema, not SQL assembled from user data.
    for statement in (base_schema + DAILY_SCHEMA).split(";"):
        statement = statement.strip()
        if statement and not statement.startswith("PRAGMA") and not statement.startswith("INSERT OR IGNORE INTO schema_version"):
            connection.execute(statement)
    connection.execute("DELETE FROM schema_version")
    connection.execute("INSERT INTO schema_version VALUES(?)", (CORE_VERSION,))


def initialize(connection, path: Path, environment, base_schema):
    connection.execute("PRAGMA foreign_keys=ON")
    version = _version(connection)
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if version is not None and not {"accounts", "events", "imports", "reconciliations", "plans", "tasks"} <= tables:
        raise QuantError("INVALID_DATABASE_SCHEMA", "已有账户数据库缺少核心事实/记录表，禁止补空表猜测余额")
    if "accounts" in tables:
        modes = {row[0] for row in connection.execute("SELECT DISTINCT environment FROM accounts")}
        if modes - {environment}:
            raise QuantError("ENVIRONMENT_MISMATCH", "数据库已属于另一运行环境，禁止升级或写入")
    backup = None
    if version is not None and version < CORE_VERSION:
        backup = path.with_name(f"{path.name}.pre-v{CORE_VERSION}-{uuid4().hex}.sqlite")
        try:
            with sqlite3.connect(backup) as destination:
                connection.backup(destination)
        except Exception:
            backup.unlink(missing_ok=True)
            raise
    if version is None or version < CORE_VERSION:
        connection.execute("BEGIN IMMEDIATE")
        try:
            # Another process may have upgraded while we made the consistent backup.
            current = _version(connection)
            if current is None or current < CORE_VERSION:
                _apply_schema(connection, base_schema)
            connection.execute("COMMIT")
        except Exception as exc:
            connection.execute("ROLLBACK")
            raise QuantError("DATABASE_MIGRATION_FAILED", f"数据库升级失败并已回滚；升级前备份：{backup}") from exc
    required = {"accounts", "events", "imports", "reconciliations", "plans", "tasks", "coverage", "strategy_signals",
                "daily_runs", "daily_attempts", "daily_steps"}
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not required <= tables:
        raise QuantError("INVALID_DATABASE_SCHEMA", "数据库版本与必要表不一致，禁止继续写入")
    actual = _version(connection)
    if actual >= 3 and not WORKBENCH_TABLES <= tables:
        raise QuantError("INVALID_DATABASE_SCHEMA", "v3工作台必要表缺失")
    if actual >= 4 and not V18_TABLES <= tables:
        raise QuantError('INVALID_DATABASE_SCHEMA', 'v4数据/验证必要表缺失')
    if actual >= 5 and not V19_TABLES <= tables:
        raise QuantError('INVALID_DATABASE_SCHEMA', 'v5来源/期权必要表缺失')
    return {"version": actual, "previous_version": version, "backup": str(backup) if backup else None}


WORKBENCH_TABLES = {"strategy_versions", "strategy_bindings", "monthly_decisions", "research_experiments", "research_attempts"}
WORKBENCH_SCHEMA = """
CREATE TABLE strategy_versions(strategy_id TEXT NOT NULL, revision INTEGER NOT NULL,
 display_name TEXT NOT NULL, spec_hash TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(strategy_id,revision));
CREATE INDEX strategy_content ON strategy_versions(spec_hash);
CREATE TABLE strategy_bindings(binding_seq INTEGER PRIMARY KEY AUTOINCREMENT,
 account_id TEXT NOT NULL REFERENCES accounts(id), strategy_id TEXT NOT NULL, revision INTEGER NOT NULL,
 spec_hash TEXT NOT NULL, effective_session TEXT NOT NULL, requested_at TEXT NOT NULL,
 status TEXT NOT NULL, details TEXT NOT NULL,
 FOREIGN KEY(strategy_id,revision) REFERENCES strategy_versions(strategy_id,revision));
CREATE UNIQUE INDEX one_pending_binding ON strategy_bindings(account_id) WHERE status='PENDING';
CREATE UNIQUE INDEX one_active_binding ON strategy_bindings(account_id) WHERE status='ACTIVE';
CREATE TABLE monthly_decisions(account_id TEXT NOT NULL REFERENCES accounts(id), decision_session TEXT NOT NULL,
 binding_seq INTEGER NOT NULL REFERENCES strategy_bindings(binding_seq), spec_hash TEXT NOT NULL,
 archive_id TEXT, outcome TEXT NOT NULL, payload TEXT NOT NULL, updated_at TEXT NOT NULL,
 PRIMARY KEY(account_id,decision_session));
CREATE TABLE research_experiments(experiment_hash TEXT PRIMARY KEY, payload TEXT NOT NULL,
 created_at TEXT NOT NULL);
CREATE TABLE research_attempts(attempt_id TEXT PRIMARY KEY,
 experiment_hash TEXT NOT NULL REFERENCES research_experiments(experiment_hash), status TEXT NOT NULL,
 worker TEXT, created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT, run_id TEXT,
 details TEXT NOT NULL);
CREATE UNIQUE INDEX one_research_worker ON research_attempts((1))
 WHERE status IN ('CREATED','RUNNING','PUBLISHING');
"""


def apply_workbench_schema(connection):
    if _version(connection) != 2:
        raise QuantError("INVALID_DATABASE_SCHEMA", "工作台升级仅接受已核验的v2数据库")
    for statement in WORKBENCH_SCHEMA.split(";"):
        if statement.strip():
            connection.execute(statement)
    connection.execute("UPDATE schema_version SET version=3")


V18_SCHEMA = """
CREATE TABLE data_series(series_id TEXT PRIMARY KEY,head_snapshot_id TEXT NOT NULL,generation INTEGER NOT NULL,metadata TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE data_publications(snapshot_id TEXT PRIMARY KEY,series_id TEXT NOT NULL REFERENCES data_series(series_id),metadata TEXT NOT NULL);
CREATE TABLE data_roles(role TEXT PRIMARY KEY,series_id TEXT NOT NULL REFERENCES data_series(series_id),revision INTEGER NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE validation_protocols(protocol_id TEXT PRIMARY KEY,payload TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE validation_suites(suite_id TEXT PRIMARY KEY,status TEXT NOT NULL,payload TEXT NOT NULL,details TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE validation_items(item_id TEXT PRIMARY KEY,suite_id TEXT NOT NULL REFERENCES validation_suites(suite_id),status TEXT NOT NULL,payload TEXT NOT NULL,attempt_id TEXT,details TEXT NOT NULL);
CREATE TABLE research_archives(archive_id TEXT PRIMARY KEY,run_id TEXT NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE local_notices(notice_id TEXT PRIMARY KEY,kind TEXT NOT NULL,status TEXT NOT NULL,payload TEXT NOT NULL,first_seen TEXT NOT NULL,last_seen TEXT NOT NULL,acknowledged_at TEXT);
"""
V18_TABLES = {'data_series','data_publications','data_roles','validation_protocols','validation_suites','validation_items','research_archives','local_notices'}


def apply_v18_schema(connection):
    if _version(connection) != 3:
        raise QuantError('INVALID_DATABASE_SCHEMA', 'v1.8升级只接受v3')
    for statement in V18_SCHEMA.split(';'):
        if statement.strip():
            connection.execute(statement)
    connection.execute('UPDATE schema_version SET version=4')


V19_SCHEMA = """
CREATE TABLE source_qualifications(qualification_id TEXT PRIMARY KEY,series_id TEXT NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE statement_mappings(mapping_id TEXT NOT NULL,revision INTEGER NOT NULL,payload TEXT NOT NULL,content_hash TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(mapping_id,revision));
CREATE TABLE mapped_imports(import_id TEXT PRIMARY KEY,account_id TEXT NOT NULL REFERENCES accounts(id),payload TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE option_contracts(version_hash TEXT PRIMARY KEY,contract_id TEXT NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE option_plans(plan_id TEXT PRIMARY KEY,account_id TEXT NOT NULL REFERENCES accounts(id),status TEXT NOT NULL,payload TEXT NOT NULL,reserved_cash TEXT NOT NULL,reserved_positions TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE pending_option_events(event_id TEXT NOT NULL,account_id TEXT NOT NULL REFERENCES accounts(id),payload TEXT NOT NULL,reason TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(account_id,event_id));
"""
V19_TABLES = {'source_qualifications','statement_mappings','mapped_imports','option_contracts','option_plans','pending_option_events'}


def apply_v19_schema(connection):
    if _version(connection)!=4:raise QuantError('INVALID_DATABASE_SCHEMA','v1.9升级只接受v4')
    for statement in V19_SCHEMA.split(';'):
        if statement.strip():connection.execute(statement)
    connection.execute('UPDATE schema_version SET version=5')
