from pathlib import Path
import json
import sqlite3

import pytest

from conftest import event
from personal_quant.common import QuantError
from personal_quant.portfolio import Ledger
from personal_quant.portfolio.backup import verify_bundle
from personal_quant.strategies.spec import StrategySpec
from personal_quant.strategies.store import StrategyStore, enable_workbench


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    source = Path(__file__).resolve().parents[1] / "configs/demo.toml"
    monkeypatch.chdir(tmp_path)
    Path("configs").mkdir()
    config = Path("configs/demo.toml"); config.write_bytes(source.read_bytes())
    book = Ledger(Path("runtime/demo/account.sqlite"), "demo")
    book.account("sample")
    book.import_events("sample", [event("cash", "DEPOSIT", amount=1000)])
    yield book, config
    book.close()


def test_explicit_upgrade_backs_up_preserves_facts_and_reopens(workspace):
    book, config = workspace
    assert book.connection.execute("SELECT version FROM schema_version").fetchone()[0] == 2
    result = enable_workbench(book, config)
    assert result["schema_version"] == 3
    previous = verify_bundle(Path(result["backup"]), "demo")
    assert previous["database"]["version"] == 2
    assert previous["database"]["table_counts"]["events"] == 1
    assert book.snapshot("sample", "2024-07-02T00:00:00Z")["settled_cash"] == "1000"
    again = Ledger(book.path, "demo")
    try:
        assert again.schema_info["version"] == 3
        assert enable_workbench(again, config)["backup"] is None
    finally:
        again.close()


def test_versions_freeze_parameters_allow_clones_and_rename(workspace):
    book, config = workspace; enable_workbench(book, config)
    store = StrategyStore(book)
    spec = StrategySpec.create("momentum_rotation", ["SPY", "IEF"])
    first = store.publish(spec)
    assert store.publish(spec).spec_hash == first.spec_hash
    assert len(store.list()) == 1
    clone = spec.content(); clone["strategy_id"] = "my_clone"
    store.publish(StrategySpec.from_dict(clone))
    assert len(store.list()) == 2
    store.rename("momentum_rotation", 1, "新的展示名")
    assert store.get("momentum_rotation", 1).spec_hash == first.spec_hash
    change = spec.content(); change["parameters"]["lookback"] = 63
    with pytest.raises(QuantError, match="冻结"):
        store.publish(StrategySpec.from_dict(change))
    change["revision"] = 2
    assert store.publish(StrategySpec.from_dict(change)).spec_hash != first.spec_hash


def test_partial_schema_failure_rolls_back_and_retains_backup(workspace, monkeypatch):
    book, config = workspace
    def fail(connection):
        connection.execute("CREATE TABLE broken_step(id INTEGER)")
        connection.execute("UPDATE schema_version SET version=3")
        raise RuntimeError("injected failure")
    monkeypatch.setattr("personal_quant.strategies.store.apply_workbench_schema", fail)
    with pytest.raises(RuntimeError, match="injected"):
        enable_workbench(book, config)
    assert book.connection.execute("SELECT version FROM schema_version").fetchone()[0] == 2
    assert book.connection.execute("SELECT name FROM sqlite_master WHERE name='broken_step'").fetchone() is None
    bundles = list(Path("reports/v15-migrations").glob("*/manifest.json"))
    assert len(bundles) == 1
    assert verify_bundle(bundles[0].parent, "demo")["database"]["table_counts"]["events"] == 1
