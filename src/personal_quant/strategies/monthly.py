from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import timedelta
import pandas as pd

from ..common import QuantError, digest, now_utc, utc
from ..config import Config
from ..data.calendar import Calendar
from ..data.quality import price_quality

VERSION = "monthly.v1"


@dataclass(frozen=True)
class Signal:
    signal_id: str
    strategy: str
    version: str
    snapshot_id: str
    basis_hash: str
    config_hash: str
    decision_time: str
    generated_at: str
    decision_session: str
    eligible_session: str
    valid_through_session: str
    target_weights: dict[str, float]
    reasons: dict[str, str]
    status: str
    research_mode: str

    def content(self) -> dict:
        return asdict(self)


def signal(frame: pd.DataFrame, calendar: Calendar, config: Config, session, strategy: str,
           snapshot_id: str, *, decision_time=None, research_mode="historical_reconstruction",
           account_state: dict | None = None) -> Signal:
    if strategy not in {"fixed", "trend"}:
        raise QuantError("UNKNOWN_STRATEGY", "未知策略")
    if research_mode not in {"historical_reconstruction", "forward"}:
        raise QuantError("INVALID_MODE", "信号模式必须明确")
    day = pd.Timestamp(session).normalize().tz_localize(None)
    if day not in calendar.month_ends():
        raise QuantError("NOT_REBALANCE_DAY", "不是已确认的月末交易日")
    close = calendar.close(day)
    delay = config.publication_delay_minutes if config.publication_delay_minutes is not None else 30
    decision = pd.Timestamp(utc(decision_time)) if decision_time else close + timedelta(minutes=delay)
    # These two target-weight rules do not depend on account capital or holdings.
    # Accept a caller's account snapshot without turning weights into orders;
    # research may omit it because bt owns its virtual account state.
    if account_state is not None:
        if "as_of" not in account_state or utc(account_state["as_of"]) > decision.to_pydatetime():
            raise QuantError("FUTURE_ACCOUNT_STATE", "策略账户状态必须带截至时间，且不能晚于决策时点")
    if decision < close:
        raise QuantError("FUTURE_DATA", "月末信号不能在收盘前形成")
    eligible = calendar.next(day)
    if research_mode == "forward":
        if decision >= calendar.close(eligible) or utc(now_utc()) >= calendar.close(eligible).to_pydatetime():
            raise QuantError("EXPIRED_SIGNAL", "前向信号已经错过适用交易日；只能生成历史研究")
    available = frame.loc[(frame.session_date <= day) & (frame.available_at <= decision) & frame.symbol.isin(config.symbols)]
    position = calendar.sessions.get_loc(day)
    window = calendar.sessions[max(0, position - config.lookback + 1):position + 1]
    prices = available.pivot(index="session_date", columns="symbol", values="adj_close").reindex(index=window, columns=config.symbols)
    complete = len(window) == config.lookback and not prices.isna().any().any()
    quality = price_quality(available, calendar, config, config.symbols, day, decision.isoformat(),
                            start_session=window[0], adjusted=True) if complete else None
    weights, reasons = {}, {}
    for symbol, base_weight in zip(config.symbols, config.weights):
        if not complete:
            weights[symbol] = 0.0
            reasons[symbol] = f"数据不足：需要 {config.lookback} 个完整、已可用交易日"
        elif quality["status"] != "PASSED":
            weights[symbol] = 0.0
            reasons[symbol] = f"数据质量阻断：{quality['code']}；{quality['issues']}"
        elif strategy == "fixed":
            weights[symbol] = float(base_weight)
            reasons[symbol] = "月度固定权重再平衡"
        else:
            last, average = float(prices[symbol].iloc[-1]), float(prices[symbol].mean())
            weights[symbol] = float(base_weight) if last > average else 0.0
            reasons[symbol] = f"收盘 {last:.6f} {'>' if last > average else '<='} {config.lookback} 日均线 {average:.6f}；{'保留基准权重' if last > average else '该份额留作现金'}"
    basis = digest({"sessions": [str(x.date()) for x in window], "symbols": list(config.symbols),
                    "prices": prices.astype(object).where(prices.notna(), None).to_dict("split")})
    state = "INSUFFICIENT_DATA" if not complete else "READY" if quality["status"] == "PASSED" else "DATA_QUALITY_BLOCKED"
    identity = digest({"strategy": strategy, "version": VERSION, "decision": decision.isoformat(),
                       "config": config.hash, "basis": basis, "status": state, "mode": research_mode})
    end = calendar.next(day, config.execution_window_sessions or 5)
    return Signal(identity, strategy, VERSION, snapshot_id, basis, config.hash, decision.isoformat(),
                  now_utc(), str(day.date()), str(eligible.date()), str(end.date()),
                  weights, reasons, state, research_mode)


def history(frame, calendar, config, strategy, snapshot_id) -> list[Signal]:
    result = []
    for session in calendar.month_ends():
        if config.evaluation_start <= str(session.date()) <= config.evaluation_end:
            try:
                result.append(signal(frame, calendar, config, session, strategy, snapshot_id))
            except QuantError as exc:
                if exc.code != "CALENDAR_RANGE":
                    raise
    return result
