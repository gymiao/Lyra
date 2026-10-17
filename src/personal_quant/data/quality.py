"""Tradability and configured jump checks on bars available at the cutoff."""
from __future__ import annotations

import pandas as pd

from ..common import QuantError, decimal as D, utc


def price_quality(frame, calendar, config, symbols, end_session, as_of, *, start_session=None,
                  adjusted=False, require_previous=False):
    threshold = config.price_jump_threshold
    if threshold is None:
        return {"status": "BLOCKED", "code": "MISSING_DATA_QUALITY_CONFIG", "issues": [],
                "message": "缺少明确的价格跳变阈值，不能推断风险条件"}
    end = pd.Timestamp(end_session).normalize()
    start = pd.Timestamp(start_session).normalize() if start_session is not None else end
    available = frame.loc[(frame.available_at <= pd.Timestamp(utc(as_of))) & (frame.session_date <= end)]
    issues, unassessed, transitions = [], [], 0
    for symbol in sorted(set(symbols)):
        rows = available.loc[available.symbol == symbol].set_index("session_date").sort_index()
        for day in calendar.sessions[(calendar.sessions >= start) & (calendar.sessions <= end)]:
            # A present OHLC row alone cannot establish a tradable daily bar.
            # Preserve zero-volume evidence and check it even without yesterday's
            # price. This does not claim to identify an exchange-confirmed halt.
            if day in rows.index and D(rows.loc[day].volume) <= 0:
                issues.append({"symbol": symbol, "session": str(day.date()), "code": "NONPOSITIVE_VOLUME",
                               "volume": str(rows.loc[day].volume),
                               "message": "成交量不为正，无法确认可成交；请核对停牌或来源缺失"})
            index = calendar.sessions.get_loc(day)
            previous = calendar.sessions[index - 1] if index else None
            if day not in rows.index or previous is None or previous not in rows.index:
                unassessed.append({"symbol": symbol, "session": str(day.date()), "code": "MISSING_TRANSITION_PRICE"})
                if require_previous:
                    issues.append({"symbol": symbol, "session": str(day.date()), "code": "MISSING_TRANSITION_PRICE"})
                continue
            current, old = rows.loc[day], rows.loc[previous]
            if current.price_basis != old.price_basis or current.source != old.source:
                issues.append({"symbol": symbol, "session": str(day.date()), "code": "PRICE_BASIS_CHANGED"})
                continue
            ratio, dividend = D(current.split_ratio), D(current.dividends)
            if not adjusted and ratio != 1 and dividend:
                issues.append({"symbol": symbol, "session": str(day.date()), "code": "AMBIGUOUS_ACTION_UNIT"})
                continue
            if adjusted:
                change = D(current.adj_close) / D(old.adj_close) - 1
            elif current.price_basis == "unadjusted":
                # Isolated actions: split ratios convert current units to prior
                # units; the ex dividend amount compensates the price drop.
                change = (D(current.close) + dividend) * ratio / D(old.close) - 1
            else:
                # Provider units remain unqualified for real quantity planning.
                change = D(current.adj_close) / D(old.adj_close) - 1
            transitions += 1
            if abs(change) > D(threshold):
                issues.append({"symbol": symbol, "session": str(day.date()), "code": "UNEXPLAINED_PRICE_JUMP",
                               "change": str(change), "threshold": str(threshold), "split_ratio": str(ratio),
                               "dividend": str(dividend), "basis": "adjusted_total_return" if adjusted else str(current.price_basis)})
    return {"status": "BLOCKED" if issues else "PASSED", "code": "DATA_QUALITY_BLOCKED" if issues else "PASSED",
            "issues": issues, "unassessed": unassessed, "coverage": "INCOMPLETE" if unassessed else "COMPLETE",
            "checked_transitions": transitions, "threshold": threshold,
            "basis": "adjusted_total_return" if adjusted else "security_units", "as_of": utc(as_of).isoformat(),
            "start": str(start.date()), "end": str(end.date()), "require_previous": require_previous}


def require_quality(result):
    if result["status"] != "PASSED":
        raise QuantError(result["code"], f"价格质量检查未通过：{result.get('issues') or result.get('message')}")
