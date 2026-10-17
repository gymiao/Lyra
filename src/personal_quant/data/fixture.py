from __future__ import annotations

from datetime import timedelta
from pathlib import Path
import numpy as np
import pandas as pd

from .calendar import Calendar


def create_fixture(root: Path) -> tuple[Path, Path]:
    """Seeded synthetic session schedule, deliberately NOT an authoritative NYSE calendar."""
    root.mkdir(parents=True, exist_ok=True)
    dates = pd.bdate_range("2024-01-02", "2025-01-15").difference(pd.DatetimeIndex(["2024-05-27", "2024-09-02"]))
    close = [pd.Timestamp(d.date()).tz_localize("America/New_York") + pd.Timedelta(hours=16) for d in dates]
    calendar = Calendar(pd.DataFrame({"close_time": close}, index=dates), "synthetic_test_sessions")
    calendar.schedule.to_csv(root / "calendar.csv", index_label="session_date")
    rng = np.random.default_rng(20261008)
    rows = []
    for number, symbol in enumerate(["SPY", "IEF", "GLD"]):
        returns = rng.normal(0.0003, 0.007 + number * 0.001, len(dates))
        returns[170:205] -= 0.008 if number == 0 else 0.002
        prices = (100 + number * 40) * np.exp(np.cumsum(returns))
        for index, (date, price) in enumerate(zip(dates, prices)):
            rows.append({"symbol": symbol, "session_date": date.date(), "market": "XNYS", "currency": "USD",
                         "source": "lyra_frozen_synthetic_v1", "data_type": "synthetic", "price_basis": "unadjusted",
                         "open": float(price * 0.999), "high": float(price * 1.005), "low": float(price * 0.995),
                         "close": float(price), "adj_close": float(price), "volume": 100000 + index,
                         "dividends": 0.0, "split_ratio": 1.0,
                         "available_at": (calendar.close(date) + timedelta(minutes=30)).isoformat()})
    path = root / "prices.csv"
    pd.DataFrame(rows).to_csv(path, index=False, float_format="%.12g")
    return path, root / "calendar.csv"


def create_lifecycle_fixture(root: Path) -> tuple[Path, Path]:
    """Frozen accounting scenario: three decisions, ex dividend, split and exit."""
    prices, schedule = create_fixture(root)
    frame = pd.read_csv(prices)
    day = pd.to_datetime(frame.session_date)
    spy, ief = frame.symbol == "SPY", frame.symbol == "IEF"
    frame["source"] = "lyra_lifecycle_synthetic_v1"
    for column in ["open", "high", "low", "close", "adj_close"]:
        frame.loc[spy, column] = np.where(day[spy] < pd.Timestamp("2024-07-31"), 90.0, 100.0)
        frame.loc[ief, column] = np.where(day[ief] < pd.Timestamp("2024-07-31"), 45.0, 50.0)
    for start, raw in [("2024-08-15", 99.0), ("2024-09-16", 49.5), ("2024-09-20", 39.5)]:
        frame.loc[spy & (day >= start), ["open", "high", "low", "close"]] = raw
    # Total-return adjusted series includes ex dividend and split, with no extra
    # dividend cash added by the abstract research adapter.
    frame.loc[spy & (day >= "2024-09-20"), "adj_close"] = 100 * 39.5 / 49.5
    frame.loc[spy & (day == "2024-08-15"), "dividends"] = 1.0
    frame.loc[spy & (day == "2024-09-16"), "split_ratio"] = 2.0
    frame.to_csv(prices, index=False, float_format="%.12g")
    return prices, schedule
