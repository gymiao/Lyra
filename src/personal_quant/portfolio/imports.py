"""Strict UTF-8 CSV contracts shared by the CLI and dashboard."""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from ..common import QuantError, decimal as D, utc


def _rows(value: bytes | str) -> list[dict]:
    text = value.decode("utf-8-sig") if isinstance(value, bytes) else value.lstrip("\ufeff")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
        raise QuantError("INVALID_CSV", "CSV 缺少表头或表头重复")
    rows = []
    for number, row in enumerate(reader, 2):
        if None in row or any(v is None for v in row.values()):
            raise QuantError("INVALID_CSV", f"第 {number} 行字段数量与表头不一致")
        rows.append({k: v.strip() for k, v in row.items() if v.strip() != ""})
    if not rows:
        raise QuantError("EMPTY_STATEMENT", "CSV 没有数据行")
    return rows


def event_csv(value: bytes | str) -> list[dict]:
    rows = _rows(value)
    for number, row in enumerate(rows, 2):
        kinds = [row[k].upper() for k in ("kind", "side", "event_type") if k in row]
        if not kinds or len(set(kinds)) != 1:
            raise QuantError("INVALID_CSV", f"第 {number} 行必须有一致的 kind / side / event_type")
        row["kind"] = kinds[0]
        row.pop("side", None)
        row.pop("event_type", None)
    return rows


def snapshot_csv(value: bytes | str) -> dict:
    rows = _rows(value)
    required = {"account_id", "as_of", "currency", "cash_basis", "cash", "source"}
    allowed = required | {"symbol", "quantity", "equity", "evidence_hash"}
    common = {k: v for k, v in rows[0].items() if k not in {"symbol", "quantity"}}
    if not required <= common.keys():
        raise QuantError("INVALID_RECONCILIATION", f"快照缺少字段：{sorted(required - common.keys())}")
    result = {**common, "positions": {}}
    result["as_of"] = utc(result["as_of"]).isoformat()
    result["cash"] = str(D(result["cash"]))
    if "equity" in result:
        result["equity"] = str(D(result["equity"]))
    for number, row in enumerate(rows, 2):
        if set(row) - allowed or {k: v for k, v in row.items() if k not in {"symbol", "quantity"}} != common:
            raise QuantError("INVALID_RECONCILIATION", f"第 {number} 行有未知字段或账户/时点/现金口径不一致")
        symbol = row.get("symbol")
        if not symbol:
            if len(rows) != 1 or "quantity" in row:
                raise QuantError("INVALID_RECONCILIATION", "空持仓必须由单独一行空 symbol/quantity 显式表示")
            continue
        if "quantity" not in row or symbol in result["positions"]:
            raise QuantError("INVALID_RECONCILIATION", f"第 {number} 行缺少数量或标的重复")
        result["positions"][symbol] = str(D(row["quantity"]))
    return result


def read_snapshot(path: Path) -> dict:
    if path.suffix.lower() == ".csv":
        return snapshot_csv(path.read_bytes())
    result = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(result, dict):
        raise QuantError("INVALID_RECONCILIATION", "JSON 快照必须是对象")
    return result
