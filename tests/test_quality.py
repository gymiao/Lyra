from dataclasses import replace

import pandas as pd
import pytest

from personal_quant.common import QuantError, decimal as D
from personal_quant.data.quality import price_quality
from personal_quant.data.quotes import quote_set
from personal_quant.execution.daily import DailyRunner
from personal_quant.execution.plans import PlanService
from personal_quant.execution.simulator import simulate
from personal_quant.portfolio.reconciliation import ReconciliationRules
from personal_quant.strategies import Signal, signal
from personal_quant.strategies.archive import SignalArchive
from conftest import event

CLOCK = "2024-07-31T21:00:00Z"


def flat(market):
    store, frame, meta, calendar = market
    frame = frame.copy()
    frame[["dividends", "split_ratio"]] = frame[["dividends", "split_ratio"]].astype(float)
    frame[["open", "high", "low", "close", "adj_close"]] = 100.0
    return store, frame, meta, calendar


@pytest.mark.parametrize("close,dividend,ratio,expected", [
    (50, 0, 1, "BLOCKED"), (50, 0, 2, "PASSED"),
    (200, 0, 0.5, "PASSED"), (50, 50, 1, "PASSED"),
    (70, 0, 1, "BLOCKED"), (75, 0, 1, "PASSED"),
])
def test_jump_check_uses_independent_action_adjusted_expectations(market, config, close, dividend, ratio, expected):
    _, frame, _, calendar = flat(market)
    current = (frame.symbol == "SPY") & (frame.session_date == "2024-07-31")
    frame.loc[current, ["open", "high", "low", "close"]] = close
    frame.loc[current, "dividends"] = dividend
    frame.loc[current, "split_ratio"] = ratio
    result = price_quality(frame, calendar, config, ["SPY"], "2024-07-31", CLOCK, require_previous=True)
    assert result["status"] == expected
    assert result["checked_transitions"] == 1
    if expected == "BLOCKED":
        assert result["issues"][0]["code"] == "UNEXPLAINED_PRICE_JUMP"
        assert D(result["issues"][0]["change"]) == D(close) / 100 - 1


def test_quality_does_not_double_adjust_virtual_price_or_guess_simultaneous_units(market, config):
    _, frame, _, calendar = flat(market)
    today = (frame.symbol == "SPY") & (frame.session_date == "2024-07-31")
    frame.loc[today, ["open", "high", "low", "close"]] = 49.5
    frame.loc[today, "split_ratio"] = 2
    frame.loc[today, "dividends"] = 0.5
    raw = price_quality(frame, calendar, config, ["SPY"], "2024-07-31", CLOCK)
    adjusted = price_quality(frame, calendar, config, ["SPY"], "2024-07-31", CLOCK, adjusted=True)
    assert raw["issues"][0]["code"] == "AMBIGUOUS_ACTION_UNIT"
    assert adjusted["status"] == "PASSED"  # Adjusted 100 -> 100, no extra action.


def test_future_unavailable_and_unrelated_prices_do_not_contaminate_quality(market, config):
    _, frame, _, calendar = flat(market)
    prior = price_quality(frame, calendar, config, ["SPY"], "2024-07-31", CLOCK)
    changed = frame.copy()
    changed.loc[(changed.session_date > "2024-07-31") | (changed.symbol == "GLD"), "close"] *= 20
    assert price_quality(changed, calendar, config, ["SPY"], "2024-07-31", CLOCK) == prior
    today = (changed.symbol == "SPY") & (changed.session_date == "2024-07-31")
    changed.loc[today, "available_at"] = pd.Timestamp("2024-08-01T21:00:00Z")
    result = price_quality(changed, calendar, config, ["SPY"], "2024-07-31", CLOCK, require_previous=True)
    assert result["issues"][0]["code"] == "MISSING_TRANSITION_PRICE"


def test_suspect_prices_block_signal_plan_and_daily_but_keep_original_rows(ledger, market, config, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    store, frame, _, calendar = flat(market)
    cfg = replace(config, reference_deviation=1.0)
    ledger.import_events("sample", [event("opening", "DEPOSIT", amount=1000)])
    ledger.reconcile("sample", {"account_id": "sample", "currency": "USD", "as_of": CLOCK,
        "cash_basis": "settled", "cash": 1000, "positions": {}, "source": "independent_fixture"},
        rules=ReconciliationRules.from_config(cfg))
    today = (frame.symbol == "SPY") & (frame.session_date == "2024-07-31")
    frame.loc[today, ["open", "high", "low", "close", "adj_close"]] = 50
    blocked = signal(frame, calendar, cfg, "2024-07-31", "fixed", "test", decision_time=CLOCK)
    assert blocked.status == "DATA_QUALITY_BLOCKED" and not any(blocked.target_weights.values())
    # Research adj_close can be valid while raw units have an unexplained jump.
    frame.loc[today, "adj_close"] = 100
    metadata = store.save(frame, calendar)
    archived = SignalArchive(ledger).generate(frame, metadata, calendar, cfg, "2024-07-31", strategy="trend", decision_time=CLOCK)
    plan = PlanService(ledger, cfg).create("sample", Signal(**archived["signal"]), frame, metadata, calendar, CLOCK)
    assert plan["check_status"] == "BLOCKED"
    assert plan["payload"]["checks"][0]["code"] == "DATA_QUALITY_BLOCKED"
    assert D(plan["reserved_cash"]) == 0 and ledger.sequence("sample") == 1
    daily = DailyRunner(ledger, cfg, store).run("sample", as_of=CLOCK)
    assert daily["status"] == "BLOCKED" and daily["data"]["quality"]["issues"]
    restored, _, _ = store.load()
    assert restored.loc[today, "close"].iloc[0] == 50  # No deletion/repair of evidence.


def test_frozen_plan_execution_rechecks_quality_before_writing_fills(ledger, market, config):
    store, frame, _, calendar = flat(market)
    cfg = replace(config, reference_deviation=1.0, active_strategy="fixed")
    ledger.import_events("sample", [event("opening", "DEPOSIT", amount=1000)])
    ledger.reconcile("sample", {"account_id": "sample", "currency": "USD", "as_of": CLOCK,
        "cash_basis": "settled", "cash": 1000, "positions": {}, "source": "independent_fixture"},
        rules=ReconciliationRules.from_config(cfg))
    metadata = store.save(frame, calendar)
    archived = SignalArchive(ledger).generate(frame, metadata, calendar, cfg, "2024-07-31", decision_time=CLOCK)
    service = PlanService(ledger, cfg)
    plan = service.create("sample", Signal(**archived["signal"]), frame, metadata, calendar, CLOCK)
    assert plan["check_status"] == "PASSED"
    today = (frame.symbol == "SPY") & (frame.session_date == "2024-08-01")
    frame.loc[today, ["open", "high", "low", "close"]] = 150
    with pytest.raises(QuantError) as exc:
        simulate(service, plan["plan_id"], frame, calendar, "2024-08-01T21:00:00Z")
    assert exc.value.code == "DATA_QUALITY_BLOCKED" and ledger.sequence("sample") == 1


def test_suspect_valuation_does_not_report_spurious_equity(market, config):
    _, frame, _, calendar = flat(market)
    today = (frame.symbol == "SPY") & (frame.session_date == "2024-07-31")
    frame.loc[today, ["open", "high", "low", "close"]] = 10
    quotes = quote_set(frame, calendar, config, CLOCK, ["SPY"])
    assert quotes["status"] == "INCOMPLETE" and quotes["prices"] == {}
    assert quotes["quotes"]["SPY"]["status"] == "SUSPECT_PRICE"
    assert quotes["quality"]["issues"]


def test_spot_only_valuation_discloses_unchecked_history_and_blocks_quantity_use(market, config):
    _, frame, _, calendar = flat(market)
    frame = frame.loc[(frame.symbol == "SPY") & (frame.session_date == "2024-07-31")]
    quotes = quote_set(frame, calendar, config, CLOCK, ["SPY"])
    assert quotes["prices"] == {"SPY": 100}
    assert quotes["quality"]["coverage"] == "INCOMPLETE" and quotes["quality"]["checked_transitions"] == 0
    result = price_quality(frame, calendar, config, ["SPY"], "2024-07-31", CLOCK, require_previous=True)
    assert result["status"] == "BLOCKED"


@pytest.mark.parametrize("threshold", [0, -0.1, True, float('inf')])
def test_invalid_jump_threshold_does_not_silently_disable_check(config, threshold):
    with pytest.raises(QuantError):
        replace(config, price_jump_threshold=threshold).validate()


def test_zero_volume_bar_is_not_a_valid_quote_even_without_prior_row(market, config):
    _, frame, _, calendar = flat(market)
    frame = frame.loc[(frame.symbol == "SPY") & (frame.session_date == "2024-07-31")].copy()
    frame["volume"] = 0
    quotes = quote_set(frame, calendar, config, CLOCK, ["SPY"])
    assert quotes["status"] == "INCOMPLETE"
    assert quotes["prices"] == {}
    assert quotes["quality"]["issues"][0]["code"] == "NONPOSITIVE_VOLUME"


@pytest.mark.parametrize("zero_day", ["2024-07-01", "2024-07-31"])
def test_zero_volume_with_valid_prices_blocks_signals_and_preserves_evidence(market, config, zero_day):
    store, frame, _, calendar = flat(market)
    mask = (frame.symbol == "SPY") & (frame.session_date == zero_day)
    frame.loc[mask, "volume"] = 0
    metadata = store.save(frame, calendar)
    restored, _, _ = store.load(metadata["snapshot_id"])
    for strategy in ["fixed", "trend"]:
        decision = signal(restored, calendar, config, "2024-07-31", strategy,
                          metadata["snapshot_id"], decision_time=CLOCK)
        assert decision.status == "DATA_QUALITY_BLOCKED"
        assert not any(decision.target_weights.values())
        assert "NONPOSITIVE_VOLUME" in decision.reasons["SPY"]
    assert restored.loc[mask, "volume"].iloc[0] == 0
    assert restored.loc[mask, "close"].iloc[0] == 100
