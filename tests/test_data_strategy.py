from dataclasses import replace
import pandas as pd
import pytest
from personal_quant.common import QuantError
from personal_quant.data.store import normalize
from personal_quant.data.online import download
from personal_quant.strategies import signal


def test_account_state_is_causal_and_does_not_change_fixed_target_rules(market, config):
    _, frame, metadata, calendar = market
    kwargs = dict(account_state={"as_of": "2024-07-31T20:30:00Z", "settled_cash": "0", "positions": {}})
    empty = signal(frame, calendar, config, "2024-07-31", "fixed", metadata["snapshot_id"], **kwargs)
    funded = signal(frame, calendar, config, "2024-07-31", "fixed", metadata["snapshot_id"],
                    account_state={"as_of": "2024-07-31T20:30:00Z", "settled_cash": "5000", "positions": {}})
    assert empty.target_weights == funded.target_weights
    with pytest.raises(QuantError) as error:
        signal(frame, calendar, config, "2024-07-31", "fixed", metadata["snapshot_id"],
               account_state={"as_of": "2024-08-01T20:30:00Z"})
    assert error.value.code == "FUTURE_ACCOUNT_STATE"


def test_repeat_snapshot_and_revision(market):
    store, frame, metadata, calendar = market
    assert store.save(frame, calendar)["snapshot_id"] == metadata["snapshot_id"]
    changed = frame.copy()
    index = changed.index[-1]
    changed.loc[index, ["open", "high", "low", "close", "adj_close"]] *= 1.1
    assert store.save(changed, calendar, incremental=True)["snapshot_id"] != metadata["snapshot_id"]
    pd.testing.assert_frame_equal(store.load(metadata["snapshot_id"])[0], frame)


def test_future_prices_cannot_change_old_signal(market, config):
    store, frame, metadata, calendar = market
    before = signal(frame, calendar, config, "2024-07-31", "trend", metadata["snapshot_id"])
    changed = frame.copy()
    changed.loc[changed.session_date > "2024-07-31", "adj_close"] *= 5
    after = signal(changed, calendar, config, "2024-07-31", "trend", "new_future_snapshot")
    assert before.target_weights == after.target_weights
    assert before.basis_hash == after.basis_hash
    assert before.signal_id == after.signal_id
    assert before.eligible_session == "2024-08-01"


def test_unavailable_close_and_missing_price_block(market, config):
    _, frame, metadata, calendar = market
    late = frame.copy()
    selected = (late.session_date == "2024-07-31") & (late.symbol == "SPY")
    late.loc[selected, "available_at"] = pd.Timestamp("2024-08-01T21:00:00Z")
    result = signal(late, calendar, config, "2024-07-31", "trend", metadata["snapshot_id"])
    assert result.status == "INSUFFICIENT_DATA"
    assert signal(frame.loc[~selected], calendar, config, "2024-07-31", "fixed", metadata["snapshot_id"]).status == "INSUFFICIENT_DATA"


def test_month_end_needs_calendar_not_final_data_row(market, config):
    _, frame, metadata, calendar = market
    with pytest.raises(QuantError, match="月末"):
        signal(frame, calendar, config, "2024-07-15", "fixed", metadata["snapshot_id"])


def test_non_session_and_nan_rejected(market):
    _, frame, _, calendar = market
    bad = frame.copy()
    bad.loc[0, "close"] = float("nan")
    with pytest.raises(QuantError, match="close"):
        normalize(bad, calendar)
    bad = frame.copy()
    bad.loc[0, "session_date"] = pd.Timestamp("2024-07-06")
    with pytest.raises(QuantError, match="交易日"):
        normalize(bad, calendar)


def test_completed_session_uses_exchange_timezone(market):
    _, _, _, calendar = market
    assert str(calendar.latest_completed("2024-07-06T03:00:00Z", 30).date()) == "2024-07-05"
    assert str(calendar.latest_completed("2024-07-05T19:00:00Z", 30).date()) == "2024-07-04"


def test_download_retry_is_bounded(market, config):
    _, _, _, calendar = market
    attempts, sleeps = [], []
    def unavailable(*args, **kwargs):
        attempts.append(kwargs)
        return pd.DataFrame()
    with pytest.raises(QuantError, match="3 次失败"):
        download(config, "2024-01-01", "2024-02-01", calendar, unavailable, sleeps.append)
    assert len(attempts) == 3 and sleeps == [1, 2]
    assert attempts[0]["auto_adjust"] is False
    assert attempts[0]["actions"] is True
    assert attempts[0]["keepna"] is True


def test_configuration_cannot_inherit_real_risk_defaults(config):
    from personal_quant.config import Config
    real = Config.load("configs/real.example.toml")
    with pytest.raises(QuantError, match="明确配置"):
        real.require_execution()
    with pytest.raises(QuantError, match="有限"):
        replace(config, cash_buffer=float("nan")).validate()
def test_incremental_fetch_calendar_extends_without_losing_old_data(market):
    store, frame, original, calendar = market
    from personal_quant.data.calendar import Calendar
    new_calendar = Calendar(calendar.schedule.loc["2024-12-01":], calendar.kind)
    newer = frame.loc[frame.session_date >= "2024-12-01"].copy()
    updated = store.save(newer, new_calendar, incremental=True)
    restored, _, restored_calendar = store.load(updated["snapshot_id"])
    assert len(restored) == len(frame)
    assert restored.session_date.min() == frame.session_date.min()
    assert restored_calendar.hash == calendar.hash
    assert updated["snapshot_id"] == original["snapshot_id"]


def test_metadata_cannot_relabel_synthetic_data_as_real(market):
    import json
    store, _, metadata, _ = market
    path = store.root / metadata["snapshot_id"] / "manifest.json"
    content = json.loads(path.read_text())
    content["data_type"] = "real_market"
    path.write_text(json.dumps(content))
    with pytest.raises(QuantError, match="声明"):
        store.load()


def test_source_intraday_bar_is_not_cached_as_future_completed_price(market, config, monkeypatch):
    _, _, _, calendar = market
    cfg = replace(config, symbols=("SPY",), weights=(1,))
    table = pd.DataFrame({"Open": [100., 101.], "High": [100., 101.], "Low": [100., 101.],
                          "Close": [100., 101.], "Adj Close": [100., 101.], "Volume": [1000, 10],
                          "Dividends": [0., 0.], "Stock Splits": [0., 0.]},
                         index=pd.to_datetime(["2024-07-30", "2024-07-31"]))
    monkeypatch.setattr("personal_quant.data.online.now_utc", lambda: "2024-07-31T19:00:00Z")
    before_close = download(cfg, "2024-07-30", "2024-08-01", calendar, lambda *args, **kwargs: table)
    assert list(before_close.session_date) == [pd.Timestamp("2024-07-30")]
    monkeypatch.setattr("personal_quant.data.online.now_utc", lambda: "2024-07-31T20:45:00Z")
    # A new successful fetch is required; the prior returned data never acquires a July 31 bar.
    after_close = download(cfg, "2024-07-30", "2024-08-01", calendar, lambda *args, **kwargs: table)
    assert len(before_close) == 1 and len(after_close) == 2


def test_only_unpublished_source_bars_wait_without_retries(market, config, monkeypatch):
    _, _, _, calendar = market
    cfg = replace(config, symbols=("SPY",), weights=(1,))
    table = pd.DataFrame({"Open": [100.], "High": [100.], "Low": [100.], "Close": [100.], "Adj Close": [100.],
                          "Volume": [1000], "Dividends": [0.], "Stock Splits": [0.]}, index=pd.to_datetime(["2024-07-31"]))
    calls, sleeps = [], []
    def provider(*args, **kwargs):
        calls.append(1)
        return table
    monkeypatch.setattr("personal_quant.data.online.now_utc", lambda: "2024-07-31T20:05:00Z")
    with pytest.raises(QuantError) as exc:
        download(cfg, "2024-07-31", "2024-08-01", calendar, provider, sleeps.append)
    assert exc.value.code == "NO_COMPLETED_DATA"
    assert calls == [1] and sleeps == []
