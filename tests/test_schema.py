import json
from pathlib import Path
import sqlite3

import pytest

from personal_quant.cli import main
from personal_quant.common import QuantError, decimal as D
from personal_quant.portfolio import Ledger
from personal_quant.portfolio import schema
from conftest import event


def legacy_database(path):
    book = Ledger(path, "demo")
    book.account("sample")
    book.import_events("sample", [event("deposit", "DEPOSIT", amount=1000)])
    for table in ("daily_steps", "daily_attempts", "daily_runs"):
        book.connection.execute(f"DROP TABLE {table}")
    book.connection.execute("UPDATE schema_version SET version=1")
    book.close()


def test_upgrade_makes_consistent_backup_and_preserves_facts(tmp_path):
    path = tmp_path / "legacy.sqlite"
    legacy_database(path)
    upgraded = Ledger(path, "demo")
    try:
        assert upgraded.schema_info["previous_version"] == 1
        assert upgraded.connection.execute("SELECT version FROM schema_version").fetchone()[0] == 2
        assert D(upgraded.snapshot("sample", "2024-07-31T21:00:00Z")["settled_cash"]) == 1000
        assert upgraded.import_events("sample", [event("deposit", "DEPOSIT", amount=1000)])["duplicates"] == 1
        with sqlite3.connect(upgraded.schema_info["backup"]) as old:
            assert old.execute("SELECT version FROM schema_version").fetchone()[0] == 1
            assert old.execute("SELECT count(*) FROM events").fetchone()[0] == 1
    finally:
        upgraded.close()
    reopened = Ledger(path, "demo")
    assert reopened.schema_info["backup"] is None
    reopened.close()


def test_failed_upgrade_rolls_back_schema_and_keeps_backup(tmp_path, monkeypatch):
    path = tmp_path / "legacy.sqlite"
    legacy_database(path)
    def fail(connection, base):
        connection.execute("CREATE TABLE partial_upgrade(id INTEGER)")
        connection.execute("UPDATE schema_version SET version=2")
        raise RuntimeError("injected migration interruption")
    monkeypatch.setattr(schema, "_apply_schema", fail)
    with pytest.raises(QuantError) as exc:
        Ledger(path, "demo")
    assert exc.value.code == "DATABASE_MIGRATION_FAILED"
    with sqlite3.connect(path) as old:
        assert old.execute("SELECT version FROM schema_version").fetchone()[0] == 1
        assert old.execute("SELECT name FROM sqlite_master WHERE name='partial_upgrade'").fetchone() is None
        assert old.execute("SELECT count(*) FROM events").fetchone()[0] == 1
    assert len(list(tmp_path.glob("*.pre-v2-*.sqlite"))) == 1


def test_future_schema_rejected_without_mutation_even_by_error_logger(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    path = Path("runtime/demo/account.sqlite")
    book = Ledger(path, "demo")
    book.connection.execute("UPDATE schema_version SET version=99")
    book.close()
    before = path.read_bytes()
    config = Path(__file__).resolve().parents[1] / "configs/demo.toml"
    assert main(["--config", str(config), "status"]) == 2
    result = json.loads(capsys.readouterr().err)
    assert result["code"] == result["task_log_error"]["code"] == "NEWER_DATABASE_SCHEMA"
    assert path.read_bytes() == before


def test_wrong_environment_does_not_upgrade_legacy_database(tmp_path):
    path = tmp_path / "legacy.sqlite"
    legacy_database(path)
    before = path.read_bytes()
    with pytest.raises(QuantError, match="另一运行环境"):
        Ledger(path, "real")
    assert path.read_bytes() == before
    assert not list(tmp_path.glob("*.pre-v2-*.sqlite"))


def test_missing_core_table_does_not_get_recreated_as_empty(tmp_path):
    path = tmp_path / "legacy.sqlite"
    legacy_database(path)
    with sqlite3.connect(path) as damaged:
        damaged.execute("DROP TABLE imports")
    before = path.read_bytes()
    with pytest.raises(QuantError) as exc:
        Ledger(path, "demo")
    assert exc.value.code == "INVALID_DATABASE_SCHEMA"
    assert path.read_bytes() == before
