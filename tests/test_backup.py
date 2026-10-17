import hashlib
import json
from pathlib import Path
import shutil
import sqlite3

import pandas as pd
import pytest

from personal_quant.cli import main
from personal_quant.common import QuantError, decimal as D, digest, write_json
from personal_quant.config import Config
from personal_quant.data.calendar import Calendar
from personal_quant.data.fixture import create_fixture
from personal_quant.data.store import DataStore
from personal_quant.execution.daily import DailyRunner, daily_lock
from personal_quant.execution.plans import PlanService
from personal_quant.portfolio import Ledger
from personal_quant.portfolio.backup import create_bundle, restore_bundle, verify_bundle
from personal_quant.portfolio.imports import event_csv
from personal_quant.portfolio.report import load_account_report, report_from_store
from personal_quant.strategies.archive import SignalArchive
from conftest import event

REPO = Path(__file__).resolve().parents[1]
AS_OF = "2024-07-31T21:00:00Z"


def scenario(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config_path = Path("local.toml")
    config_path.write_bytes((REPO / "configs/demo.toml").read_bytes())
    config = Config.load(config_path)
    root = Path(config.runtime_dir)
    prices, sessions = create_fixture(root / "fixtures")
    store = DataStore(root / "data")
    calendar = Calendar.csv(sessions, "synthetic_test_sessions")
    store.save(pd.read_csv(prices), calendar)
    frame, metadata, calendar = store.load()
    book = Ledger(root / "account.sqlite", "demo")
    book.account("sample")
    archived = SignalArchive(book).generate(frame, metadata, calendar, config, "2024-07-31")
    rows = event_csv((REPO / "examples/test_statement.csv").read_bytes())
    book.import_events("sample", rows)
    store.save(pd.read_csv(REPO / "examples/statement_prices.csv"), calendar)
    report_from_store(book, "sample", AS_OF, store, config, root / "reports/account-latest")
    book.close()
    return root, config_path, archived, rows


def rewrite_manifest(bundle):
    path = bundle / "manifest.json"
    manifest = json.loads(path.read_text())
    for name, item in list(manifest["files"].items()):
        file = bundle / name
        if file.exists():
            item.update(sha256=hashlib.sha256(file.read_bytes()).hexdigest(), bytes=file.stat().st_size)
        else:
            manifest["files"].pop(name)
    manifest["manifest_hash"] = digest({k: v for k, v in manifest.items() if k != "manifest_hash"})
    write_json(path, manifest)


def test_complete_bundle_restores_independent_statement_and_referenced_history(tmp_path, monkeypatch):
    root, config, archived, rows = scenario(tmp_path, monkeypatch)
    bundle, restored = tmp_path / "backup", tmp_path / "recovered"
    original = (root / "account.sqlite").read_bytes()
    created = create_bundle(root, config, bundle)
    assert created["database"]["table_counts"]["events"] == 5
    assert (root / "account.sqlite").read_bytes() == original
    verified = verify_bundle(bundle, "demo")
    assert len(verified["references"]["snapshots"]) == 2
    assert archived["data"]["snapshot_id"] in verified["references"]["referenced_snapshots"]
    restore_bundle(bundle, restored, "demo")
    assert (restored / "configs/recovered.toml").read_bytes() == config.read_bytes()
    book = Ledger(restored / root / "account.sqlite", "demo")
    try:
        result = book.snapshot("sample", AS_OF, {"SPY": "49.5"})
        # Expected from the independent statement, not from the backup summary.
        assert D(result["settled_cash"]) == D("503.5")
        assert D(result["positions"]["SPY"]) == 10
        assert D(result["equity"]) == D("998.5")
        assert D(result["net_contributions"]) == 1000
        assert SignalArchive(book).get(archived["archive_id"]) == archived
        assert book.import_events("sample", rows)["added"] == 0
        assert book.sequence("sample") == 5
    finally:
        book.close()
    report = load_account_report(restored / root / "reports/account-latest")
    assert D(report["equity"]) == D("998.5")
    assert (root / "account.sqlite").read_bytes() == original


def test_partial_plan_manual_reserves_and_task_retry_survive_restore(tmp_path, monkeypatch):
    root, path, _, _ = scenario(tmp_path, monkeypatch)
    # A separate workspace provides the manually calculable plan scenario.
    workspace = tmp_path / "plan"
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    raw = path.resolve() if path.is_absolute() else tmp_path / path
    text = raw.read_text().replace('symbols = ["SPY", "IEF", "GLD"]', 'symbols = ["SPY"]')
    text = text.replace('weights = [0.3333333333333333, 0.3333333333333333, 0.3333333333333334]', 'weights = [1.0]')
    for old, new in [('active_strategy = "trend"', 'active_strategy = "fixed"'), ('max_weight = 0.60', 'max_weight = 1.0'),
                     ('commission_bps = 2.0', 'commission_bps = 0.0'), ('slippage_bps = 5.0', 'slippage_bps = 0.0'),
                     ('cash_buffer = 0.01', 'cash_buffer = 0.0')]:
        text = text.replace(old, new)
    Path("local.toml").write_text(text)
    config = Config.load("local.toml")
    prices, sessions = create_fixture(root / "fixtures")
    calendar = Calendar.csv(sessions, "synthetic_test_sessions")
    frame = pd.read_csv(prices)
    frame[["open", "high", "low", "close", "adj_close"]] = 100.0
    store = DataStore(root / "data")
    store.save(frame, calendar)
    book = Ledger(root / "account.sqlite", "demo")
    book.account("sample")
    book.import_events("sample", [event("opening", "DEPOSIT", amount=1000)])
    expected = {"account_id": "sample", "currency": "USD", "as_of": AS_OF,
                "cash_basis": "settled", "cash": 1000, "positions": {}, "source": "independent_fixture"}
    first = DailyRunner(book, config, store).run("sample", as_of=AS_OF, reconciliation=expected)
    plan_id = first["planning"]["plan_id"]
    service = PlanService(book, config)
    service.manual_pending(plan_id, True, AS_OF)
    fill = event("fill", "BUY", symbol="SPY", quantity=4, price=100, fee=0,
                 plan_id=plan_id, effective_at="2024-08-01T20:00:00Z", settlement_at="2024-08-02T20:00:00Z")
    book.import_events("sample", [fill])
    assert service.get(plan_id)["execution_status"] == "PARTIAL"
    book.close()
    bundle, restored = tmp_path / "plan-backup", tmp_path / "plan-restored"
    create_bundle(root, Path("local.toml"), bundle)
    restore_bundle(bundle, restored, "demo")
    monkeypatch.chdir(restored)
    cfg = Config.load("configs/recovered.toml")
    book = Ledger(Path(cfg.runtime_dir) / "account.sqlite", "demo")
    try:
        recovered_plan = PlanService(book, cfg).get(plan_id)
        assert recovered_plan["execution_status"] == "PARTIAL" and recovered_plan["manual_pending"]
        snap = book.snapshot("sample", "2024-08-03T21:00:00Z", {"SPY": 100})
        assert D(snap["settled_cash"]) == 600 and D(snap["positions"]["SPY"]) == 4
        assert D(snap["reserved_cash"]) == 600 and D(snap["equity"]) == 1000
        assert book.import_events("sample", [fill])["added"] == 0
        retry = DailyRunner(book, cfg, DataStore(Path(cfg.runtime_dir) / "data")).run("sample", as_of=AS_OF, reconciliation=expected)
        assert retry["planning"]["plan_id"] == plan_id
        assert book.sequence("sample") == 2
        assert book.connection.execute("SELECT count(*) FROM plans").fetchone()[0] == 1
    finally:
        book.close()


@pytest.mark.parametrize("damage", ["missing", "content", "extra", "link"])
def test_damaged_or_unsafe_bundle_never_publishes_restore(tmp_path, monkeypatch, damage):
    root, config, _, _ = scenario(tmp_path, monkeypatch)
    bundle, restored = tmp_path / "backup", tmp_path / "recovered"
    create_bundle(root, config, bundle)
    file = bundle / "configs/recovered.toml"
    if damage == "missing":
        file.unlink()
    elif damage == "content":
        file.write_text(file.read_text() + "# changed\n")
    elif damage == "extra":
        (bundle / "unexpected").write_text("not listed")
    else:
        file.unlink()
        file.symlink_to(tmp_path / config)
    with pytest.raises(QuantError):
        restore_bundle(bundle, restored, "demo")
    assert not restored.exists() and not list(tmp_path.glob(".pending-restore-*"))


def test_hash_valid_bundle_with_missing_archived_snapshot_is_rejected(tmp_path, monkeypatch):
    root, config, archived, _ = scenario(tmp_path, monkeypatch)
    bundle = tmp_path / "backup"
    create_bundle(root, config, bundle)
    shutil.rmtree(bundle / root / "data" / archived["data"]["snapshot_id"])
    rewrite_manifest(bundle)
    with pytest.raises(QuantError) as exc:
        restore_bundle(bundle, tmp_path / "recovered", "demo")
    assert exc.value.code == "MISSING_BACKUP_REFERENCE"


def test_explicit_environment_no_overwrite_and_safe_manifest_paths(tmp_path, monkeypatch):
    root, config, _, _ = scenario(tmp_path, monkeypatch)
    bundle, occupied = tmp_path / "backup", tmp_path / "occupied"
    create_bundle(root, config, bundle)
    occupied.mkdir()
    sentinel = occupied / "account.sqlite"
    sentinel.write_bytes(b"user-owned account")
    for source, dest, env, code in [(bundle, occupied, "demo", "NONEMPTY_DESTINATION"),
                                    (bundle, tmp_path / "real", "real", "ENVIRONMENT_MISMATCH")]:
        with pytest.raises(QuantError) as exc:
            restore_bundle(source, dest, env)
        assert exc.value.code == code
    assert sentinel.read_bytes() == b"user-owned account"
    manifest = json.loads((bundle / "manifest.json").read_text())
    manifest["files"]["../../escape"] = {"sha256": "0" * 64, "bytes": 0}
    manifest["manifest_hash"] = digest({k: v for k, v in manifest.items() if k != "manifest_hash"})
    write_json(bundle / "manifest.json", manifest)
    with pytest.raises(QuantError) as exc:
        restore_bundle(bundle, tmp_path / "recovered", "demo")
    assert exc.value.code == "INVALID_BACKUP_PATH" and not (tmp_path / "escape").exists()


def test_future_database_does_not_mutate_source_even_on_cli_failure(tmp_path, monkeypatch, capsys):
    root, config, _, _ = scenario(tmp_path, monkeypatch)
    with sqlite3.connect(root / "account.sqlite") as db:
        db.execute("UPDATE schema_version SET version=99")
    original = (root / "account.sqlite").read_bytes()
    assert main(["--config", str(config), "backup-bundle", "--destination", str(tmp_path / "backup")]) == 2
    assert json.loads(capsys.readouterr().err)["code"] == "NEWER_DATABASE_SCHEMA"
    assert (root / "account.sqlite").read_bytes() == original
    assert not (tmp_path / "backup").exists()


def test_competing_daily_and_concurrent_account_write_do_not_publish_bundle(tmp_path, monkeypatch):
    root, config, _, _ = scenario(tmp_path, monkeypatch)
    bundle = tmp_path / "backup"
    with daily_lock(root / ".daily.lock"):
        with pytest.raises(QuantError) as exc:
            create_bundle(root, config, bundle)
        assert exc.value.code == "DAILY_ALREADY_RUNNING"
    copyfile = shutil.copyfile
    changed = False
    def concurrent_write(source, destination):
        nonlocal changed
        if not changed:
            changed = True
            book = Ledger(root / "account.sqlite", "demo")
            book.import_events("sample", [event("concurrent", "DEPOSIT", amount=20)])
            book.close()
        return copyfile(source, destination)
    monkeypatch.setattr(shutil, "copyfile", concurrent_write)
    with pytest.raises(QuantError) as exc:
        create_bundle(root, config, bundle)
    assert exc.value.code == "BACKUP_SOURCE_CHANGED"
    assert not bundle.exists() and not list(tmp_path.glob(".pending-backup-*"))


def test_recovery_cli_needs_no_source_worktree_config_or_implicit_database(tmp_path, monkeypatch, capsys):
    root, config, _, _ = scenario(tmp_path, monkeypatch)
    bundle = tmp_path / "backup"
    assert main(["--config", str(config), "backup-bundle", "--destination", str(bundle)]) == 0
    capsys.readouterr()
    working = tmp_path / "unrelated"
    working.mkdir()
    monkeypatch.chdir(working)
    assert main(["verify-backup", "--source", str(bundle), "--environment", "demo"]) == 0
    assert main(["restore", "--source", str(bundle), "--destination", str(tmp_path / "recovered"), "--environment", "demo"]) == 0
    assert not (working / "runtime").exists()


def test_backup_closes_sqlite_copy_before_publishing_directory(tmp_path, monkeypatch):
    root, config, _, _ = scenario(tmp_path, monkeypatch)
    import personal_quant.portfolio.backup as module
    connect, rename = sqlite3.connect, module.os.rename
    copies = []
    def record_connection(database, *args, **kwargs):
        connection = connect(database, *args, **kwargs)
        if ".pending-backup-" in str(database) and not kwargs.get("uri"):
            copies.append(connection)
        return connection
    def publish(source, destination):
        assert copies
        for connection in copies:
            with pytest.raises(sqlite3.ProgrammingError, match="closed"):
                connection.execute("SELECT 1")
        return rename(source, destination)
    monkeypatch.setattr(sqlite3, "connect", record_connection)
    monkeypatch.setattr(module.os, "rename", publish)
    create_bundle(root, config, tmp_path / "backup")


def test_supplier_cache_and_unpublished_price_files_are_not_snapshots(tmp_path, monkeypatch):
    root, config, _, _ = scenario(tmp_path, monkeypatch)
    cache = root / "data/provider-cache"
    cache.mkdir(); (cache / "quotes.sqlite").write_bytes(b"discardable supplier cache")
    pending = root / "data/.pending-interrupted-download"
    pending.mkdir(); (pending / "prices.parquet").write_bytes(b"incomplete")
    create_bundle(root, config, tmp_path / "backup")
    manifest = verify_bundle(tmp_path / "backup", "demo")
    assert not any("provider-cache" in name or ".pending-" in name for name in manifest["files"])
    assert len(manifest["references"]["snapshots"]) == 2
