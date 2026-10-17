from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4
import numpy as np
import pandas as pd

from ..common import QuantError, digest, now_utc, write_json
from .calendar import Calendar
from ..locks import publication_lock

REQUIRED = ["symbol", "session_date", "market", "currency", "source", "data_type",
            "price_basis", "open", "high", "low", "close", "adj_close", "volume",
            "dividends", "split_ratio", "available_at"]


def normalize(frame: pd.DataFrame, calendar: Calendar) -> pd.DataFrame:
    missing = set(REQUIRED) - set(frame.columns)
    if missing:
        raise QuantError("INVALID_DATA", f"行情缺少字段：{sorted(missing)}")
    result = frame[REQUIRED].copy()
    result["session_date"] = pd.to_datetime(result.session_date).dt.normalize()
    result["available_at"] = pd.to_datetime(result.available_at, utc=True)
    if result.empty or result.session_date.isna().any() or result.available_at.isna().any():
        raise QuantError("INVALID_DATA", "行情为空或时间缺失")
    if result.session_date.dt.tz is not None:
        raise QuantError("INVALID_DATA", "session_date 为市场日期，不应携带时区")
    if not result.session_date.isin(calendar.sessions).all():
        raise QuantError("NON_SESSION", "行情含非配置交易日，不能直接成交")
    for column in ["open", "high", "low", "close", "adj_close", "volume", "dividends", "split_ratio"]:
        result[column] = pd.to_numeric(result[column], errors="coerce")
        if not np.isfinite(result[column]).all():
            raise QuantError("INVALID_DATA", f"{column} 缺失或非有限；不自动填充")
        if (result[column] < 0).any():
            raise QuantError("INVALID_DATA", f"{column} 不能为负")
    if (result[["open", "high", "low", "close", "adj_close"]] <= 0).any().any() or (result.split_ratio <= 0).any():
        raise QuantError("INVALID_DATA", "价格和拆股比例必须为正（无拆股填 1）")
    if (result.high < result[["open", "close", "low"]].max(axis=1)).any() or (result.low > result[["open", "close", "high"]].min(axis=1)).any():
        raise QuantError("INVALID_DATA", "OHLC 价格关系异常")
    if set(result.market) != {"XNYS"} or set(result.currency) != {"USD"}:
        raise QuantError("UNSUPPORTED_MARKET", "行情市场/币种混用或不受支持")
    if not set(result.data_type) <= {"synthetic", "real_market"} or len(set(result.data_type)) != 1:
        raise QuantError("ENVIRONMENT_MISMATCH", "合成行情与真实行情不可混在同一快照")
    if not set(result.price_basis) <= {"unadjusted", "provider_split_adjusted"}:
        raise QuantError("INVALID_DATA", "未知价格口径")
    if calendar.kind == "synthetic_test_sessions" and set(result.data_type) != {"synthetic"}:
        raise QuantError("ENVIRONMENT_MISMATCH", "真实行情不能使用合成交易日历")
    closes = result.session_date.map(calendar.schedule.close_time)
    if (result.available_at < closes).any():
        raise QuantError("FUTURE_DATA", "完整日线不可在市场收盘前可用")
    result = result.drop_duplicates()
    if result.duplicated(["symbol", "session_date"]).any():
        raise QuantError("DATA_CONFLICT", "同标的日期含冲突值；历史修订必须明确更新版本")
    if result[["symbol", "source", "price_basis"]].isna().any().any():
        raise QuantError("INVALID_DATA", "标的/来源/价格口径缺失")
    return result.sort_values(["session_date", "symbol"]).reset_index(drop=True)


class DataStore:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, frame: pd.DataFrame, calendar: Calendar, *, incremental: bool = False,
             historical_availability_assumed: bool = True, series_id=None) -> dict:
        with publication_lock(self.root.parent):
            return self._save(frame, calendar, incremental=incremental,
                historical_availability_assumed=historical_availability_assumed, series_id=series_id)

    @staticmethod
    def series_identity(metadata):
        return digest({key: metadata[key] for key in ('source', 'data_type', 'price_basis', 'symbols', 'currency', 'market', 'calendar_kind')})

    def heads(self):
        path = self.root / 'series-heads.json'
        return json.loads(path.read_text()) if path.exists() else {}

    def load_role(self, role):
        from .selection import selected
        return selected(self, role)

    def load_series(self, series_id):
        head = self.heads().get(series_id)
        if not head:
            raise QuantError('UNKNOWN_DATA_SERIES', '数据系列尚无已发布快照')
        value = self.load(head['snapshot_id'])
        if self.series_identity(value[1]) != series_id:
            raise QuantError('CORRUPT_DATA_SERIES', '系列索引与快照身份不一致')
        return value

    def _save(self, frame, calendar, *, incremental=False, historical_availability_assumed=True, series_id=None):
        normalized = normalize(frame, calendar)
        latest = self.root / "latest.json"
        if incremental and (series_id or latest.exists()):
            previous, meta, old_cal = self.load_series(series_id) if series_id else self.load()
            if meta["data_type"] != normalized.data_type.iloc[0] or old_cal.kind != calendar.kind:
                raise QuantError("ENVIRONMENT_MISMATCH", "增量更新不允许切换数据身份")
            overlap = old_cal.sessions.intersection(calendar.sessions)
            if not old_cal.schedule.loc[overlap, "close_time"].equals(calendar.schedule.loc[overlap, "close_time"]):
                raise QuantError("CALENDAR_CONFLICT", "增量日历重叠交易日的收盘时点发生冲突，请显式核验新版本")
            combined = pd.concat([old_cal.schedule, calendar.schedule])
            combined = combined.loc[~combined.index.duplicated(keep="last")]
            calendar = Calendar(combined, calendar.kind)
            for symbol in set(previous.symbol) & set(normalized.symbol):
                for field in ["source", "price_basis"]:
                    if set(previous.loc[previous.symbol == symbol, field]) != set(normalized.loc[normalized.symbol == symbol, field]):
                        raise QuantError("DATA_BASIS_CONFLICT", "增量更新不允许静默切换来源或价格口径，请使用独立数据版本")
            keys = pd.MultiIndex.from_frame(normalized[["symbol", "session_date"]])
            old_keys = pd.MultiIndex.from_frame(previous[["symbol", "session_date"]])
            normalized = normalize(pd.concat([previous.loc[~old_keys.isin(keys)], normalized]), calendar)
        content = normalized.copy()
        content["session_date"] = content.session_date.dt.strftime("%Y-%m-%d")
        content["available_at"] = content.available_at.dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        snapshot = digest({"schema_version": 1, "calendar_hash": calendar.hash,
                           "availability_assumed": historical_availability_assumed,
                           "rows": content.to_dict("records")})
        directory = self.root / snapshot
        if not directory.exists():
            temporary = self.root / (".pending-" + uuid4().hex)
            temporary.mkdir()
            normalized.to_parquet(temporary / "prices.parquet", index=False)
            calendar.schedule.to_csv(temporary / "calendar.csv", index_label="session_date")
            meta = {"schema_version": 1, "snapshot_id": snapshot, "data_hash": digest(content.to_dict("records")),
                    "calendar_kind": calendar.kind, "calendar_hash": calendar.hash,
                    "data_type": normalized.data_type.iloc[0], "source": sorted(set(normalized.source)),
                    "price_basis": sorted(set(normalized.price_basis)), "currency": "USD", "market": "XNYS",
                    "market_timezone": "America/New_York", "acquired_at": now_utc(),
                    "historical_availability_assumed": historical_availability_assumed,
                    "start": str(normalized.session_date.min().date()), "end": str(normalized.session_date.max().date()),
                    "rows": len(normalized), "symbols": sorted(set(normalized.symbol))}
            write_json(temporary / "manifest.json", meta)
            os.replace(temporary, directory)
        # Verify existing content too, and publish each series independently.
        verified = self.load(snapshot)[1]
        actual_series = self.series_identity(verified)
        if series_id and actual_series != series_id:
            raise QuantError('DATA_SERIES_CONFLICT', '更新结果改变了系列来源/口径/标的身份')
        heads = self.heads()
        heads[actual_series] = {'snapshot_id': snapshot, 'metadata': verified}
        write_json(self.root / 'series-heads.json', heads)
        write_json(latest, {"snapshot_id": snapshot})
        # Acquisition log is separate from content identity.
        with (self.root / "acquisitions.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"snapshot_id": snapshot, "acquired_at": now_utc()}) + "\n")
        return json.loads((directory / "manifest.json").read_text())

    def load(self, snapshot_id: str | None = None) -> tuple[pd.DataFrame, dict, Calendar]:
        if snapshot_id is None:
            if not (self.root / "latest.json").exists():
                raise QuantError("NO_DATA", "没有数据快照，请先导入 CSV 或下载")
            snapshot_id = json.loads((self.root / "latest.json").read_text())["snapshot_id"]
        if len(snapshot_id) != 64 or any(c not in "0123456789abcdef" for c in snapshot_id):
            raise QuantError("INVALID_SNAPSHOT", "非法快照标识")
        directory = self.root / snapshot_id
        meta = json.loads((directory / "manifest.json").read_text())
        calendar = Calendar.csv(directory / "calendar.csv", meta["calendar_kind"])
        frame = normalize(pd.read_parquet(directory / "prices.parquet"), calendar)
        content = frame.copy()
        content["session_date"] = content.session_date.dt.strftime("%Y-%m-%d")
        content["available_at"] = content.available_at.dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        identity = digest({"schema_version": 1, "calendar_hash": calendar.hash,
                           "availability_assumed": meta["historical_availability_assumed"], "rows": content.to_dict("records")})
        if identity != snapshot_id or meta["snapshot_id"] != snapshot_id:
            raise QuantError("CORRUPT_SNAPSHOT", "快照内容或日历哈希不匹配")
        derived = {"data_type": frame.data_type.iloc[0], "source": sorted(set(frame.source)),
                   "price_basis": sorted(set(frame.price_basis)), "symbols": sorted(set(frame.symbol)),
                   "start": str(frame.session_date.min().date()), "end": str(frame.session_date.max().date()),
                   "rows": len(frame), "currency": "USD", "market": "XNYS", "calendar_hash": calendar.hash,
                   "data_hash": digest(content.to_dict("records"))}
        if any(meta.get(key) != value for key, value in derived.items()):
            raise QuantError("CORRUPT_SNAPSHOT", "快照声明与实际内容不一致，不能改变来源、类型或价格口径")
        return frame, meta, calendar
