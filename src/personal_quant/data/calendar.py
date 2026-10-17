from __future__ import annotations

from datetime import timedelta
from pathlib import Path
import pandas as pd

from ..common import QuantError, digest, utc


class Calendar:
    def __init__(self, schedule: pd.DataFrame, kind: str):
        self.kind = kind
        self.schedule = schedule.copy()
        self.schedule.index = pd.to_datetime(self.schedule.index).normalize().tz_localize(None)
        self.schedule["close_time"] = pd.to_datetime(self.schedule["close_time"], utc=True)
        self.schedule = self.schedule.sort_index()
        if self.schedule.index.duplicated().any() or self.schedule.close_time.isna().any():
            raise QuantError("INVALID_CALENDAR", "日历日期重复或收市时点缺失")

    @classmethod
    def csv(cls, path: Path, kind: str) -> Calendar:
        if kind not in {"synthetic_test_sessions", "verified_market_sessions"}:
            raise QuantError("INVALID_CALENDAR", "CSV 日历必须明确合成或已核验市场日历")
        return cls(pd.read_csv(path, index_col="session_date"), kind)

    @classmethod
    def market(cls, start: str, end: str) -> Calendar:
        try:
            import exchange_calendars as xc
        except ImportError as exc:
            raise QuantError("MISSING_DEPENDENCY", "真实市场日历需要安装 exchange-calendars；不能用工作日近似替代") from exc
        first,last=pd.Timestamp(start),pd.Timestamp(end)
        if first==last:
            # exchange-calendars needs a non-empty construction interval;
            # the published schedule still contains only the requested day.
            cal=xc.get_calendar("XNYS",start=str((first-pd.Timedelta(days=7)).date()),end=str((last+pd.Timedelta(days=7)).date()))
        else:
            cal = xc.get_calendar("XNYS", start=start, end=end)
        schedule = cal.schedule.loc[start:end].rename(columns={"close": "close_time", "market_close": "close_time"})
        return cls(schedule[["close_time"]], "verified_market_sessions")

    @property
    def sessions(self) -> pd.DatetimeIndex:
        return self.schedule.index

    @property
    def hash(self) -> str:
        return digest({"kind": self.kind, "sessions": [(str(d.date()), t.isoformat()) for d, t in self.schedule.close_time.items()]})

    def close(self, session) -> pd.Timestamp:
        key = pd.Timestamp(session).normalize().tz_localize(None)
        if key not in self.sessions:
            raise QuantError("NON_SESSION", f"非配置交易日：{session}")
        return self.schedule.loc[key, "close_time"]

    def next(self, session, n: int = 1) -> pd.Timestamp:
        key = pd.Timestamp(session).normalize().tz_localize(None)
        position = self.sessions.get_indexer([key])[0]
        if position < 0 or position + n >= len(self.sessions) or n < 0:
            raise QuantError("CALENDAR_RANGE", "日历没有足够的后续交易日")
        return self.sessions[position + n]

    def month_ends(self) -> list[pd.Timestamp]:
        # Last loaded row is not proof of month end: a later month must exist in the calendar.
        return [a for a, b in zip(self.sessions[:-1], self.sessions[1:]) if a.to_period("M") != b.to_period("M")]

    def latest_completed(self, as_of, delay_minutes: int) -> pd.Timestamp:
        instant = pd.Timestamp(utc(as_of)) - timedelta(minutes=delay_minutes)
        dates = self.schedule.index[self.schedule.close_time <= instant]
        if not len(dates):
            raise QuantError("NO_COMPLETED_SESSION", "截至该时点没有已发布完整日线")
        # Fail closed beyond coverage instead of declaring an old final row fresh forever.
        if instant > self.schedule.close_time.iloc[-1] + timedelta(days=1):
            raise QuantError("CALENDAR_RANGE", "新鲜度检查超出交易日历覆盖，需更新日历")
        return dates[-1]

