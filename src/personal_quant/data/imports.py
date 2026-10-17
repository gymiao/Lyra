"""Read-only CSV preflight shared by the price upload UI."""
from io import BytesIO
import hashlib
import pandas as pd

from ..common import QuantError, digest
from .calendar import Calendar
from .store import normalize


def price_csv_preview(content, *, calendar_content=None, calendar_kind="verified_market_sessions", environment="demo"):
    frame = pd.read_csv(BytesIO(content))
    if calendar_content:
        calendar = Calendar(pd.read_csv(BytesIO(calendar_content), index_col="session_date"), calendar_kind)
    elif calendar_kind == "verified_market_sessions":
        if "session_date" not in frame:
            raise QuantError("INVALID_DATA", "行情缺少session_date")
        calendar = Calendar.market(str(frame.session_date.min()), str(pd.Timestamp(frame.session_date.max()) + pd.Timedelta(days=45)))
    else:
        raise QuantError("MISSING_CALENDAR", "合成样本必须提供明确的测试日历CSV")
    if calendar.kind not in {"synthetic_test_sessions", "verified_market_sessions"}:
        raise QuantError("INVALID_CALENDAR", "必须明确日历资格")
    frame = normalize(frame, calendar)
    if environment in {"real", "paper"} and (set(frame.data_type) != {"real_market"} or calendar.kind != "verified_market_sessions"):
        raise QuantError("ENVIRONMENT_MISMATCH", "前向目录不能保存合成价格/日历")
    key = digest({"content": hashlib.sha256(content).hexdigest(), "calendar": hashlib.sha256(calendar_content).hexdigest() if calendar_content else None,
                  "calendar_kind": calendar_kind, "environment": environment})
    return {"input_hash": key, "rows": len(frame), "symbols": sorted(set(frame.symbol)),
            "data_type": frame.data_type.iloc[0], "price_basis": sorted(set(frame.price_basis)),
            "source": sorted(set(frame.source)), "start": str(frame.session_date.min().date()),
            "end": str(frame.session_date.max().date()), "calendar_hash": calendar.hash}, frame, calendar
