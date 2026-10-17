from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import date
from pathlib import Path
import json
import tomllib

from .common import QuantError, digest, finite_float


@dataclass(frozen=True)
class Config:
    schema_version: int = 1
    environment: str = "demo"
    market: str = "XNYS"
    currency: str = "USD"
    symbols: tuple[str, ...] = ("SPY", "IEF", "GLD")
    weights: tuple[float, ...] = (1 / 3, 1 / 3, 1 / 3)
    lookback: int = 126
    active_strategy: str = "trend"
    research_capital: float = 10000
    demo_deposit: float | None = None
    commission_bps: float | None = None
    slippage_bps: float | None = None
    fixed_fee: float | None = None
    max_weight: float | None = None
    cash_buffer: float | None = None
    lot_size: float | None = None
    execution_window_sessions: int | None = None
    settlement_lag_sessions: int | None = None
    publication_delay_minutes: int | None = None
    reference_deviation: float | None = None
    price_jump_threshold: float | None = None
    reconciliation_max_days: int | None = None
    reconciliation_cash_tolerance: float | None = None
    reconciliation_quantity_tolerance: float | None = None
    reconciliation_equity_tolerance: float | None = None
    download_attempts: int = 3
    download_timeout: int = 20
    evaluation_start: str = "2024-07-01"
    evaluation_end: str = "2024-12-31"
    development_start: str | None = None
    development_end: str | None = None
    volatility_annual_factor: int = 252
    runtime_dir: str = "runtime/demo"
    strategy_spec: dict | None = None
    supplied: frozenset[str] = field(default_factory=frozenset, repr=False)

    @classmethod
    def load(cls, path: str | Path) -> Config:
        path = Path(path)
        text = path.read_text(encoding="utf-8")
        return cls.from_dict(json.loads(text) if text.lstrip().startswith("{") else tomllib.loads(text))

    @classmethod
    def from_dict(cls, raw) -> Config:
        if not isinstance(raw, dict):
            raise QuantError("INVALID_CONFIG", "配置必须是对象")
        raw = dict(raw)
        unknown = set(raw) - {f.name for f in fields(cls) if f.name != "supplied"}
        if unknown:
            raise QuantError("INVALID_CONFIG", f"未知配置项：{sorted(unknown)}")
        for name in ("symbols", "weights"):
            if name in raw:
                raw[name] = tuple(raw[name])
        config = cls(**raw, supplied=frozenset(raw))
        config.validate()
        return config

    def validate(self) -> None:
        if self.schema_version != 1 or self.environment not in {"demo", "paper", "real"}:
            raise QuantError("INVALID_CONFIG", "schema_version 或运行环境不受支持")
        if self.market != "XNYS" or self.currency != "USD":
            raise QuantError("UNSUPPORTED_MARKET", "V1 当前仅支持 XNYS / USD；不可隐式换算币种")
        if not self.symbols or len(set(self.symbols)) != len(self.symbols):
            raise QuantError("INVALID_CONFIG", "标的不能为空或重复")
        if any(not isinstance(s, str) or not s or not s.isascii() for s in self.symbols):
            raise QuantError("INVALID_CONFIG", "标的必须为非空 ASCII 标识")
        if any(isinstance(w, bool) for w in self.weights):
            raise QuantError("INVALID_WEIGHTS", "权重不能是布尔值")
        weights = [finite_float(w) for w in self.weights]
        if len(weights) != len(self.symbols) or min(weights) < 0 or sum(weights) > 1 + 1e-10:
            raise QuantError("INVALID_WEIGHTS", "权重必须非负、与标的一致且总和不超过 1")
        if not isinstance(self.lookback, int) or self.lookback < 2:
            raise QuantError("INVALID_CONFIG", "趋势窗口至少为 2")
        if self.strategy_spec is None:
            if self.active_strategy not in {"fixed", "trend"}:
                raise QuantError("INVALID_CONFIG", "新策略需要完整冻结的strategy_spec")
        else:
            from .strategies.spec import StrategySpec
            spec = StrategySpec.from_dict(self.strategy_spec)
            body = spec.content()
            if (self.active_strategy != spec.template_id or self.symbols != spec.symbols
                    or self.weights != tuple(body["weights"].get(s, 0.) for s in spec.symbols)
                    or self.lookback != max(2, spec.required_prices)
                    or self.publication_delay_minutes != body["publication_delay_minutes"]
                    or self.price_jump_threshold != body["price_jump_threshold"]):
                raise QuantError("STRATEGY_CONFIG_CONFLICT", "配置字段与冻结策略规格冲突，请使用共享规格解析入口")
        for name in ("commission_bps", "slippage_bps", "fixed_fee", "max_weight", "cash_buffer", "lot_size", "reference_deviation", "price_jump_threshold",
                     "reconciliation_cash_tolerance", "reconciliation_quantity_tolerance", "reconciliation_equity_tolerance"):
            value = getattr(self, name)
            if isinstance(value, bool):
                raise QuantError("INVALID_CONFIG", f"{name} 必须是数值，不能是布尔值")
            if value is not None and finite_float(value) < 0:
                raise QuantError("INVALID_CONFIG", f"{name} 不能为负")
        if self.price_jump_threshold is not None and (isinstance(self.price_jump_threshold, bool) or self.price_jump_threshold <= 0):
            raise QuantError("INVALID_CONFIG", "price_jump_threshold 必须为有限正数，以收益比例表示")
        if isinstance(self.research_capital, bool) or finite_float(self.research_capital) <= 0:
            raise QuantError("INVALID_CONFIG", "研究资金必须为正，不代表实际入金")
        if self.demo_deposit is not None and (isinstance(self.demo_deposit, bool) or finite_float(self.demo_deposit) <= 0):
            raise QuantError("INVALID_CONFIG", "demo_deposit 必须是有限正数，仅代表测试入金")
        for name in ("lookback", "download_attempts", "download_timeout", "execution_window_sessions", "settlement_lag_sessions", "publication_delay_minutes", "reconciliation_max_days", "volatility_annual_factor"):
            value = getattr(self, name)
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < (0 if name in {"settlement_lag_sessions", "publication_delay_minutes"} else 1)):
                raise QuantError("INVALID_CONFIG", f"{name} 必须是合法整数")
        if self.max_weight is not None and not 0 < self.max_weight <= 1:
            raise QuantError("INVALID_CONFIG", "max_weight 必须在 (0,1] 内")
        if self.cash_buffer is not None and not 0 <= self.cash_buffer < 1:
            raise QuantError("INVALID_CONFIG", "cash_buffer 必须在 [0,1) 内")
        if self.lot_size is not None and self.lot_size <= 0:
            raise QuantError("INVALID_CONFIG", "交易单位必须为正")
        if self.download_attempts > 5:
            raise QuantError("INVALID_CONFIG", "下载最多尝试 5 次")
        for name in ("evaluation_start", "evaluation_end", "development_start", "development_end"):
            value = getattr(self, name)
            if value is not None:
                try:
                    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
                        raise ValueError
                except (TypeError, ValueError):
                    raise QuantError("INVALID_CONFIG", f"{name} 必须是 YYYY-MM-DD 日期") from None
        if self.evaluation_start >= self.evaluation_end:
            raise QuantError("INVALID_CONFIG", "评估区间起点必须早于终点")
        if (self.development_start is None) != (self.development_end is None):
            raise QuantError("INVALID_CONFIG", "开发区间起止日期须同时填写")
        if self.development_start is not None and not (
                self.development_start <= self.development_end < self.evaluation_start):
            raise QuantError("INVALID_CONFIG", "开发区间必须有序且完全早于最终评估区间")
        expected = Path("runtime") / self.environment
        if Path(self.runtime_dir) != expected:
            raise QuantError("ENVIRONMENT_MISMATCH", f"运行目录必须为 {expected}，防止跨环境写入")

    def require_execution(self) -> None:
        required = {"commission_bps", "slippage_bps", "fixed_fee", "max_weight", "cash_buffer", "lot_size", "execution_window_sessions", "settlement_lag_sessions", "publication_delay_minutes", "reference_deviation", "price_jump_threshold", "reconciliation_max_days",
                    "reconciliation_cash_tolerance", "reconciliation_quantity_tolerance", "reconciliation_equity_tolerance"}
        missing = sorted(k for k in required if getattr(self, k) is None or (self.environment == "real" and k not in self.supplied))
        if self.environment == "real" and "active_strategy" not in self.supplied:
            missing.append("active_strategy")
        if missing:
            raise QuantError("MISSING_EXECUTION_CONFIG", f"计划缺少明确配置：{missing}")

    def content(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self) if f.name != "supplied"
                and not (f.name == "strategy_spec" and self.strategy_spec is None)}

    @property
    def hash(self) -> str:
        return digest(self.content())
