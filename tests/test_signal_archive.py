from dataclasses import replace
import json

import pandas as pd
import pytest

from personal_quant.common import QuantError
from personal_quant.data.calendar import Calendar
from personal_quant.execution.plans import PlanService
from personal_quant.portfolio import Ledger
from personal_quant.strategies import Signal, signal
from personal_quant.strategies.archive import SignalArchive


def set_time(monkeypatch, instant):
    monkeypatch.setattr("personal_quant.strategies.archive.now_utc", lambda: instant)
    monkeypatch.setattr("personal_quant.strategies.monthly.now_utc", lambda: instant)


def forward_fixture(tmp_path, market, config):
    """Offline contract fixture; does not prove online data/calendar acceptance."""
    store, original, _, synthetic_calendar = market
    calendar = Calendar(synthetic_calendar.schedule, "verified_market_sessions")
    frame = original.loc[original.session_date <= "2024-07-31"].copy()
    frame["data_type"] = "real_market"
    frame["source"] = "offline_forward_contract_fixture"
    metadata = store.save(frame, calendar)
    metadata["acquired_at"] = "2024-07-31T20:35:00Z"
    cfg = replace(config, environment="paper", runtime_dir="runtime/paper", active_strategy="fixed")
    book = Ledger(tmp_path / "paper.sqlite", "paper")
    return book, frame, metadata, calendar, cfg


def test_historical_archive_is_immutable_and_retry_preserves_generation(ledger, market, config, monkeypatch):
    store, frame, metadata, calendar = market
    set_time(monkeypatch, "2026-10-09T01:00:00Z")
    archive = SignalArchive(ledger)
    first = archive.generate(frame, metadata, calendar, config, "2024-07-31")
    set_time(monkeypatch, "2026-10-09T02:00:00Z")
    repeat = archive.generate(frame, metadata, calendar, config, "2024-07-31")
    assert repeat == first
    assert first["signal"]["generated_at"] == "2026-10-09T01:00:00Z"
    assert len(archive.list()) == 1
    revised = frame.copy()
    revised.loc[(revised.symbol == "SPY") & (revised.session_date == "2024-07-31"), "adj_close"] *= 0.5
    new_metadata = store.save(revised, calendar)
    newer = archive.generate(revised, new_metadata, calendar, config, "2024-07-31")
    assert newer["archive_id"] != first["archive_id"]
    assert archive.get(first["archive_id"]) == first
    assert len(archive.list()) == 2


def test_forward_actual_acquisition_and_first_time_are_frozen(tmp_path, market, config, monkeypatch):
    book, frame, metadata, calendar, cfg = forward_fixture(tmp_path, market, config)
    try:
        archive = SignalArchive(book)
        set_time(monkeypatch, "2024-07-31T20:40:00Z")
        first = archive.generate(frame, metadata, calendar, cfg, "2024-07-31")
        assert first["signal"]["research_mode"] == "forward"
        assert first["signal"]["decision_time"] == "2024-07-31T20:40:00+00:00"
        assert first["data"]["acquired_at"] == "2024-07-31T20:35:00Z"
        set_time(monkeypatch, "2024-07-31T21:10:00Z")
        assert archive.generate(frame, metadata, calendar, cfg, "2024-07-31") == first
        assert archive.require(Signal(**first["signal"])) == first
    finally:
        book.close()


@pytest.mark.parametrize("case,code", [("future_acquisition", "DATA_NOT_OBSERVED"),
    ("missed_close", "STALE_SIGNAL_DATA"), ("historical_clock", "HISTORICAL_TIME_FORBIDDEN"),
    ("synthetic", "ENVIRONMENT_MISMATCH")])
def test_invalid_forward_evidence_is_not_archived(tmp_path, market, config, monkeypatch, case, code):
    book, frame, metadata, calendar, cfg = forward_fixture(tmp_path, market, config)
    try:
        clock, kwargs = "2024-07-31T20:40:00Z", {}
        if case == "future_acquisition":
            metadata["acquired_at"] = "2024-07-31T21:00:00Z"
        elif case == "missed_close":
            clock = "2024-08-01T20:40:00Z"
        elif case == "historical_clock":
            kwargs["decision_time"] = "2024-07-31T20:40:00Z"
        else:
            frame["data_type"] = "synthetic"
        set_time(monkeypatch, clock)
        with pytest.raises(QuantError) as failure:
            SignalArchive(book).generate(frame, metadata, calendar, cfg, "2024-07-31", **kwargs)
        assert failure.value.code == code
        assert book.connection.execute("SELECT count(*) FROM strategy_signals").fetchone()[0] == 0
    finally:
        book.close()


def test_temporary_forward_object_cannot_create_paper_plan(tmp_path, market, config, monkeypatch):
    book, frame, metadata, calendar, cfg = forward_fixture(tmp_path, market, config)
    try:
        book.account("paper")
        clock = "2024-07-31T20:40:00Z"
        set_time(monkeypatch, clock)
        value = signal(frame, calendar, cfg, "2024-07-31", cfg.active_strategy, metadata["snapshot_id"],
                       decision_time=clock, research_mode="forward")
        with pytest.raises(QuantError) as failure:
            PlanService(book, cfg).create("paper", value, frame, metadata, calendar, clock)
        assert failure.value.code == "UNARCHIVED_SIGNAL"
        archived = SignalArchive(book).generate(frame, metadata, calendar, cfg, "2024-07-31")
        result = PlanService(book, cfg).create("paper", Signal(**archived["signal"]), frame, metadata, calendar, clock)
        assert result["check_status"] == "BLOCKED"  # Empty account has no independent reconciliation.
        assert result["payload"]["signal_archive_id"] == archived["archive_id"]
    finally:
        book.close()


def test_corrupt_archive_is_not_used_for_plan(ledger, market, config):
    _, frame, metadata, calendar = market
    archive = SignalArchive(ledger)
    record = archive.generate(frame, metadata, calendar, config, "2024-07-31")
    corrupted = json.loads(json.dumps(record))
    corrupted["signal"]["target_weights"]["SPY"] = 1
    ledger.connection.execute("UPDATE strategy_signals SET payload=? WHERE archive_id=?",
                              (json.dumps(corrupted), record["archive_id"]))
    with pytest.raises(QuantError) as failure:
        archive.require(Signal(**record["signal"]))
    assert failure.value.code == "CORRUPT_SIGNAL"


def test_signal_archive_survives_connection_restart(ledger, market, config):
    _, frame, metadata, calendar = market
    original = SignalArchive(ledger).generate(frame, metadata, calendar, config, "2024-07-31")
    reopened = Ledger(ledger.path, "demo")
    try:
        assert SignalArchive(reopened).get(original["archive_id"]) == original
    finally:
        reopened.close()
