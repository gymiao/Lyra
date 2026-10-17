import pandas as pd
import pytest
from personal_quant.common import QuantError
from personal_quant.data.calendar import Calendar
from personal_quant.data.store import DataStore
from personal_quant.data.update import update_online


def setup_source(market, tmp_path):
    _, frame, _, calendar = market
    frame = frame.copy()
    frame["data_type"], frame["source"], frame["price_basis"] = "real_market", "yahoo_yfinance", "provider_split_adjusted"
    calendar = Calendar(calendar.schedule, "verified_market_sessions")
    store = DataStore(tmp_path / "online")
    store.save(frame.loc[frame.session_date <= "2024-12-10"], calendar)
    requests = []

    def fetch(config, start, end, schedule):
        requests.append((start, end))
        return frame.loc[(frame.session_date >= start) & (frame.session_date < end)].copy()

    return store, frame, calendar, requests, fetch


def test_incremental_request_uses_overlap_and_keeps_earlier_history(market, config, tmp_path):
    store, frame, calendar, requests, fetch = setup_source(market, tmp_path)
    result = update_online(store, config, "2024-01-02", "2024-12-13", calendar_factory=lambda *args: calendar, fetcher=fetch)
    assert requests == [("2024-11-26", "2024-12-13")]
    restored, _, _ = store.load()
    assert restored.session_date.min() == pd.Timestamp("2024-01-02")
    assert restored.session_date.max() == pd.Timestamp("2024-12-12")
    assert result["full_refresh_reason"] is None


def test_changed_adjustment_downloads_full_history_and_retains_prior_version(market, config, tmp_path):
    store, frame, calendar, requests, fetch = setup_source(market, tmp_path)
    old = store.load()[1]["snapshot_id"]
    frame.loc[frame.symbol == "SPY", "adj_close"] *= 0.9
    result = update_online(store, config, "2024-01-02", "2024-12-13", calendar_factory=lambda *args: calendar, fetcher=fetch)
    assert requests == [("2024-11-26", "2024-12-13"), ("2024-01-02", "2024-12-13")]
    assert result["full_refresh_reason"] == "historical_price_revision"
    prior = store.load(old)[0]
    revised = store.load()[0]
    assert prior.loc[prior.symbol == "SPY", "adj_close"].iloc[0] != revised.loc[revised.symbol == "SPY", "adj_close"].iloc[0]


def test_new_action_forces_backfill_but_known_action_does_not_repeat(market, config, tmp_path):
    store, frame, calendar, requests, fetch = setup_source(market, tmp_path)
    frame.loc[(frame.symbol == "SPY") & (frame.session_date == "2024-12-11"), "dividends"] = 1
    result = update_online(store, config, "2024-01-02", "2024-12-13", calendar_factory=lambda *args: calendar, fetcher=fetch)
    assert result["full_refresh_reason"] == "new_corporate_action"
    requests.clear()
    second = update_online(store, config, "2024-01-02", "2024-12-14", calendar_factory=lambda *args: calendar, fetcher=fetch)
    assert len(requests) == 1 and second["full_refresh_reason"] is None


def test_synthetic_cache_is_not_silently_relabelled_as_online(market, config):
    store = market[0]
    with pytest.raises(QuantError, match="new-series"):
        update_online(store, config, "2024-01-02", "2024-12-13", fetcher=lambda *args: pytest.fail("must not download"))
