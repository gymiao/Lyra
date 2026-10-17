from dataclasses import replace
from pathlib import Path

import pytest

from personal_quant.common import QuantError, decimal as D, digest
from personal_quant.config import Config
from personal_quant.execution.daily import DailyRunner, daily_lock
from personal_quant.portfolio import Ledger
from personal_quant.portfolio.report import load_account_report
from conftest import event

MONTH_END = "2024-07-31T21:00:00Z"
EXECUTION_DAY = "2024-08-01T21:00:00Z"


def scenario(ledger, market, config, tmp_path, monkeypatch, *, deposit=True):
    monkeypatch.chdir(tmp_path)
    store, frame, _, calendar = market
    frame = frame.copy()
    frame[["open", "high", "low", "close", "adj_close"]] = 100.0
    store.save(frame, calendar)
    cfg = replace(config, symbols=("SPY",), weights=(1,), active_strategy="fixed", max_weight=1,
                  commission_bps=0, slippage_bps=0, fixed_fee=0, cash_buffer=0)
    if deposit:
        ledger.import_events("sample", [event("initial", "DEPOSIT", amount=1000)])
    expected = {"account_id": "sample", "currency": "USD", "as_of": MONTH_END,
                "cash_basis": "settled", "cash": 1000, "positions": {}, "source": "independent_manual_fixture"}
    return cfg, store, frame, calendar, expected


def test_missing_monthly_records_are_reported_without_backfilled_signal_or_trade(ledger, market, config, tmp_path, monkeypatch):
    cfg, store, _, _, _ = scenario(ledger, market, config, tmp_path, monkeypatch)
    runner = DailyRunner(ledger, cfg, store)
    first = runner.run("sample", as_of="2024-07-15T21:00:00Z")
    assert first["tracking_gaps"]["months"] == []
    after_gap = runner.run("sample", as_of="2024-09-03T21:00:00Z")
    gaps = after_gap["tracking_gaps"]
    assert gaps["status"] == "WARNING"
    assert [item["decision_session"] for item in gaps["months"]] == ["2024-07-31", "2024-08-30"]
    assert all(item["state"] == "NO_ARCHIVED_SIGNAL" for item in gaps["months"])
    assert gaps["tracking_start"] == "2024-07-15"
    assert ledger.sequence("sample") == 1
    assert ledger.connection.execute("SELECT count(*) FROM strategy_signals").fetchone()[0] == 0
    assert ledger.connection.execute("SELECT count(*) FROM plans").fetchone()[0] == 0
    retried = runner.run("sample", as_of="2024-09-03T21:00:00Z")
    assert retried["tracking_gaps"] == gaps
    assert ledger.sequence("sample") == 1


def test_existing_monthly_plan_is_not_mislabeled_as_lost_task(ledger, market, config, tmp_path, monkeypatch):
    cfg, store, _, _, expected = scenario(ledger, market, config, tmp_path, monkeypatch)
    runner = DailyRunner(ledger, cfg, store)
    created = runner.run("sample", as_of=MONTH_END, reconciliation=expected)
    assert created["tracking_gaps"]["months"] == []  # Execution is still in the future.
    executed = runner.run("sample", as_of=EXECUTION_DAY)
    assert executed["tracking_gaps"]["months"] == []
    assert executed["ledger_seq"] == 2


def test_archived_but_blocked_month_is_distinguished_from_missing_signal(ledger, market, config, tmp_path, monkeypatch):
    cfg, store, _, _, _ = scenario(ledger, market, config, tmp_path, monkeypatch)
    runner = DailyRunner(ledger, cfg, store)
    created = runner.run("sample", as_of=MONTH_END)  # No independent reconciliation.
    assert created["status"] == "BLOCKED"
    later = runner.run("sample", as_of="2024-08-02T21:00:00Z")
    month = later["tracking_gaps"]["months"][0]
    assert month["state"] == "PLAN_BLOCKED"
    states = ledger.connection.execute("SELECT intent_id,execution_status,check_status FROM plans").fetchall()
    assert len({row["intent_id"] for row in states}) == 1
    assert all(row["execution_status"] not in {"READY", "PARTIAL"} and row["check_status"] == "BLOCKED" for row in states)
    assert ledger.sequence("sample") == 1
    assert ledger.connection.execute("SELECT count(*) FROM strategy_signals").fetchone()[0] == 1


def test_month_end_plan_next_day_fill_and_repeat_are_idempotent(ledger, market, config, tmp_path, monkeypatch):
    cfg, store, _, _, expected = scenario(ledger, market, config, tmp_path, monkeypatch)
    first = DailyRunner(ledger, cfg, store).run("sample", as_of=MONTH_END, reconciliation=expected)
    assert first["status"] == "SUCCESS", first
    plan_id = first["planning"]["plan_id"]
    second = DailyRunner(ledger, cfg, store).run("sample", as_of=EXECUTION_DAY)
    assert second["status"] == "SUCCESS", second
    assert second["planning"]["code"] == "NOT_REBALANCE_DAY"
    assert second["account_facts"]["completed"][0]["plan_id"] == plan_id
    assert ledger.sequence("sample") == 2
    snapshot = ledger.snapshot("sample", "2024-08-02T21:00:00Z", {"SPY": 100})
    assert D(snapshot["positions"]["SPY"]) == 10
    assert D(snapshot["settled_cash"]) == 0 and D(snapshot["equity"]) == 1000
    repeated = DailyRunner(ledger, cfg, store).run("sample", as_of=EXECUTION_DAY)
    assert repeated["run_id"] == second["run_id"]
    assert repeated["attempt_id"] != second["attempt_id"]
    assert repeated["report_id"] == second["report_id"]
    assert ledger.sequence("sample") == 2
    assert ledger.connection.execute("SELECT count(*) FROM plans").fetchone()[0] == 1


def test_import_commit_boundary_resume_reuses_exact_batch(ledger, market, config, tmp_path, monkeypatch):
    cfg, store, _, _, expected = scenario(ledger, market, config, tmp_path, monkeypatch, deposit=False)
    rows = [event("initial", "DEPOSIT", amount=1000)]
    def interrupt(name, result):
        if name == "import":
            raise RuntimeError("injected process stop after commit")
    with pytest.raises(RuntimeError):
        DailyRunner(ledger, cfg, store, after_step=interrupt).run("sample", as_of=MONTH_END, events=rows,
            expected_sequence=0, expected_hash=digest(rows), reconciliation=expected)
    assert ledger.sequence("sample") == 1
    resumed = DailyRunner(ledger, cfg, store).run("sample", as_of=MONTH_END, events=rows,
        expected_sequence=0, expected_hash=digest(rows), reconciliation=expected)
    assert resumed["status"] == "SUCCESS"
    assert next(step for step in resumed["steps"] if step["name"] == "import")["reused"]
    assert ledger.connection.execute("SELECT count(*) FROM imports").fetchone()[0] == 1
    assert ledger.sequence("sample") == 1


def test_report_failure_resume_keeps_committed_fill_once(ledger, market, config, tmp_path, monkeypatch):
    cfg, store, _, _, expected = scenario(ledger, market, config, tmp_path, monkeypatch)
    DailyRunner(ledger, cfg, store).run("sample", as_of=MONTH_END, reconciliation=expected)
    import personal_quant.execution.daily as module
    original = module.report_from_store
    def fail(*args, **kwargs):
        raise OSError("injected report publication failure")
    monkeypatch.setattr(module, "report_from_store", fail)
    with pytest.raises(OSError):
        DailyRunner(ledger, cfg, store).run("sample", as_of=EXECUTION_DAY)
    assert ledger.sequence("sample") == 2
    monkeypatch.setattr(module, "report_from_store", original)
    result = DailyRunner(ledger, cfg, store).run("sample", as_of=EXECUTION_DAY)
    assert result["status"] == "SUCCESS", result
    assert ledger.sequence("sample") == 2
    report = load_account_report(Path(cfg.runtime_dir) / "reports/account-latest")
    assert D(report["equity"]) == 1000
    assert ledger.connection.execute("SELECT count(*) FROM daily_attempts WHERE status='FAILED'").fetchone()[0] == 1


def test_non_rebalance_day_and_missing_month_end_price_do_not_make_plan(ledger, market, config, tmp_path, monkeypatch):
    cfg, store, frame, calendar, expected = scenario(ledger, market, config, tmp_path, monkeypatch)
    normal = DailyRunner(ledger, cfg, store).run("sample", as_of="2024-07-15T21:00:00Z")
    assert normal["status"] == "SUCCESS"
    assert normal["planning"]["code"] == "NOT_REBALANCE_DAY"
    assert ledger.connection.execute("SELECT count(*) FROM plans").fetchone()[0] == 0
    missing = frame.loc[~((frame.symbol == "SPY") & (frame.session_date == "2024-07-31"))]
    store.save(missing, calendar)
    blocked = DailyRunner(ledger, cfg, store).run("sample", as_of=MONTH_END, reconciliation=expected)
    assert blocked["status"] == "BLOCKED"
    assert blocked["planning"]["code"] == "INVALID_SIGNAL"
    assert ledger.connection.execute("SELECT count(*) FROM plans").fetchone()[0] == 0


def test_late_processing_interleaves_buy_dividend_and_split_without_double_assets(ledger, market, config, tmp_path, monkeypatch):
    cfg, store, frame, calendar, expected = scenario(ledger, market, config, tmp_path, monkeypatch)
    DailyRunner(ledger, cfg, store).run("sample", as_of=MONTH_END, reconciliation=expected)
    frame.loc[(frame.symbol == "SPY") & (frame.session_date >= "2024-08-05"), ["open", "high", "low", "close"]] = 99
    frame.loc[(frame.symbol == "SPY") & (frame.session_date >= "2024-08-09"), ["open", "high", "low", "close"]] = 49.5
    store.save(frame, calendar)
    actions = [
        {"action_id": "div", "kind": "CASH_DIVIDEND", "symbol": "SPY", "source": "late_fixture", "data_type": "synthetic",
         "effective_at": "2024-08-05T13:30:00Z", "available_at": "2024-08-02T20:30:00Z", "qualification_at": "2024-08-05T13:30:00Z",
         "payment_at": "2024-08-08T13:30:00Z", "amount_per_share": "1", "withholding_per_share": "0"},
        {"action_id": "split", "kind": "SPLIT", "symbol": "SPY", "source": "late_fixture", "data_type": "synthetic",
         "effective_at": "2024-08-09T13:30:00Z", "available_at": "2024-08-06T20:30:00Z", "ratio": "2"},
    ]
    as_of = "2024-08-12T21:00:00Z"
    result = DailyRunner(ledger, cfg, store).run("sample", as_of=as_of, actions=actions)
    assert result["status"] == "SUCCESS", result
    completion = result["account_facts"]["completed"][0]
    assert completion["late_processing"] is True
    assert completion["processing_as_of"] == "2024-08-12T21:00:00+00:00"
    assert completion["state_as_of"] == "2024-08-01T20:00:00+00:00"
    snapshot = ledger.snapshot("sample", as_of, {"SPY": "49.5"})
    assert D(snapshot["settled_cash"]) == 10 and D(snapshot["positions"]["SPY"]) == 20
    assert D(snapshot["equity"]) == 1000 and D(snapshot["investment_pnl"]) == 0
    count = ledger.sequence("sample")
    DailyRunner(ledger, cfg, store).run("sample", as_of=as_of, actions=actions)
    assert ledger.sequence("sample") == count == 5


def test_lock_rejects_overlap_and_is_reusable_after_owner_exits(tmp_path):
    path = tmp_path / ".daily.lock"
    with daily_lock(path):
        with pytest.raises(QuantError) as exc:
            with daily_lock(path):
                pass
        assert exc.value.code == "DAILY_ALREADY_RUNNING"
    with daily_lock(path):
        assert path.exists()


def test_real_empty_account_reports_zero_without_simulation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from personal_quant.data.store import DataStore
    cfg = Config.load(Path(__file__).resolve().parents[1] / "configs/real.example.toml")
    book = Ledger(tmp_path / "real.sqlite", "real")
    try:
        book.account("real")
        result = DailyRunner(book, cfg, DataStore(Path(cfg.runtime_dir) / "data")).run("real")
        assert result["status"] == "BLOCKED" and result["data"]["code"] == "NO_DATA"
        assert D(result["equity"]) == 0 and book.sequence("real") == 0
        assert result["account_facts"]["status"] == "NO_ACTION"
        with pytest.raises(QuantError) as exc:
            DailyRunner(book, cfg, DataStore(Path(cfg.runtime_dir) / "data")).run("real", as_of=MONTH_END)
        assert exc.value.code == "HISTORICAL_TIME_FORBIDDEN"
    finally:
        book.close()


def test_wait_for_complete_execution_bar_then_continue_frozen_plan(ledger, market, config, tmp_path, monkeypatch):
    cfg, store, _, _, expected = scenario(ledger, market, config, tmp_path, monkeypatch)
    first = DailyRunner(ledger, cfg, store).run("sample", as_of=MONTH_END, reconciliation=expected)
    waiting = DailyRunner(ledger, cfg, store).run("sample", as_of="2024-08-01T20:05:00Z")
    assert waiting["status"] == "WAITING" and ledger.sequence("sample") == 1
    assert waiting["planning"]["plan_id"] == first["planning"]["plan_id"]
    arrived = DailyRunner(ledger, cfg, store).run("sample", as_of="2024-08-01T20:35:00Z")
    assert arrived["status"] == "SUCCESS" and ledger.sequence("sample") == 2


def test_stale_import_preview_cannot_mix_duplicates_and_new_events(ledger, market, config, tmp_path, monkeypatch):
    cfg, store, _, _, _ = scenario(ledger, market, config, tmp_path, monkeypatch)
    rows = [event("initial", "DEPOSIT", amount=1000), event("unreviewed", "DEPOSIT", amount=500)]
    with pytest.raises(QuantError) as exc:
        DailyRunner(ledger, cfg, store).run("sample", as_of=MONTH_END, events=rows,
                                          expected_sequence=0, expected_hash=digest(rows))
    assert exc.value.code == "STALE_PREVIEW"
    assert ledger.sequence("sample") == 1
    assert D(ledger.snapshot("sample", MONTH_END)["settled_cash"]) == 1000


def test_missing_execution_bar_waits_without_moving_original_trade_date(ledger, market, config, tmp_path, monkeypatch):
    cfg, store, frame, calendar, expected = scenario(ledger, market, config, tmp_path, monkeypatch)
    first = DailyRunner(ledger, cfg, store).run("sample", as_of=MONTH_END, reconciliation=expected)
    store.save(frame.loc[frame.session_date != "2024-08-01"], calendar)
    missing = DailyRunner(ledger, cfg, store).run("sample", as_of=EXECUTION_DAY)
    assert missing["status"] == "WAITING"
    assert missing["planning"]["plan_id"] == first["planning"]["plan_id"]
    assert ledger.sequence("sample") == 1
    assert ledger.connection.execute("SELECT count(*) FROM plans").fetchone()[0] == 1
    store.save(frame, calendar)
    recovered = DailyRunner(ledger, cfg, store).run("sample", as_of="2024-08-02T21:00:00Z")
    assert recovered["status"] == "SUCCESS", recovered
    completion = recovered["account_facts"]["completed"][0]
    assert completion["execution_session"] == "2024-08-01"
    assert completion["processing_as_of"] == "2024-08-02T21:00:00+00:00"
    assert ledger.sequence("sample") == 2


def test_forward_plan_time_follows_actual_signal_generation_not_job_start(tmp_path, market, config, monkeypatch):
    # A constructed provider/calendar contract, not actual online evidence.
    from datetime import timedelta
    from personal_quant.common import utc
    from personal_quant.data.calendar import Calendar
    from personal_quant.portfolio.reconciliation import ReconciliationRules
    monkeypatch.chdir(tmp_path)
    current = [utc("2024-07-31T20:35:00Z")]
    def ticking_clock():
        current[0] += timedelta(milliseconds=1)
        return current[0].isoformat()
    for module in ("execution.daily", "execution.plans", "portfolio.ledger", "data.store", "strategies.archive", "strategies.monthly"):
        monkeypatch.setattr(f"personal_quant.{module}.now_utc", ticking_clock)
    store, original, _, original_calendar = market
    calendar = Calendar(original_calendar.schedule, "verified_market_sessions")
    frame = original.loc[original.session_date <= "2024-07-31"].copy()
    frame["data_type"], frame["source"] = "real_market", "offline_forward_contract_fixture"
    metadata = store.save(frame, calendar)
    cfg = replace(config, environment="paper", runtime_dir="runtime/paper", active_strategy="fixed")
    book = Ledger(tmp_path / "paper.sqlite", "paper")
    try:
        book.account("paper")
        book.import_events("paper", [event("simulation-capital", "DEPOSIT", amount=1000)])
        book.reconcile("paper", {"account_id": "paper", "currency": "USD", "as_of": "2024-07-31T20:36:00Z",
            "cash_basis": "settled", "cash": 1000, "positions": {}, "source": "independent_contract_fixture"},
            rules=ReconciliationRules.from_config(cfg))
        current[0] = utc("2024-07-31T20:40:00Z")
        result = DailyRunner(book, cfg, store).run("paper")
        assert result["status"] == "SUCCESS", result
        from personal_quant.execution.plans import PlanService
        plan = PlanService(book, cfg).get(result["planning"]["plan_id"])
        assert plan["execution_status"] == "READY"
        assert utc(plan["payload"]["as_of"]) >= utc(plan["payload"]["signal"]["generated_at"])
        assert utc(plan["payload"]["signal"]["decision_time"]) >= utc(metadata["acquired_at"])
        assert book.sequence("paper") == 1  # Advice never books a trade.
    finally:
        book.close()


def test_no_completed_source_data_is_normal_waiting_not_a_failed_job(ledger, market, config, tmp_path, monkeypatch):
    cfg, store, _, _, _ = scenario(ledger, market, config, tmp_path, monkeypatch)
    def unpublished(*args, **kwargs):
        raise QuantError("NO_COMPLETED_DATA", "source has only unpublished bars")
    monkeypatch.setattr("personal_quant.execution.daily.update_online", unpublished)
    result = DailyRunner(ledger, cfg, store).run("sample", as_of=MONTH_END, fetch_range=("2024-07-01", "2024-08-01"))
    assert result["status"] == "WAITING"
    assert ledger.sequence("sample") == 1
    assert ledger.connection.execute("SELECT count(*) FROM plans").fetchone()[0] == 0


def test_cli_unpublished_fetch_returns_waiting_and_zero_exit(tmp_path, monkeypatch, capsys):
    import json
    from personal_quant.cli import main
    monkeypatch.chdir(tmp_path)
    def unpublished(*args, **kwargs):
        raise QuantError("NO_COMPLETED_DATA", "source has only unpublished bars")
    monkeypatch.setattr("personal_quant.cli.update_online", unpublished)
    cfg_file = Path(__file__).resolve().parents[1] / "configs/demo.toml"
    assert main(["--config", str(cfg_file), "fetch", "--start", "2024-07-31", "--end", "2024-08-01"]) == 0
    output = capsys.readouterr()
    assert not output.err
    assert json.loads(output.out)["status"] == "WAITING"
