"""Reproduce independent accounting and account replay in fresh, isolated directories."""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

REPO = Path(__file__).resolve().parents[1]
WRITABLE_ALIAS = Path('/mnt/c/quant/project/lyra')
if WRITABLE_ALIAS.is_dir() and WRITABLE_ALIAS.samefile(REPO):
    REPO = WRITABLE_ALIAS
sys.path.insert(0, str(REPO / "src"))

from personal_quant.cli import main
from personal_quant.common import decimal as D, now_utc, write_json
from personal_quant.portfolio import Ledger
from personal_quant.strategies.archive import SignalArchive, source_fingerprint
from personal_quant.data.fixture import create_lifecycle_fixture
from personal_quant.portfolio.report import load_account_report


def verify():
    original = Path.cwd()
    root = REPO / "reports" / "offline-validation" / uuid4().hex
    root.mkdir(parents=True)
    records = []
    config = str(REPO / "configs/demo.toml")

    def run(*args, expected_exit=0):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--config", config, *args])
        result = json.loads(out.getvalue() or err.getvalue())
        records.append({"command": list(args), "config": config, "exit_code": code, "working_directory": str(Path.cwd()), "result": result})
        if code != expected_exit:
            raise AssertionError(f"{args[0]} returned {code}: {result}")
        return result

    try:
        sample = root / "statement"
        sample.mkdir()
        os.chdir(sample)
        run("fixture")
        signals = run("signals")
        repeated_signals = run("signals")
        assert signals["archive_ids"] == repeated_signals["archive_ids"]
        assert signals["counts"] == {"fixed": 6, "trend": 6}
        listed = run("list-signals", "--limit", "1", "--mode", "historical_reconstruction")
        assert len(listed["signals"]) == 1
        run("import-prices", "--file", str(REPO / "examples/statement_prices.csv"), "--calendar",
            "runtime/demo/fixtures/calendar.csv", "--calendar-kind", "synthetic_test_sessions")
        run("account", "--account-id", "sample")
        statement = str(REPO / "examples/test_statement.csv")
        preview = run("import-events", "--account-id", "sample", "--file", statement,
                      "--as-of", "2024-07-31T21:00:00Z")
        run("import-events", "--account-id", "sample", "--file", statement, "--commit",
            "--expected-sequence", str(preview["expected_sequence"]), "--expected-hash", preview["batch_hash"])
        run("reconcile", "--account-id", "sample", "--file", str(REPO / "examples/test_snapshot.csv"))
        report = run("report", "--account-id", "sample", "--as-of", "2024-07-31T21:00:00Z")
        # Independent expected amounts: 1000-500-1.5+5=503.5, 5*2=10,
        # equity 503.5+10*49.5=998.5. Deposits remain 1000.
        assert D(report["settled_cash"]) == D("503.5")
        assert D(report["positions"]["SPY"]) == 10
        assert D(report["equity"]) == D("998.5")
        assert D(report["investment_pnl"]) == D("-1.5")
        preview = run("import-events", "--account-id", "sample", "--file", statement)
        repeated = run("import-events", "--account-id", "sample", "--file", statement, "--commit",
                       "--expected-sequence", str(preview["expected_sequence"]), "--expected-hash", preview["batch_hash"])
        assert repeated["added"] == 0 and repeated["duplicates"] == 5
        run("backup", "--destination", str(root / "backup.sqlite"))
        restored = Ledger(root / "backup.sqlite", "demo")
        try:
            snap = restored.snapshot("sample", "2024-07-31T21:00:00Z", {"SPY": "49.5"})
            assert D(snap["settled_cash"]) == D("503.5") and D(snap["equity"]) == D("998.5")
            assert len(SignalArchive(restored).list()) == 12
        finally:
            restored.close()

        replay = root / "replay"
        replay.mkdir()
        os.chdir(replay)
        first = run("demo-account")
        assert first["blocked_batches"] == 0
        curve_path = Path("runtime/demo/reports/account-demo/account_curve.csv")
        before = curve_path.read_bytes()
        book = Ledger(Path("runtime/demo/account.sqlite"), "demo")
        count = book.sequence("demo-account")
        trades = book.connection.execute("SELECT count(*) FROM events WHERE json_extract(payload,'$.kind') IN ('BUY','SELL')").fetchone()[0]
        book.close()
        run("demo-account")
        book = Ledger(Path("runtime/demo/account.sqlite"), "demo")
        assert book.sequence("demo-account") == count
        book.close()
        assert trades > 0 and curve_path.read_bytes() == before
        run("status")
        lifecycle_root = root / "lifecycle"
        lifecycle_root.mkdir()
        os.chdir(lifecycle_root)
        config = str(REPO / "configs/lifecycle.toml")
        full = run("demo-lifecycle")
        lifecycle_curve = Path(full["report"]) / "account_curve.csv"
        before_lifecycle = lifecycle_curve.read_bytes()
        repeated_lifecycle = run("demo-lifecycle")
        assert full["ledger_seq"] == repeated_lifecycle["ledger_seq"] == 9
        assert before_lifecycle == lifecycle_curve.read_bytes()
        daily_root = root / "daily"
        daily_root.mkdir()
        os.chdir(daily_root)
        daily_prices, daily_calendar = create_lifecycle_fixture(Path("daily-fixture"))
        run("import-prices", "--file", str(daily_prices), "--calendar", str(daily_calendar), "--calendar-kind", "synthetic_test_sessions")
        run("account", "--account-id", "daily-account")
        opening = Path("opening.csv")
        opening.write_text("event_id,kind,amount,effective_at,source,evidence_type\n"
                           "daily:opening,DEPOSIT,1000,2024-07-01T20:00:00Z,independent_daily_fixture,test\n")
        opening_snapshot = Path("opening-snapshot.json")
        write_json(opening_snapshot, {"account_id": "daily-account", "currency": "USD", "as_of": "2024-07-31T21:00:00Z",
                   "cash_basis": "settled", "cash": 1000, "positions": {}, "source": "independent_daily_fixture"})
        review = run("import-events", "--account-id", "daily-account", "--file", str(opening), "--as-of", "2024-07-31T21:00:00Z")
        daily_initial = run("daily", "--account-id", "daily-account", "--as-of", "2024-07-31T21:00:00Z",
                            "--events", str(opening), "--expected-sequence", str(review["expected_sequence"]),
                            "--expected-hash", review["batch_hash"], "--reconciliation", str(opening_snapshot))
        assert daily_initial["status"] == "SUCCESS"
        assert D(daily_initial["equity"]) == 1000 and daily_initial["ledger_seq"] == 1
        executed = run("daily", "--account-id", "daily-account", "--as-of", "2024-08-01T21:00:00Z")
        assert executed["status"] == "SUCCESS" and executed["ledger_seq"] == 3
        settled_snapshot = Path("settled-snapshot.json")
        write_json(settled_snapshot, {"account_id": "daily-account", "currency": "USD", "as_of": "2024-08-02T21:00:00Z",
                   "cash_basis": "settled", "cash": 0, "positions": {"SPY": 5, "IEF": 10}, "equity": 1000,
                   "source": "independent_daily_fixture"})
        settled = run("daily", "--account-id", "daily-account", "--as-of", "2024-08-02T21:00:00Z",
                      "--reconciliation", str(settled_snapshot))
        repeated_daily = run("daily", "--account-id", "daily-account", "--as-of", "2024-08-02T21:00:00Z",
                             "--reconciliation", str(settled_snapshot))
        assert repeated_daily["ledger_seq"] == settled["ledger_seq"] == 3
        assert repeated_daily["report_id"] == settled["report_id"]
        daily_report = load_account_report(Path("runtime/demo/reports/account-latest"))
        assert D(daily_report["settled_cash"]) == 0 and D(daily_report["equity"]) == 1000
        assert {s: D(q) for s, q in daily_report["positions"].items()} == {"SPY": D(5), "IEF": D(10)}
        run("status")
        bundle = root / "daily-backup"
        backup = run("backup-bundle", "--destination", str(bundle))
        run("verify-backup", "--source", str(bundle), "--environment", "demo")
        recovery_root = root / "daily-restored"
        restored = run("restore", "--source", str(bundle), "--destination", str(recovery_root), "--environment", "demo")
        assert restored["database"]["logical_hash"] == backup["database"]["logical_hash"]
        os.chdir(recovery_root)
        config = str(recovery_root / "configs/recovered.toml")
        resumed = run("daily", "--account-id", "daily-account", "--as-of", "2024-08-02T21:00:00Z")
        assert resumed["ledger_seq"] == 3 and resumed["report_id"] == settled["report_id"]
        restored_report = load_account_report(Path("runtime/demo/reports/account-latest"))
        assert D(restored_report["settled_cash"]) == 0 and D(restored_report["equity"]) == 1000
        opening_path = str(daily_root / opening)
        review = run("import-events", "--account-id", "daily-account", "--file", opening_path)
        imported = run("import-events", "--account-id", "daily-account", "--file", opening_path, "--commit",
                       "--expected-sequence", str(review["expected_sequence"]), "--expected-hash", review["batch_hash"])
        assert imported["added"] == 0 and imported["duplicates"] == 1
        recovered_book = Ledger(Path("runtime/demo/account.sqlite"), "demo")
        try:
            assert recovered_book.sequence("daily-account") == 3
            assert len(SignalArchive(recovered_book).list()) == 1
        finally:
            recovered_book.close()
        summary = {"status": "PASSED_OFFLINE_ACCOUNTING", "generated_at": now_utc(),
                   "synthetic_only": True, "not_bt_acceptance": True, "not_online_acceptance": True,
                   "not_ui_acceptance": True, "root": str(root), "events": count, "nonzero_trades": trades,
                   "account_report": str(replay / "runtime/demo/reports/account-demo/account.md"),
                   "manual_report": str(sample / "runtime/demo/reports/account-latest/account.md"),
                   "lifecycle_report": str(lifecycle_root / full["report"] / "account.md"),
                   "lifecycle_checkpoints": len(full["checkpoints"]),
                   "daily_report": str(daily_root / "runtime/demo/reports/account-latest/account.md"),
                   "daily_checkpoints": 3, "daily_events": settled["ledger_seq"],
                   "complete_backup": str(bundle), "restored_workspace": str(recovery_root),
                   "restored_config": config, "restored_events": 3,
                   "restored_report": str(recovery_root / "runtime/demo/reports/account-latest/account.md"),
                   "historical_signal_archives": len(signals["archive_ids"]), "not_forward_acceptance": True,
                   "source_hash": source_fingerprint(),
                   "records": records}
        write_json(root / "verification.json", summary)
        write_json(root.parent / "latest.json", {"root": str(root), "status": summary["status"]})
        print(json.dumps({k: v for k, v in summary.items() if k != "records"}, ensure_ascii=False, indent=2))
        return 0
    finally:
        os.chdir(original)


if __name__ == "__main__":
    raise SystemExit(verify())
