from __future__ import annotations

import pandas as pd
from ..common import QuantError, utc
from .quality import price_quality


def quote_set(frame, calendar, config, as_of, symbols, *, frozen_session=None):
    """Current-unit prices at one completed session; stale prices remain diagnostic."""
    required = sorted(set(symbols))
    if not required:
        return {"status": "CASH_ONLY", "prices": {}, "quotes": {}, "expected_session": None}
    if config.publication_delay_minutes is None:
        return {"status": "INCOMPLETE", "prices": {}, "quotes": {}, "expected_session": None,
                "reason": {"code": "MISSING_PUBLICATION_CONFIG", "message": "缺少明确的日线发布延迟，无法检查估值新鲜度"}}
    try:
        session = (calendar.latest_completed(as_of, config.publication_delay_minutes)
                   if frozen_session is None else pd.Timestamp(frozen_session).normalize())
        if calendar.close(session).to_pydatetime() > utc(as_of):
            raise QuantError('FUTURE_VALUATION_SESSION', '冻结估值交易日尚未收盘')
    except QuantError as exc:
        return {"status": "INCOMPLETE", "prices": {}, "quotes": {}, "expected_session": None,
                "reason": {"code": exc.code, "message": str(exc)}}
    available = frame.loc[(frame.available_at <= pd.Timestamp(utc(as_of))) & (frame.session_date <= session)]
    quality = price_quality(frame, calendar, config, required, session, as_of)
    suspect = {item["symbol"] for item in quality["issues"]}
    prices, quotes = {}, {}
    for symbol in required:
        rows = available.loc[available.symbol == symbol].sort_values("session_date")
        if rows.empty:
            quotes[symbol] = {"status": "MISSING"}
            continue
        row = rows.iloc[-1]
        status = "STALE" if row.session_date != session else "UNQUALIFIED_UNIT" if row.price_basis != "unadjusted" else "VALID"
        if status == "VALID" and (symbol in suspect or quality["code"] == "MISSING_DATA_QUALITY_CONFIG"):
            status = "SUSPECT_PRICE"
        quotes[symbol] = {"status": status, "session": str(row.session_date.date()), "available_at": row.available_at.isoformat(),
                          "source": row.source, "data_type": row.data_type, "price_basis": row.price_basis, "reference_price": float(row.close)}
        if status == "VALID":
            prices[symbol] = float(row.close)
    return {"status": "COMPLETE" if len(prices) == len(required) else "INCOMPLETE", "prices": prices,
            "quotes": quotes, "expected_session": str(session.date()), "quality": quality}
