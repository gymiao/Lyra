"""Immutable, fully resolved research inputs; no account writes or live downloads."""
from __future__ import annotations

from dataclasses import dataclass
import importlib.metadata
import json
from pathlib import Path

from ..common import QuantError, canonical, digest
from ..config import Config
from ..data.factors import FactorStore
from ..data.store import DataStore
from ..strategies.archive import source_fingerprint
from ..strategies.spec import DataBundle, ID, StrategySpec


@dataclass(frozen=True)
class ResearchSpec:
    _json: str

    @classmethod
    def create(cls, config, members, benchmark, bundle, *, purpose="exploratory"):
        config.validate()
        if config.strategy_spec is not None:
            raise QuantError("INVALID_EXPERIMENT", "研究使用独立运行配置；账户绑定规格不覆盖研究成员")
        if purpose not in {"exploratory", "validation"}:
            raise QuantError("OBSERVED_EVALUATION", "当前历史研究不宣称未见的最终评估；请记录探索或验证用途")
        if not isinstance(members, dict) or not 2 <= len(members) <= 7 or benchmark not in members:
            raise QuantError("INVALID_EXPERIMENT", "需要一个明确基准及1至6个候选")
        members = {key: StrategySpec.from_dict(spec.export()) for key, spec in members.items()}
        if any(not isinstance(key, str) or not ID.fullmatch(key) for key in members) or len({spec.spec_hash for spec in members.values()}) != len(members):
            raise QuantError("INVALID_EXPERIMENT", "成员ID非法或存在相同计算规格")
        if any(set(spec.symbols) != set(config.symbols) for spec in members.values()):
            raise QuantError("INCOMPARABLE_UNIVERSE", "正式比较需要相同篮子")
        for spec in members.values():
            body = spec.content()
            if body["publication_delay_minutes"] != config.publication_delay_minutes or body["price_jump_threshold"] != config.price_jump_threshold:
                raise QuantError("INCOMPARABLE_POLICY", "研究成员必须使用同一发布时间及质量政策")
        store = DataStore(Path(config.runtime_dir) / "data")
        _, meta, calendar = store.load(bundle.signal_snapshot_id)
        if calendar.hash != bundle.calendar_hash:
            raise QuantError("INVALID_DATA_BUNDLE", "冻结日历与行情不一致")
        needs_factors = any(s.template_id == "multi_factor" and s.content()["parameters"]["mode"] == "fundamental" for s in members.values())
        factor_meta = None
        if needs_factors:
            if not bundle.factor_snapshot_id:
                raise QuantError("MISSING_FACTORS", "价值/质量实验必须指定冻结因子快照")
            _, factor_meta = FactorStore(Path(config.runtime_dir) / "factors").load(bundle.factor_snapshot_id)
            if factor_meta["metadata"]["qualification"] == "unverified":
                raise QuantError("UNQUALIFIED_FACTORS", "真实因子来源尚未核验")
        return cls(canonical({"schema_version": 1, "config": config.content(),
            "members": {key: spec.export() for key, spec in members.items()}, "benchmark_member_id": benchmark,
            "data_bundle": bundle.content(), "source_hash": source_fingerprint(),
            "dependencies": {key: importlib.metadata.version(key) for key in ("bt", "ffn", "pandas", "numpy", "pyarrow")},
            "engine_adapter": "bt.monthly.v15.1", "purpose": purpose, "evaluation_seen": True,
            "contains_test_factors": bool(factor_meta and factor_meta["data_type"] == "synthetic"),
            "data_type": meta["data_type"], "universe_basis": "declared_static"}))

    @classmethod
    def from_dict(cls, body):
        keys = {"schema_version", "config", "members", "benchmark_member_id", "data_bundle", "source_hash",
                "dependencies", "engine_adapter", "purpose", "evaluation_seen", "contains_test_factors", "data_type", "universe_basis"}
        if not isinstance(body, dict) or set(body) != keys or body["schema_version"] != 1:
            raise QuantError("INVALID_EXPERIMENT", "实验版本或字段不完整")
        Config.from_dict(body["config"])
        DataBundle(**body["data_bundle"])
        members = body["members"]
        if (not isinstance(members, dict) or not 2 <= len(members) <= 7 or body["benchmark_member_id"] not in members or
                any(not isinstance(key, str) or not ID.fullmatch(key) for key in members)):
            raise QuantError("INVALID_EXPERIMENT", "成员/基准身份无效")
        specs = [StrategySpec.from_dict(item) for item in members.values()]
        if len({spec.spec_hash for spec in specs}) != len(specs):
            raise QuantError("INVALID_EXPERIMENT", "实验不能包含重复的计算规格")
        config = Config.from_dict(body["config"])
        if config.strategy_spec or any(set(s.symbols) != set(config.symbols) for s in specs):
            raise QuantError("INVALID_EXPERIMENT", "实验篮子或运行配置不一致")
        if any(s.content()["publication_delay_minutes"] != config.publication_delay_minutes or
               s.content()["price_jump_threshold"] != config.price_jump_threshold for s in specs):
            raise QuantError("INVALID_EXPERIMENT", "实验决策政策不一致")
        if body["purpose"] not in {"exploratory", "validation"} or body["evaluation_seen"] is not True:
            raise QuantError("OBSERVED_EVALUATION", "当前工作台不宣称未见的最终评估")
        return cls(canonical(body))

    @classmethod
    def load_request(cls, path, config, strategy_store):
        path = Path(path)
        request = json.loads(path.read_text())
        required = {"members", "benchmark_member_id", "data_bundle"}
        if not isinstance(request, dict) or required - request.keys() or request.keys() - (required | {"purpose"}):
            raise QuantError("INVALID_EXPERIMENT", "实验请求字段不完整或含未知项")
        members = {}
        for member_id, ref in request["members"].items():
            if not isinstance(ref, dict) or set(ref) != {"strategy_id", "revision"}:
                raise QuantError("INVALID_EXPERIMENT", "实验成员必须引用已发布的精确版本")
            members[member_id] = strategy_store.get(ref["strategy_id"], ref["revision"])
        return cls.create(config, members, request["benchmark_member_id"], DataBundle(**request["data_bundle"]),
                          purpose=request.get("purpose", "exploratory"))

    def content(self):
        return json.loads(self._json)

    @property
    def experiment_hash(self):
        value = self.content()
        # The run shows its frozen display metadata; aliases do not change computations.
        value["members"] = {key: item["spec_hash"] for key, item in value["members"].items()}
        return digest(value)

    def require_current_implementation(self):
        body = self.content()
        if source_fingerprint() != body["source_hash"] or any(importlib.metadata.version(k) != v for k, v in body["dependencies"].items()):
            raise QuantError("EXPERIMENT_CODE_CHANGED", "代码/依赖已改变；请基于当前实现建立新实验，不覆盖旧运行")
