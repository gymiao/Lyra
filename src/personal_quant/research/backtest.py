from __future__ import annotations

import hashlib
import importlib.metadata
import math
import os
from pathlib import Path
import subprocess
from uuid import uuid4
import pandas as pd

from ..common import QuantError, digest, now_utc, write_json
from ..config import Config
from ..data.store import DataStore
from ..data.quality import price_quality, require_quality
from ..strategies import history


def run_research(store: DataStore, config: Config, report_root: Path, snapshot_id=None, *,
                 members=None, benchmark=None, bundle=None, factor_selector=None,
                 execution_id=None, publish_latest=True, research_context=None, defer_publication=False) -> dict:
    config.validate()
    try:
        import bt
        import ffn
    except ImportError as exc:
        raise QuantError("MISSING_BACKTEST_DEPENDENCY", "bt / ffn 尚未安装；不能将信号演示冒充已完成回测") from exc
    if any(getattr(config, k) is None for k in ["commission_bps", "slippage_bps", "fixed_fee"]):
        raise QuantError("MISSING_COST_CONFIG", "研究必须明确费用及滑点")
    data, meta, calendar = store.load(snapshot_id) if snapshot_id else store.load_role("signal")
    if members is None:
        signals = {name: history(data, calendar, config, name, meta["snapshot_id"]) for name in ["fixed", "trend"]}
        benchmark = "fixed"
    else:
        from ..strategies.adapter import history_v2
        from ..strategies.spec import DataBundle, ID
        if not isinstance(members, dict) or not 2 <= len(members) <= 7 or benchmark not in members:
            raise QuantError("INVALID_EXPERIMENT", "实验需要基准和1至6个候选，成员ID必须唯一")
        if any(not isinstance(name, str) or not ID.fullmatch(name) for name in members):
            raise QuantError("INVALID_EXPERIMENT", "实验成员ID非法")
        if len({spec.spec_hash for spec in members.values()}) != len(members):
            raise QuantError("DUPLICATE_EXPERIMENT_MEMBER", "同一冻结规格不能重复加入实验")
        if any(set(spec.symbols) != set(config.symbols) for spec in members.values()):
            raise QuantError("INCOMPARABLE_UNIVERSE", "正式比较需要相同篮子")
        bundle = bundle or DataBundle(meta["snapshot_id"], calendar.hash)
        if bundle.signal_snapshot_id != meta["snapshot_id"] or bundle.calendar_hash != calendar.hash:
            raise QuantError("INVALID_DATA_BUNDLE", "研究必须加载实验冻结的价格快照和日历")
        signals = {name: history_v2(data, calendar, config, spec, bundle, factor_selector=factor_selector)
                   for name, spec in members.items()}
        blocked = {name: [{"session": item.decision_session, "status": item.status, "reasons": item.reasons}
                         for item in items if item.status != "READY"] for name, items in signals.items()}
        if any(blocked.values()):
            from ..common import canonical
            raise QuantError("INCOMPLETE_RESEARCH_DATA", "实验存在受阻月份，不能跳过后发布完整比较：" + canonical(blocked))
    dates = calendar.sessions[(calendar.sessions >= config.evaluation_start) & (calendar.sessions <= config.evaluation_end)]
    prices = data.pivot(index="session_date", columns="symbol", values="adj_close").reindex(index=dates, columns=config.symbols)
    if prices.empty or prices.isna().any().any():
        raise QuantError("INCOMPLETE_RESEARCH_DATA", "评估区间价格缺失，不能填充或删掉日期后继续回测")
    quality = price_quality(data, calendar, config, config.symbols, dates[-1],
        (calendar.close(dates[-1]) + pd.Timedelta(minutes=config.publication_delay_minutes or 0)).isoformat(),
        start_session=dates[0], adjusted=True)
    require_quality(quality)
    if any(not any(s.status == "READY" and pd.Timestamp(s.eligible_session) in dates for s in items) for items in signals.values()):
        raise QuantError("INSUFFICIENT_DATA", "评估区间没有双方共同的有效调仓信号")
    rate = (config.commission_bps + config.slippage_bps) / 10000
    fee = config.fixed_fee

    class ScheduledWeights(bt.Algo):
        def __init__(self, items):
            super().__init__()
            self.by_session = {pd.Timestamp(s.eligible_session): s.target_weights for s in items if s.status == "READY"}

        def __call__(self, target):
            weights = self.by_session.get(target.now)
            if weights is None:
                return False
            target.perm.setdefault("pre_trade_equity", {})[target.now] = float(target.value)
            # Upper bound for buy+sell notional and fixed charges; guarantees a fee reserve.
            reserve = min(1.0, 2 * rate + fee * len(config.symbols) / max(target.value, 1e-12))
            target.temp["weights"] = {symbol: weight * (1 - reserve) for symbol, weight in weights.items()}
            return True

    def commission(quantity, price):
        return abs(quantity * price) * rate + (fee if abs(quantity) > 1e-12 else 0)

    backtests = [bt.Backtest(bt.Strategy(name, [ScheduledWeights(signals[name]), bt.algos.Rebalance()]),
                            prices, initial_capital=config.research_capital, commissions=commission,
                            integer_positions=False, progress_bar=False) for name in signals]
    results = bt.run(*backtests)
    run_id = execution_id or uuid4().hex
    if len(run_id) != 32 or any(c not in "0123456789abcdef" for c in run_id):
        raise QuantError("INVALID_RUN_ID", "运行ID必须为32位十六进制")
    report_root.mkdir(parents=True, exist_ok=True)
    pending = report_root / (".pending-" + run_id)
    pending.mkdir()
    # bt adds an initialization row before the supplied range. Exclude it from
    # observation dates, while retaining the configured capital as normalization.
    nav = pd.DataFrame({b.name: b.strategy.values for b in backtests}).reindex(prices.index)
    if nav.isna().any().any():
        raise QuantError("INCOMPLETE_BACKTEST_RESULT", "回测净值未覆盖共同评估区间")
    if not all(b.strategy.cash.reindex(prices.index).notna().all()
               and b.strategy.cash.reindex(prices.index).ge(-1e-6).all() for b in backtests):
        raise QuantError("BACKTEST_CASH", "回测出现负现金，费用口径需修复")
    nav.to_csv(pending / "nav.csv", index_label="date")
    normalized = nav / config.research_capital
    # Include bt's initial capital baseline for metrics, without presenting that
    # initialization row as an observed market price or extra trading session.
    baseline_date = prices.index[0] - pd.Timedelta(days=1)
    performance = pd.concat([pd.DataFrame(1.0, index=[baseline_date], columns=normalized.columns), normalized])
    drawdowns = performance.apply(ffn.to_drawdown_series).reindex(prices.index)
    drawdowns.to_csv(pending / "drawdowns.csv", index_label="date")
    metrics, all_trades, contributions = {}, [], {}
    for backtest in backtests:
        series = performance[backtest.name]
        stats = ffn.calc_stats(series, annualization_factor=config.volatility_annual_factor)
        # bt 1.3.0 indexes the first security row when building transactions.
        # A valid all-cash strategy has no security columns; preserve an empty
        # blotter rather than asking that API to index a nonexistent child.
        trade = (pd.DataFrame(columns=["Date", "Security", "quantity", "price"])
                 if backtest.strategy.positions.empty
                 else results.get_transactions(backtest.name).reset_index())
        trade["strategy"] = backtest.name
        trade["notional"] = (trade.quantity * trade.price).abs()
        trade["commission"] = trade.notional * config.commission_bps / 10000 + fee
        trade["slippage_cost"] = trade.notional * config.slippage_bps / 10000
        trade["total_cost"] = trade.commission + trade.slippage_cost
        trade["pre_trade_equity"] = trade.iloc[:, 0].map(backtest.strategy.perm.get("pre_trade_equity", {}))
        if trade.pre_trade_equity.isna().any() or (trade.pre_trade_equity <= 0).any():
            raise QuantError("INCOMPLETE_BACKTEST_RESULT", "成交缺少有效的当日调仓前权益，不能推算换手率")
        all_trades.append(trade)
        backtest.security_weights.to_csv(pending / f"{backtest.name}_weights.csv", index_label="date")
        backtest.strategy.positions.to_csv(pending / f"{backtest.name}_positions.csv", index_label="date")
        from .contributions import contribution_bridge
        positions=backtest.strategy.positions.reindex(index=prices.index,columns=prices.columns,fill_value=0.)
        daily_contribution,contributions[backtest.name]=contribution_bridge(prices,positions,nav[backtest.name],trade,config.research_capital)
        daily_contribution.to_csv(pending/f'{backtest.name}_contributions.csv',index_label='date')
        turnover = 0.0
        if not trade.empty:
            for date, group in trade.groupby(trade.columns[0]):
                value = group.pre_trade_equity.iloc[0]
                turnover += float(group.notional.sum() / (2 * value))
        def numeric(value):
            return float(value) if value is not None and math.isfinite(float(value)) else None
        metrics[backtest.name] = {"total_return": numeric(stats.total_return), "annual_return": numeric(stats.cagr),
                                  "max_drawdown": numeric(stats.max_drawdown), "annual_volatility": numeric(stats.daily_vol),
                                  "cost": float(trade.total_cost.sum()), "turnover": turnover,
                                  "initial_capital": config.research_capital, "observations": len(prices),
                                  "calendar_days": int((prices.index[-1] - baseline_date).days),
                                  "short_sample_annualization": (prices.index[-1] - baseline_date).days < 365,
                                  "buy_notional": float(trade.loc[trade.quantity > 0, "notional"].sum()),
                                  "sell_notional": float(trade.loc[trade.quantity < 0, "notional"].sum()),
                                  "start": str(prices.index[0].date()), "end": str(prices.index[-1].date())}
    populated = [table for table in all_trades if not table.empty]
    (pd.concat(populated) if populated else all_trades[0]).to_csv(pending / "trades.csv", index=False)
    from .slices import continuous_slices
    trades_for_slices=pd.concat(populated,ignore_index=True) if populated else all_trades[0]
    write_json(pending/"continuous-slices.json",continuous_slices(nav,trades_for_slices,config.research_capital,config.volatility_annual_factor))
    from .contributions import rolling_comparison
    write_json(pending/'contributions.json',contributions)
    write_json(pending/'rolling.json',rolling_comparison(nav,benchmark,annual_factor=config.volatility_annual_factor))
    write_json(pending / "signals.json", {k: [s.content() for s in v] for k, v in signals.items()})
    source_root = Path(__file__).resolve().parents[1]
    source_hash = digest({str(p.relative_to(source_root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(source_root.rglob("*.py"))})
    try:
        revision = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True)
        git_head = revision.stdout.strip() if revision.returncode == 0 else None
        status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
        dirty = bool(status.stdout.strip()) if status.returncode == 0 else None
    except FileNotFoundError:
        git_head, dirty = None, None  # Source fingerprint remains available without Git.
    manifest = {"run_id": run_id, "data_type": meta["data_type"], "activity": "historical_backtest",
                "research_protocol": {"development_start": config.development_start,
                    "development_end": config.development_end,
                    "evaluation_start": config.evaluation_start, "evaluation_end": config.evaluation_end,
                    "parameter_selection": "configured_fixed_rules_no_automatic_search",
                    "temporal_split_declared": config.development_start is not None},
                "snapshot_id": meta["snapshot_id"], "config": config.content(), "config_hash": config.hash,
                "source_hash": source_hash, "git_head": git_head, "dirty_worktree": dirty,
                "dependencies": {k: importlib.metadata.version(k) for k in ["bt", "ffn", "pandas", "numpy"]},
                "generated_at": now_utc(), "metrics": metrics,
                "data_quality": quality,
                "assumptions": {"signal": "月末收盘后", "execution": "下一交易日收盘，成交前收益归旧持仓",
                                "price": "复权抽象份额；不额外计分红", "slippage": "按成交金额等价成本扣减",
                                "cash_interest": 0, "volatility_annual_factor": config.volatility_annual_factor,
                                "metrics_baseline": "评估首日前一自然日的初始资金，仅用于收益、回撤及年化基线，不是行情或成交",
                                "annual_return": "ffn CAGR；基线至末日的实际自然日数，包含评估首日",
                                "turnover": "逐次买卖金额绝对值之和 / (2 × 当日成交前权益)，包含首次建仓",
                                "historical_availability_assumed": meta["historical_availability_assumed"]}}
    if members is not None:
        manifest.update({"schema_version": 2, "benchmark_member_id": benchmark,
            "members": {name: spec.export() for name, spec in members.items()}, "data_bundle": bundle.content(),
            "research_context": research_context or {"purpose": "exploratory", "evaluation_seen": True},
            "completeness": "COMPLETE", "cash_policy": "strategy_budget_once_then_legacy_bt_fee_reserve_v1"})
        if research_context and research_context.get("contains_test_factors"):
            manifest["data_type"] = "mixed_test_factors"
        for name, m in metrics.items():
            cash = backtests[list(signals).index(name)].strategy.cash.reindex(prices.index)
            m["average_cash_weight"] = float((cash / nav[name]).mean())
    report = ["# LyraX 策略研究报告", "", f"数据：{manifest['data_type']} / 历史回测；截至 {meta['end']}；展示时区 Asia/Shanghai。", "",
              "复权份额不等同于实际证券份额；示例不代表投资建议。短于一年的年化数值须谨慎解释。", "",
              "| 策略 | 累计收益 | 年化收益 | 最大回撤 | 年化波动 | 成本 | 换手 |", "|---|---|---|---|---|---|---|"]
    for name, m in metrics.items():
        fmt = lambda x: "无有效值" if x is None else f"{x:.2%}"
        report.append(f"| {name} | {fmt(m['total_return'])} | {fmt(m['annual_return'])} | {fmt(m['max_drawdown'])} | {fmt(m['annual_volatility'])} | {m['cost']:.2f} USD | {fmt(m['turnover'])} |")
    report += ["", f"运行 ID：{run_id}", f"观察区间：{prices.index[0].date()} 至 {prices.index[-1].date()}；年化计时 {metrics[benchmark]['calendar_days']} 个自然日。",
               f"开发检查区间：{config.development_start or '未配置（无自动调参）'} 至 {config.development_end or '未配置'}；参数由配置固定，不自动根据最终评估收益选择。",
               "收益与回撤以评估前初始资金为基线，包含首日费用；初始化基线不计作行情观察或成交。",
               f"日收益波动率年化因子：{config.volatility_annual_factor}；现金收益为0。",
               "", "完整参数、内容哈希及成交假设见 manifest.json；交易、持仓和净值见同目录 CSV。"]
    (pending / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    manifest["files"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(pending.iterdir())}
    write_json(pending / "manifest.json", manifest)
    if defer_publication:
        return manifest
    os.replace(pending, report_root / run_id)
    if publish_latest:
        write_json(report_root / "latest.json", {"run_id": run_id})
    return manifest
