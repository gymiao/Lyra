from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..common import QuantError, decimal as D, digest


@dataclass(frozen=True)
class ReconciliationRules:
    """Comparison tolerances never round or rewrite ledger facts."""

    cash: Decimal = Decimal("0.01")
    quantity: Decimal = Decimal("0.00000001")
    equity: Decimal = Decimal("0.01")

    def __post_init__(self):
        for name in ("cash", "quantity", "equity"):
            raw = getattr(self, name)
            if isinstance(raw, bool):
                raise QuantError("INVALID_RECONCILIATION_RULES", "对账容差不能是布尔值")
            value = D(raw)
            if value < 0:
                raise QuantError("INVALID_RECONCILIATION_RULES", "对账容差必须是有限非负数")
            object.__setattr__(self, name, value)

    def content(self):
        return {"schema_version": 1, **{k: format(getattr(self, k).normalize(), "f") for k in ("cash", "quantity", "equity")}}

    @property
    def hash(self):
        return digest(self.content())

    @classmethod
    def from_config(cls, config):
        names = {name: f"reconciliation_{name}_tolerance" for name in ("cash", "quantity", "equity")}
        missing = [field for field in names.values() if getattr(config, field) is None or
                   (config.environment == "real" and field not in config.supplied)]
        if missing:
            raise QuantError("MISSING_RECONCILIATION_CONFIG", f"对账缺少明确容差配置：{missing}")
        return cls(**{name: getattr(config, field) for name, field in names.items()})
