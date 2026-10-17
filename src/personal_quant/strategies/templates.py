"""Six deterministic monthly, long-only rules; no prices are fetched and no money is written."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..common import QuantError
from .registry import Definition, Parameter as P, register


def _weights(spec):
    return dict(spec.content()["weights"])


def fixed(prices, spec, factors=None):
    return _weights(spec), {s: "月度固定权重再平衡" for s in spec.symbols}, {}


def trend(prices, spec, factors=None):
    cfg = spec.content()
    last, average = prices.iloc[-1], prices.tail(cfg["parameters"]["lookback"]).mean()
    weights, reasons, scores = {}, {}, {}
    for s in spec.symbols:
        weights[s] = cfg["weights"][s] if last[s] > average[s] else 0.0
        scores[s] = float(last[s] / average[s] - 1)
        reasons[s] = f"收盘 {last[s]:.6f} {'>' if last[s] > average[s] else '<='} 均线 {average[s]:.6f}；{'保留基础权重' if weights[s] else '留作现金'}"
    return weights, reasons, scores


def momentum(prices, spec, factors=None):
    cfg = spec.content(); p = cfg["parameters"]
    scores = (prices.iloc[-1] / prices.iloc[-p["lookback"] - 1] - 1).to_dict()
    winners = sorted((s for s in spec.symbols if scores[s] > 0), key=lambda s: (-scores[s], s))[:p["top_k"]]
    weights = {s: cfg["invested_budget"] / p["top_k"] if s in winners else 0.0 for s in spec.symbols}
    return weights, {s: f"{p['lookback']}日收益 {scores[s]:.6%}；{'入选' if s in winners else '未入选或收益非正'}" for s in spec.symbols}, scores


def reversion(prices, spec, factors=None):
    cfg = spec.content(); p = cfg["parameters"]
    scores = (prices.iloc[-1] / prices.tail(p["lookback"]).mean() - 1).to_dict()
    weights = {s: cfg["weights"][s] if scores[s] <= -p["threshold"] else 0.0 for s in spec.symbols}
    return weights, {s: f"均线偏离 {scores[s]:.6%}；阈值 {-p['threshold']:.6%}；{'持有基础权重' if weights[s] else '留作现金'}" for s in spec.symbols}, scores


def inverse_volatility(prices, spec, factors=None):
    cfg = spec.content(); p = cfg["parameters"]
    sigma = prices.pct_change(fill_method=None).tail(p["lookback"]).std(ddof=1)
    if (~np.isfinite(sigma)).any() or (sigma <= 1e-8).any():
        raise QuantError("ZERO_VOLATILITY", "波动率非有限或过低，不能使用倒数权重")
    raw = (1 / sigma) / (1 / sigma).sum() * cfg["invested_budget"]
    return raw.to_dict(), {s: f"日收益样本波动率 {sigma[s]:.6%}；按倒数分配" for s in spec.symbols}, sigma.to_dict()


def multi_factor(prices, spec, factors=None):
    cfg = spec.content(); p = cfg["parameters"]
    if p["mode"] == "prices":
        first = prices.iloc[-1] / prices.iloc[-p["momentum_lookback"] - 1] - 1
        second = -prices.pct_change(fill_method=None).tail(p["volatility_lookback"]).std(ddof=1)
    else:
        if factors is None or set(factors.index) != set(spec.symbols) or not {"book_to_market", "roe_ttm"} <= set(factors.columns):
            raise QuantError("MISSING_FACTORS", "价值/质量策略需要完整且已通过时点校验的因子")
        first, second = factors.loc[list(spec.symbols), "book_to_market"], factors.loc[list(spec.symbols), "roe_ttm"]
        if (first <= 0).any():
            raise QuantError("INVALID_FACTORS", "book_to_market必须为正；非正权益不能参与价值排名")
    if not np.isfinite(first).all() or not np.isfinite(second).all():
        raise QuantError("MISSING_FACTORS", "因子存在缺失或非有限值")
    ranks_a = (first.rank(method="average") - 1) / (len(first) - 1)
    ranks_b = (second.rank(method="average") - 1) / (len(second) - 1)
    scores = (p["first_factor_weight"] * ranks_a + (1 - p["first_factor_weight"]) * ranks_b).to_dict()
    winners = sorted(spec.symbols, key=lambda s: (-scores[s], s))[:p["top_k"]]
    weights = {s: cfg["invested_budget"] / p["top_k"] if s in winners else 0.0 for s in spec.symbols}
    return weights, {s: f"因子秩分 {ranks_a[s]:.4f}/{ranks_b[s]:.4f}；综合 {scores[s]:.4f}；{'入选' if s in winners else '未入选'}" for s in spec.symbols}, scores


def install():
    register(Definition("fixed", "固定配置", "每月恢复显式基础权重。", {}, lambda p: 1, fixed))
    register(Definition("trend", "趋势跟随", "月末收盘严格高于均线才保留基础权重。",
        {"lookback": P("均线交易日", "int", 126, 2, 2520)}, lambda p: p["lookback"], trend))
    register(Definition("momentum_rotation", "动量轮动", "按历史收益选前K个正收益标的，未填满名额留现金。",
        {"lookback": P("收益交易日", "int", 126, 1, 2520), "top_k": P("入选数量", "int", 2, 1, 1000)},
        lambda p: p["lookback"] + 1, momentum))
    register(Definition("mean_reversion", "均值回归", "月末负偏离达到阈值时持有，次月重新判断。",
        {"lookback": P("均线交易日", "int", 20, 2, 2520), "threshold": P("负偏离比例", "float", .05, 0, .99)},
        lambda p: p["lookback"], reversion))
    register(Definition("inverse_volatility", "波动率倒数配置", "按收益样本标准差倒数配置，不等同严格风险平价。",
        {"lookback": P("收益交易日", "int", 63, 2, 2520)}, lambda p: p["lookback"] + 1, inverse_volatility))
    register(Definition("multi_factor", "多因子", "两个因子的平均秩加权；价值/质量模式要求时点因子。",
        {"mode": P("因子模式", "choice", "prices", choices=("prices", "fundamental")),
         "momentum_lookback": P("动量交易日", "int", 126, 1, 2520),
         "volatility_lookback": P("波动交易日", "int", 63, 2, 2520),
         "top_k": P("入选数量", "int", 2, 1, 1000),
         "first_factor_weight": P("第一个因子系数", "float", .5, 0, 1),
         "max_report_age_days": P("最长财报年龄(日)", "int", 180, 1, 3650),
         "max_value_age_days": P("最长因子估值年龄(日)", "int", 7, 0, 3650)},
         lambda p: max(p["momentum_lookback"], p["volatility_lookback"]) + 1 if p["mode"] == "prices" else 1, multi_factor))


def evaluate(prices, spec, factors=None):
    from .registry import definition
    prices = prices.reindex(columns=spec.symbols)
    if len(prices) < spec.required_prices or not np.isfinite(prices.to_numpy(dtype=float)).all() or (prices <= 0).any().any():
        raise QuantError("INSUFFICIENT_DATA", "缺少完整正价格或策略预热不足")
    weights, reasons, scores = definition(spec.template_id).compute(prices, spec, factors)
    cfg = spec.content()
    if set(weights) != set(spec.symbols) or any(not np.isfinite(x) or x < 0 for x in weights.values()) or sum(weights.values()) > cfg["invested_budget"] + 1e-10:
        raise QuantError("INVALID_WEIGHTS", "策略输出权重非法")
    for symbol, weight in weights.items():
        if weight > cfg["weight_cap"]:
            weights[symbol] = cfg["weight_cap"]
            reasons[symbol] += f"；原权重{weight:.6f}按上限裁剪，余量留现金"
    return {s: float(w) for s, w in weights.items()}, reasons, {s: float(x) for s, x in scores.items()}
