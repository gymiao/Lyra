"""Incremental online requests, with explicit full-history refresh on revisions."""
from __future__ import annotations

import numpy as np
import pandas as pd
from ..common import QuantError
from .calendar import Calendar
from .online import download


def update_online(store, config, start, end, *, new_series=False, full_refresh=False,
                  calendar_factory=Calendar.market, fetcher=download, series_id=None):
    start, end = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
    if start >= end or start.tz is not None or end.tz is not None:
        raise QuantError("INVALID_INTERVAL", "下载日期必须是无时区市场日期，起点早于不包含的终点")
    previous, metadata, incremental = None, None, False
    if (store.root / "latest.json").exists() and not new_series:
        previous, metadata, _ = store.load_series(series_id) if series_id else store.load()
        if metadata["data_type"] != "real_market" or metadata["source"] != ["yahoo_yfinance"] or metadata["symbols"] != sorted(config.symbols):
            raise QuantError("SOURCE_SERIES_CONFLICT", "当前缓存的来源/标的与在线研究不同；使用独立配置或 --new-series 显式建立新系列，不改变账本")
        incremental = True
    requested_start = start
    if metadata and not full_refresh and start >= pd.Timestamp(metadata["start"]) and end > pd.Timestamp(metadata["end"]):
        start = max(pd.Timestamp(metadata["start"]), pd.Timestamp(metadata["end"]) - pd.Timedelta(days=14))
    if metadata and full_refresh:
        start = min(start, pd.Timestamp(metadata["start"]))
        end = max(end, pd.Timestamp(metadata["end"]) + pd.Timedelta(days=1))
    calendar_start = min(start, pd.Timestamp(metadata["start"])) if metadata else start
    calendar = calendar_factory(str(calendar_start.date()), str((end + pd.Timedelta(days=45)).date()))
    requests = [{"start": str(start.date()), "end_exclusive": str(end.date())}]
    data = fetcher(config, requests[0]["start"], requests[0]["end_exclusive"], calendar)
    reason = None
    if previous is not None and not full_refresh:
        before = previous.set_index(["symbol", "session_date"])
        after = data.set_index(["symbol", "session_date"])
        overlap = before.index.intersection(after.index)
        historical_revision = len(overlap) and not np.allclose(before.loc[overlap, "adj_close"], after.loc[overlap, "adj_close"], rtol=1e-10, atol=1e-10)
        new_actions = False
        for key, row in after.iterrows():
            if row.dividends != 0 or row.split_ratio != 1:
                if key not in before.index or before.loc[key, "dividends"] != row.dividends or before.loc[key, "split_ratio"] != row.split_ratio:
                    new_actions = True
        if historical_revision or new_actions:
            reason = "historical_price_revision" if historical_revision else "new_corporate_action"
            full_start = min(requested_start, pd.Timestamp(metadata["start"]))
            full_end = max(end, pd.Timestamp(metadata["end"]) + pd.Timedelta(days=1))
            requests.append({"start": str(full_start.date()), "end_exclusive": str(full_end.date())})
            calendar = calendar_factory(str(full_start.date()), str((full_end + pd.Timedelta(days=45)).date()))
            data = fetcher(config, requests[-1]["start"], requests[-1]["end_exclusive"], calendar)
    saved = store.save(data, calendar, incremental=incremental, series_id=series_id)
    return {**saved, "download_requests": requests, "full_refresh_reason": reason,
            "new_series": new_series, "cache_incremental": incremental}
