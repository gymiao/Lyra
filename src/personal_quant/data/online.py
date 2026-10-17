from __future__ import annotations

from datetime import timedelta
from pathlib import Path
import time
import pandas as pd

from ..common import QuantError, now_utc, utc
from ..config import Config
from .calendar import Calendar


def download(config: Config, start: str, end: str, calendar: Calendar, downloader=None, sleep=time.sleep) -> pd.DataFrame:
    """Explicit Yahoo parameters. Returned Close is not certified raw execution data."""
    if downloader is None:
        import yfinance as yf
        # The public cache hook keeps provider cookies/timezones in this runtime,
        # including when the user's global cache directory is not writable.
        cache = Path(config.runtime_dir) / "data" / "provider-cache"
        cache.mkdir(parents=True, exist_ok=True)
        yf.set_tz_cache_location(str(cache.resolve()))
        downloader = yf.download
    last_error = None
    for attempt in range(config.download_attempts):
        try:
            result = downloader(list(config.symbols), start=start, end=end, interval="1d",
                                auto_adjust=False, back_adjust=False, actions=True,
                                keepna=True, repair=False, ignore_tz=False,
                                progress=False, threads=False, timeout=config.download_timeout,
                                group_by="ticker", multi_level_index=True)
            if result is None or result.empty:
                raise QuantError("DOWNLOAD_EMPTY", "行情源返回空数据，可能限流或下载失败")
            rows = []
            observed_at = utc(now_utc())
            for symbol in config.symbols:
                table = result[symbol] if isinstance(result.columns, pd.MultiIndex) else result
                expected = {"Open", "High", "Low", "Close", "Adj Close", "Volume", "Dividends", "Stock Splits"}
                if not expected <= set(table.columns):
                    raise QuantError("SOURCE_SCHEMA", f"{symbol} 源字段不完整：{sorted(expected - set(table.columns))}")
                for date, row in table.iterrows():
                    session = pd.Timestamp(date).tz_localize(None).normalize()
                    available_at = calendar.close(session) + timedelta(minutes=config.publication_delay_minutes if config.publication_delay_minutes is not None else 30)
                    if available_at.to_pydatetime() > observed_at:
                        continue  # Never cache an intraday bar that becomes "complete" merely as time passes.
                    rows.append({"symbol": symbol, "session_date": session, "market": config.market,
                                 "currency": config.currency, "source": "yahoo_yfinance",
                                 "data_type": "real_market", "price_basis": "provider_split_adjusted",
                                 "open": row["Open"], "high": row["High"], "low": row["Low"],
                                 "close": row["Close"], "adj_close": row["Adj Close"], "volume": row["Volume"],
                                 "dividends": row["Dividends"], "split_ratio": row["Stock Splits"] or 1.0,
                                 "available_at": available_at})
            if not rows:
                raise QuantError("NO_COMPLETED_DATA", "源仅返回尚未完整发布的日线，等待下一次获取，不缓存为可用价格")
            return pd.DataFrame(rows)
        except QuantError as exc:
            if exc.code in {"SOURCE_SCHEMA", "NO_COMPLETED_DATA"}:
                raise
            last_error = exc
        except Exception as exc:
            last_error = exc
        if attempt + 1 < config.download_attempts:
            sleep(2 ** attempt)
    raise QuantError("DOWNLOAD_FAILED", f"行情下载尝试 {config.download_attempts} 次失败：{type(last_error).__name__}: {last_error}") from last_error
