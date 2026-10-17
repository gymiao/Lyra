"""Readiness for an exact, already available trading-session window."""
import pandas as pd
from ..common import utc


def history_readiness(frame, calendar, symbols, end_session, as_of, required):
    position = calendar.sessions.get_loc(pd.Timestamp(end_session).normalize().tz_localize(None))
    window = calendar.sessions[max(0, position - required + 1):position + 1]
    usable = frame.loc[frame.session_date.isin(window) & (frame.available_at <= pd.Timestamp(utc(as_of)))]
    counts, missing = {}, {}
    for symbol in symbols:
        rows = usable.loc[usable.symbol == symbol]
        valid = rows.loc[(rows.adj_close > 0) & rows.adj_close.notna(), 'session_date']
        counts[symbol] = len(window.intersection(pd.DatetimeIndex(valid)))
        missing[symbol] = [str(day.date()) for day in window.difference(pd.DatetimeIndex(valid))]
    return {'status': 'PASSED' if len(window) == required and not any(missing.values()) else 'BLOCKED',
            'required_sessions': required, 'calendar_sessions': len(window), 'available_sessions': counts,
            'missing_sessions': missing, 'window_start': str(window[0].date()) if len(window) else None,
            'window_end': str(pd.Timestamp(end_session).date()), 'symbols': list(symbols)}
