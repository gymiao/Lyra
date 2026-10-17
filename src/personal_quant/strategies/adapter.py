"""Shared v1.5 decision boundary and backward-compatible signal decoding."""
from __future__ import annotations

from dataclasses import dataclass, field, fields, replace
import pandas as pd

from ..common import QuantError, digest, now_utc, utc
from ..data.quality import price_quality
from .monthly import Signal
from .spec import DataBundle, StrategySpec, number
from .templates import evaluate


@dataclass(frozen=True)
class VersionedSignal(Signal):
    schema_version: int = 2
    spec_hash: str = ""
    spec: dict = field(default_factory=dict)
    data_bundle: dict = field(default_factory=dict)
    scores: dict = field(default_factory=dict)


def decode_signal(body):
    if not isinstance(body, dict):
        raise QuantError("INVALID_SIGNAL", "信号内容必须是对象")
    version = body.get("schema_version", 1)
    cls = Signal if version == 1 else VersionedSignal if version == 2 else None
    if cls is None or isinstance(version, bool):
        raise QuantError("UNKNOWN_SIGNAL_SCHEMA", "不支持的信号记录版本")
    payload = dict(body)
    if cls is Signal:
        payload.pop("schema_version", None)
    try:
        result = cls(**payload)
    except TypeError as exc:
        raise QuantError("INVALID_SIGNAL", "信号字段与记录版本不一致") from exc
    if cls is VersionedSignal:
        spec = StrategySpec.from_dict(result.spec)
        if result.spec_hash != spec.spec_hash or result.strategy != spec.template_id or result.version != spec.content()["implementation_version"]:
            raise QuantError("CORRUPT_SIGNAL", "冻结信号与策略规格不匹配")
        bundle = DataBundle(**result.data_bundle)
        if result.snapshot_id != bundle.signal_snapshot_id:
            raise QuantError("CORRUPT_SIGNAL", "信号价格快照身份不匹配")
        if result.status == "READY":
            if not isinstance(result.target_weights, dict) or set(result.target_weights) != set(spec.symbols):
                raise QuantError("CORRUPT_SIGNAL", "有效信号缺少完整目标权重")
            value = spec.content()
            weights = [number(w, "信号目标权重", 0, value["weight_cap"]) for w in result.target_weights.values()]
            if sum(weights) > value["invested_budget"] + 1e-10:
                raise QuantError("CORRUPT_SIGNAL", "信号目标权重超过冻结预算")
        elif result.target_weights is not None:
            raise QuantError("CORRUPT_SIGNAL", "受阻信号不能带可执行权重")
    return result


@dataclass(frozen=True)
class ResolvedStrategyContext:
    config: object
    spec: StrategySpec | None


def resolve(config, spec=None):
    config.validate()
    embedded = getattr(config, "strategy_spec", None)
    if spec is not None and not isinstance(spec, StrategySpec):
        spec = StrategySpec.from_dict(spec)
    if embedded:
        frozen = StrategySpec.from_dict(embedded)
        if spec and frozen.spec_hash != spec.spec_hash:
            raise QuantError("STRATEGY_CONFIG_CONFLICT", "显式策略与配置中冻结规格不同")
        spec = frozen
    if spec is None:
        config.validate()
        return ResolvedStrategyContext(config, None)
    value = spec.content()
    adapted = replace(config, symbols=spec.symbols, weights=tuple(value["weights"].get(s, 0.) for s in spec.symbols),
        active_strategy=spec.template_id, lookback=max(2, spec.required_prices),
        publication_delay_minutes=value["publication_delay_minutes"], price_jump_threshold=value["price_jump_threshold"],
        strategy_spec=spec.export())
    adapted.validate()
    return ResolvedStrategyContext(adapted, spec)


def signal_v2(frame, calendar, config, spec, session, bundle, *, decision_time=None,
              research_mode="historical_reconstruction", account_state=None, factor_values=None, factor_error=None):
    spec = StrategySpec.from_dict(spec.export())
    if research_mode not in {"historical_reconstruction", "forward"}:
        raise QuantError("INVALID_MODE", "信号用途无效")
    day = pd.Timestamp(session).normalize().tz_localize(None)
    if day not in calendar.month_ends():
        raise QuantError("NOT_REBALANCE_DAY", "不是已确认的月末交易日")
    if calendar.hash != bundle.calendar_hash:
        raise QuantError("INVALID_DATA_BUNDLE", "数据包与决策日历不匹配")
    delay = spec.content()["publication_delay_minutes"]
    cutoff = calendar.close(day) + pd.Timedelta(minutes=delay)
    instant = pd.Timestamp(utc(decision_time)) if decision_time else cutoff
    if instant < cutoff:
        raise QuantError("FUTURE_DATA", "信号早于完整日线发布时点")
    eligible = calendar.next(day)
    if research_mode == "forward" and (instant >= calendar.close(eligible) or utc(now_utc()) >= calendar.close(eligible).to_pydatetime()):
        raise QuantError("EXPIRED_SIGNAL", "信号已错过适用交易时点")
    if account_state is not None and ("as_of" not in account_state or utc(account_state["as_of"]) > instant.to_pydatetime()):
        raise QuantError("FUTURE_ACCOUNT_STATE", "账户状态不能晚于决策时点")
    end = calendar.next(day, config.execution_window_sessions or 5)
    pos = calendar.sessions.get_loc(day)
    window = calendar.sessions[max(0, pos - spec.required_prices + 1):pos + 1]
    available = frame.loc[(frame.session_date.isin(window)) & (frame.available_at <= instant) & frame.symbol.isin(spec.symbols)]
    prices = available.pivot(index="session_date", columns="symbol", values="adj_close").reindex(index=window, columns=spec.symbols)
    state, weights, reasons, scores = "READY", None, {}, {}
    try:
        from ..data.readiness import history_readiness
        readiness = history_readiness(frame, calendar, spec.symbols, day, instant.isoformat(), spec.required_prices)
        if readiness['status'] != 'PASSED':
            raise QuantError("INSUFFICIENT_DATA", f"需要{spec.required_prices}个完整且已发布的价格观测")
        quality = price_quality(frame, calendar, config, spec.symbols, day, instant.isoformat(), start_session=window[0], adjusted=True)
        if quality["status"] != "PASSED":
            raise QuantError("DATA_QUALITY_BLOCKED", f"价格质量不通过：{quality['issues']}")
        if factor_error is not None:
            raise factor_error
        weights, reasons, scores = evaluate(prices, spec, factor_values)
    except QuantError as exc:
        state = "INSUFFICIENT_DATA" if exc.code == "INSUFFICIENT_DATA" else "DATA_QUALITY_BLOCKED"
        weights = None
        reasons = {s: f"{exc.code}: {exc}" for s in spec.symbols}
    basis = digest({"dates": [str(d.date()) for d in window], "symbols": list(spec.symbols),
        "prices": prices.astype(object).where(prices.notna(), None).to_dict("split"),
        "factors": factor_values.to_dict("split") if factor_values is not None else None,
        "factor_evidence": factor_values.attrs.get("evidence") if factor_values is not None else None})
    identity = digest({"spec_hash": spec.spec_hash, "basis_hash": basis, "decision_time": instant.isoformat(),
                       "status": state, "weights": weights, "mode": research_mode})
    return VersionedSignal(identity, spec.template_id, spec.content()["implementation_version"],
        bundle.signal_snapshot_id, basis, config.hash, instant.isoformat(), now_utc(), str(day.date()),
        str(eligible.date()), str(end.date()), weights, reasons, state, research_mode,
        spec_hash=spec.spec_hash, spec=spec.export(), data_bundle=bundle.content(), scores=scores)


def history_v2(frame, calendar, config, spec, bundle, *, factor_selector=None):
    config = resolve(config, spec).config
    result = []
    for session in calendar.month_ends():
        if config.evaluation_start <= str(session.date()) <= config.evaluation_end:
            factors, error = None, None
            if factor_selector and spec.template_id == "multi_factor" and spec.content()["parameters"]["mode"] == "fundamental":
                try:
                    cutoff = calendar.close(session) + pd.Timedelta(minutes=spec.content()["publication_delay_minutes"])
                    factors = factor_selector(spec, cutoff.isoformat())
                except QuantError as exc:
                    error = exc
            result.append(signal_v2(frame, calendar, config, spec, session, bundle, factor_values=factors, factor_error=error))
    return result
