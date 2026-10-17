"""Canonical immutable strategy specifications. Display names are not calculation identity."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import tomllib

from ..common import QuantError, canonical, digest, finite_float
from .registry import definition

ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}\Z")
HASH = re.compile(r"[a-f0-9]{64}\Z")


def number(value, label, minimum, maximum, *, positive=False):
    try:
        result = finite_float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise QuantError("INVALID_STRATEGY_SPEC", f"{label} 必须为有限数值") from exc
    if isinstance(value, bool) or not minimum <= result <= maximum or (positive and result == 0):
        raise QuantError("INVALID_STRATEGY_SPEC", f"{label} 超出允许范围")
    return result


@dataclass(frozen=True)
class StrategySpec:
    _json: str

    @classmethod
    def create(cls, template_id, symbols, *, strategy_id=None, name=None, parameters=None, weights=None,
               invested_budget=0.95, weight_cap=0.60, revision=1, publication_delay_minutes=30,
               price_jump_threshold=0.25):
        return cls.from_dict({"schema_version": 1, "strategy_id": strategy_id or template_id,
            "name": name or definition(template_id).name, "revision": revision, "template_id": template_id,
            "implementation_version": definition(template_id).version, "market": "XNYS", "currency": "USD",
            "symbols": list(symbols), "parameters": parameters or {}, "weights": weights,
            "invested_budget": invested_budget, "weight_cap": weight_cap,
            "publication_delay_minutes": publication_delay_minutes, "price_jump_threshold": price_jump_threshold,
            "universe_basis": "declared_static"})

    @classmethod
    def from_dict(cls, body):
        allowed = {"schema_version", "strategy_id", "name", "revision", "template_id", "implementation_version",
                   "market", "currency", "symbols", "parameters", "weights", "invested_budget", "weight_cap",
                   "publication_delay_minutes", "price_jump_threshold", "universe_basis", "spec_hash"}
        required = allowed - {"weights", "spec_hash"}
        if not isinstance(body, dict) or set(body) - allowed or required - set(body):
            raise QuantError("INVALID_STRATEGY_SPEC", "策略规格缺少字段或包含未知字段")
        try:
            value = json.loads(canonical(body))
        except (TypeError, ValueError, OverflowError) as exc:
            raise QuantError("INVALID_STRATEGY_SPEC", "策略参数必须是可序列化的有限数值及基础类型") from exc
        claimed = value.pop("spec_hash", None)
        if type(value["schema_version"]) is not int or value["schema_version"] != 1:
            raise QuantError("INVALID_STRATEGY_SPEC", "不支持的策略规格版本")
        if not isinstance(value["strategy_id"], str) or not ID.fullmatch(value["strategy_id"]):
            raise QuantError("INVALID_STRATEGY_SPEC", "策略ID仅允许字母、数字、下划线和连字符")
        if type(value["revision"]) is not int or value["revision"] < 1 or not isinstance(value["name"], str) or not value["name"].strip():
            raise QuantError("INVALID_STRATEGY_SPEC", "名称及修订号无效")
        if value["market"] != "XNYS" or value["currency"] != "USD" or value["universe_basis"] != "declared_static":
            raise QuantError("UNSUPPORTED_UNIVERSE", "当前规格只支持显式固定的XNYS/USD篮子，不推定历史成员资格")
        symbols = value["symbols"]
        if not isinstance(symbols, list) or not symbols or any(not isinstance(x, str) or not re.fullmatch(r"[A-Z0-9][A-Z0-9.\-]{0,19}", x) for x in symbols) or len(set(symbols)) != len(symbols):
            raise QuantError("INVALID_STRATEGY_SPEC", "标的必须是唯一的大写证券代码")
        value["symbols"] = sorted(symbols)
        item = definition(value["template_id"], value["implementation_version"])
        value["parameters"] = item.normalize(value["parameters"], tuple(symbols))
        value["invested_budget"] = number(value["invested_budget"], "投资预算", 0, 1)
        value["weight_cap"] = number(value["weight_cap"], "目标上限", 0, 1, positive=True)
        value["price_jump_threshold"] = number(value["price_jump_threshold"], "异常价格阈值", 0, 100, positive=True)
        if type(value["publication_delay_minutes"]) is not int or not 0 <= value["publication_delay_minutes"] <= 1440:
            raise QuantError("INVALID_STRATEGY_SPEC", "发布延迟必须为0到1440的整数分钟")
        weights = value.get("weights")
        base = value["template_id"] in {"fixed", "trend", "mean_reversion"}
        if weights is None and base:
            raise QuantError("INVALID_STRATEGY_SPEC", "该规则需要显式基础权重；等权请先明确生成权重")
        if not base and weights not in (None, {}):
            raise QuantError("INVALID_STRATEGY_SPEC", "排名/波动率规则不接受基础权重")
        if base:
            if not isinstance(weights, dict) or set(weights) != set(symbols):
                raise QuantError("INVALID_STRATEGY_SPEC", "基础权重必须与全部篮子标的一致")
            weights = {x: number(weights[x], f"{x}权重", 0, 1) for x in sorted(symbols)}
            if sum(weights.values()) > value["invested_budget"] + 1e-10:
                raise QuantError("INVALID_WEIGHTS", "基础权重合计超过策略预算")
            if value["template_id"] in {"fixed", "trend"} and max(weights.values()) > value["weight_cap"] + 1e-10:
                raise QuantError("INVALID_WEIGHTS", "显式权重超过目标上限，不自动裁剪")
        value["weights"] = weights or {}
        result = cls(canonical(value))
        if claimed is not None and claimed != result.spec_hash:
            raise QuantError("CORRUPT_STRATEGY_SPEC", "策略内容与声明哈希不一致")
        return result

    @classmethod
    def load(cls, path):
        path = Path(path)
        body = json.loads(path.read_text()) if path.suffix == ".json" else tomllib.loads(path.read_text())
        return cls.from_dict(body)

    def content(self):
        return json.loads(self._json)

    @property
    def spec_hash(self):
        return digest({key: value for key, value in self.content().items()
                       if key not in {"strategy_id", "revision", "name"}})

    @property
    def template_id(self):
        return self.content()["template_id"]

    @property
    def symbols(self):
        return tuple(self.content()["symbols"])

    @property
    def required_prices(self):
        return definition(self.template_id).history_size(self.content()["parameters"])

    def export(self):
        return {**self.content(), "spec_hash": self.spec_hash}


@dataclass(frozen=True)
class DataBundle:
    signal_snapshot_id: str
    calendar_hash: str
    execution_snapshot_id: str | None = None
    factor_snapshot_id: str | None = None

    def __post_init__(self):
        for value in self.content().values():
            if value is not None and (not isinstance(value, str) or not HASH.fullmatch(value)):
                raise QuantError("INVALID_DATA_BUNDLE", "数据包引用必须是已发布快照的内容哈希")

    def content(self):
        return {key: getattr(self, key) for key in ("signal_snapshot_id", "calendar_hash", "execution_snapshot_id", "factor_snapshot_id")}

    @property
    def bundle_hash(self):
        return digest(self.content())
