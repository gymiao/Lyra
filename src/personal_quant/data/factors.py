"""Point-in-time factor snapshots with immutable revisions and system receipt times."""
from __future__ import annotations

from datetime import date
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd

from ..common import QuantError, canonical, digest, now_utc, utc, write_json
from ..strategies.spec import HASH
from ..locks import publication_lock

COLUMNS = {"asset_id", "factor_name", "value", "unit", "period_end", "published_at", "available_at",
           "value_as_of", "source", "source_record_id", "revision", "currency", "data_type", "definition_version"}
IDENTITY = ["source", "asset_id", "factor_name", "period_end", "definition_version", "source_record_id", "revision"]
META_FIELDS = {"source", "source_reference", "permission_note", "definitions", "availability_evidence", "qualification"}


def normalize(frame, metadata):
    if not isinstance(metadata, dict) or set(metadata) != META_FIELDS:
        raise QuantError("INVALID_FACTOR_METADATA", "因子元数据需要来源、定义、权限、时点证据和资格声明")
    if metadata["qualification"] not in {"test", "unverified", "reviewed_source"}:
        raise QuantError("INVALID_FACTOR_METADATA", "未知因子资格")
    for field in ("source", "source_reference", "permission_note"):
        if not isinstance(metadata[field], str) or not metadata[field].strip():
            raise QuantError("INVALID_FACTOR_METADATA", f"缺少{field}")
    if not isinstance(metadata["definitions"], dict) or not metadata["definitions"]:
        raise QuantError("INVALID_FACTOR_METADATA", "缺少因子定义")
    if metadata["qualification"] == "reviewed_source" and not metadata["availability_evidence"]:
        raise QuantError("INVALID_FACTOR_METADATA", "历史可用性资格必须附人工核验依据")
    if set(frame.columns) != COLUMNS or frame.empty:
        raise QuantError("INVALID_FACTOR_DATA", "因子CSV字段必须完整且不能包含自报的系统recorded_at")
    out = frame.copy()
    if out.isna().any().any():
        raise QuantError("INVALID_FACTOR_DATA", "因子缺失不能填零")
    text_fields = COLUMNS - {"value", "revision"}
    for field in text_fields:
        if any(not isinstance(x, str) or not x.strip() for x in out[field]):
            raise QuantError("INVALID_FACTOR_DATA", f"{field}必须是非空文本")
    if set(out.currency) != {"USD"} or set(out.source) != {metadata["source"]}:
        raise QuantError("INVALID_FACTOR_DATA", "因子来源或币种与声明不一致")
    if not set(out.data_type) <= {"synthetic", "real_factors"} or len(set(out.data_type)) != 1:
        raise QuantError("INVALID_FACTOR_DATA", "因子真实/测试类型不能混合")
    if (out.data_type.iloc[0] == "synthetic") != (metadata["qualification"] == "test"):
        raise QuantError("INVALID_FACTOR_METADATA", "合成因子必须标记test，真实因子不可用测试资格")
    for column in ("period_end", "value_as_of"):
        try:
            if any(date.fromisoformat(x).isoformat() != x for x in out[column]):
                raise ValueError
        except (TypeError, ValueError) as exc:
            raise QuantError("INVALID_FACTOR_DATA", f"{column}需要YYYY-MM-DD") from exc
    for column in ("published_at", "available_at"):
        try:
            out[column] = [utc(x).isoformat() for x in out[column]]
        except (TypeError, ValueError) as exc:
            raise QuantError("INVALID_FACTOR_DATA", f"{column}需要带时区的时间") from exc
    out["value"] = pd.to_numeric(out.value, errors="coerce")
    if any(isinstance(v, bool) for v in out.revision) or any(isinstance(v, bool) for v in out.value):
        raise QuantError("INVALID_FACTOR_DATA", "因子值及修订号不能为布尔值")
    rev = pd.to_numeric(out.revision, errors="coerce")
    if not np.isfinite(out.value).all() or not np.isfinite(rev).all() or (rev < 1).any() or (rev % 1 != 0).any():
        raise QuantError("INVALID_FACTOR_DATA", "因子须有限，修订号须为正整数")
    out["revision"] = rev.astype(int)
    if (pd.to_datetime(out.published_at, utc=True) > pd.to_datetime(out.available_at, utc=True)).any():
        raise QuantError("FUTURE_FACTOR", "可用时间不能早于发布时间")
    if (pd.to_datetime(out.period_end) > pd.to_datetime(out.published_at, utc=True).dt.tz_localize(None)).any():
        raise QuantError("FUTURE_FACTOR", "不能发布未来报告期的因子")
    for name, group in out.groupby("factor_name"):
        definition = metadata["definitions"].get(name)
        if not isinstance(definition, dict) or set(definition) != {"unit", "version", "description"}:
            raise QuantError("INVALID_FACTOR_METADATA", f"{name}缺少单位、版本或计算口径")
        if set(group.unit) != {definition["unit"]} or set(group.definition_version) != {definition["version"]} or not definition["description"]:
            raise QuantError("FACTOR_DEFINITION_MISMATCH", f"{name}数据与定义不一致")
    out = out.drop_duplicates()
    if out.duplicated(IDENTITY).any():
        raise QuantError("FACTOR_ID_CONFLICT", "同一来源事件及修订号包含不同内容")
    return out.sort_values(IDENTITY).reset_index(drop=True)


class FactorStore:
    def __init__(self, root):
        self.root = Path(root)

    def save(self, frame, metadata):
        with publication_lock(self.root.parent):
            return self._save(frame, metadata)

    def _save(self, frame, metadata):
        normalized = normalize(frame, metadata)
        self.root.mkdir(parents=True, exist_ok=True)
        current = self.root / "latest.json"
        receipt = now_utc()
        normalized["recorded_at"] = receipt
        if current.exists():
            old, previous = self.load()
            if previous["metadata"] != metadata:
                raise QuantError("FACTOR_SERIES_CONFLICT", "因子来源/定义变更需要独立数据目录，不能静默合并")
            old_rows = {tuple(row[k] for k in IDENTITY): row for row in old.to_dict("records")}
            for row in normalized.to_dict("records"):
                key = tuple(row[k] for k in IDENTITY)
                if key in old_rows:
                    if {k: old_rows[key][k] for k in COLUMNS} != {k: row[k] for k in COLUMNS}:
                        raise QuantError("FACTOR_ID_CONFLICT", "已保存因子同ID内容冲突，禁止覆盖历史")
                else:
                    old_rows[key] = row
            normalized = pd.DataFrame(old_rows.values()).sort_values(IDENTITY).reset_index(drop=True)
        content = normalized.drop(columns="recorded_at").to_dict("records")
        snapshot_id = digest({"schema_version": 1, "metadata": metadata, "rows": content})
        directory = self.root / snapshot_id
        if not directory.exists():
            pending = self.root / (".pending-" + uuid4().hex)
            pending.mkdir()
            normalized.to_parquet(pending / "factors.parquet", index=False)
            manifest = {"schema_version": 1, "snapshot_id": snapshot_id, "metadata": metadata,
                "data_type": normalized.data_type.iloc[0], "rows": len(normalized), "acquired_at": receipt,
                "files": {"factors.parquet": hashlib.sha256((pending / "factors.parquet").read_bytes()).hexdigest()}}
            write_json(pending / "manifest.json", manifest)
            os.replace(pending, directory)
        verified=self.load(snapshot_id)[1]
        write_json(current, {"snapshot_id": snapshot_id})
        return verified

    def load(self, snapshot_id=None):
        if snapshot_id is None:
            if not (self.root / "latest.json").exists():
                raise QuantError("MISSING_FACTORS", "尚无因子快照")
            snapshot_id = json.loads((self.root / "latest.json").read_text())["snapshot_id"]
        if not isinstance(snapshot_id, str) or not HASH.fullmatch(snapshot_id):
            raise QuantError("INVALID_FACTOR_SNAPSHOT", "非法因子快照标识")
        directory = self.root / snapshot_id
        try:
            meta = json.loads((directory / "manifest.json").read_text())
            path = directory / "factors.parquet"
            if hashlib.sha256(path.read_bytes()).hexdigest() != meta["files"]["factors.parquet"]:
                raise ValueError("hash")
            frame = pd.read_parquet(path)
            rows = normalize(frame.drop(columns="recorded_at"), meta["metadata"])
            identity = digest({"schema_version": 1, "metadata": meta["metadata"], "rows": rows.to_dict("records")})
            if identity != snapshot_id or meta["snapshot_id"] != snapshot_id or len(frame) != meta["rows"] or set(frame.data_type) != {meta["data_type"]}:
                raise ValueError("identity")
            for value in frame.recorded_at:
                utc(value)
        except (OSError, KeyError, TypeError, ValueError) as exc:
            raise QuantError("CORRUPT_FACTOR_SNAPSHOT", "因子文件/清单内容不匹配") from exc
        return frame, meta

    def select(self, snapshot_id, spec, decision_time, *, forward=False):
        frame, meta = self.load(snapshot_id)
        instant = pd.Timestamp(utc(decision_time)); today = instant.tz_convert("America/New_York").date()
        if meta["metadata"]["qualification"] == "unverified":
            raise QuantError("UNQUALIFIED_FACTORS", "真实因子来源尚未核验，只能查看诊断")
        if forward and (meta["data_type"] != "real_factors" or meta["metadata"]["qualification"] != "reviewed_source"):
            raise QuantError("UNQUALIFIED_FACTORS", "前向因子需要真实来源及历史可用性核验凭据")
        allowed = pd.to_datetime(frame.available_at, utc=True) <= instant
        if forward:
            allowed &= pd.to_datetime(frame.recorded_at, utc=True) <= instant
        candidates = frame.loc[allowed]
        params = spec.content()["parameters"]
        selected = []
        for asset in spec.symbols:
            for name in ("book_to_market", "roe_ttm"):
                rows = candidates.loc[(candidates.asset_id == asset) & (candidates.factor_name == name)]
                if rows.empty:
                    raise QuantError("MISSING_FACTORS", f"{asset}/{name}在决策时点尚不可用")
                period = rows.period_end.max()
                rows = rows.loc[rows.period_end == period]
                # Select the latest valuation date, then its latest known revision.
                rows = rows.sort_values(["value_as_of", "available_at", "revision"])
                row = rows.iloc[-1]
                same = rows.loc[(rows.value_as_of == row.value_as_of) & (rows.available_at == row.available_at) & (rows.revision == row.revision)]
                if len(same) > 1:
                    raise QuantError("AMBIGUOUS_FACTOR", "同一估值与修订时点有多条记录，不能任意选择")
                age = (today - date.fromisoformat(row.period_end)).days
                value_age = (today - date.fromisoformat(row.value_as_of)).days
                if age < 0 or value_age < 0:
                    raise QuantError("FUTURE_FACTOR", "因子引用未来报告期或估值日期")
                if age > params["max_report_age_days"] or value_age > params["max_value_age_days"]:
                    raise QuantError("STALE_FACTOR", f"{asset}/{name}报告或估值超过配置年龄")
                selected.append(row.to_dict())
        result = pd.DataFrame(selected).pivot(index="asset_id", columns="factor_name", values="value").reindex(spec.symbols)
        result.attrs["evidence"] = [{k: row[k] for k in sorted(COLUMNS)} for row in selected]
        return result
