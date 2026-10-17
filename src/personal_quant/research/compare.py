"""Only compare published runs with identical data and execution assumptions."""
import hashlib
import json
from pathlib import Path
import re

import pandas as pd

from ..common import QuantError, digest


def published_runs(root, ledger=None):
    root = Path(root)
    result = []
    if not root.exists():
        return result
    for directory in root.iterdir():
        if not re.fullmatch("[0-9a-f]{32}", directory.name) or not directory.is_dir():
            continue
        manifest_path = directory / "manifest.json"
        if not manifest_path.exists():
            continue
        manifest = json.loads(manifest_path.read_text())
        if manifest.get("schema_version") == 2:
            if ledger is None or ledger.connection.execute("SELECT version FROM schema_version").fetchone()[0] < 3:
                continue
            row = ledger.connection.execute("SELECT status FROM research_attempts WHERE run_id=?", (directory.name,)).fetchone()
            if not row or row[0] != "SUCCESS":
                continue
        result.append(manifest)
    return sorted(result, key=lambda item: item["generated_at"], reverse=True)


def compare_runs(root, run_ids, *, ledger=None):
    if not 2 <= len(set(run_ids)) <= 5 or len(set(run_ids)) != len(run_ids):
        raise QuantError("INVALID_COMPARISON", "请选择2至5个不同的已发布运行")
    available = {item["run_id"]: item for item in published_runs(root, ledger)}
    if set(run_ids) - available.keys():
        raise QuantError("UNPUBLISHED_RESEARCH", "运行不存在或尚未成功注册，不能比较")
    policies, curves, metrics = [], {}, {}
    keys = ("market", "currency", "symbols", "research_capital", "evaluation_start", "evaluation_end",
            "commission_bps", "slippage_bps", "fixed_fee", "publication_delay_minutes", "price_jump_threshold", "volatility_annual_factor")
    for run_id in run_ids:
        manifest = available[run_id]
        policies.append(digest({"config": {k: manifest["config"][k] for k in keys},
            "snapshot": manifest["snapshot_id"], "bundle": manifest.get("data_bundle"),
            "source": manifest["source_hash"], "dependencies": manifest["dependencies"],
            "assumptions": manifest["assumptions"], "data_type": manifest["data_type"],
            "adapter": manifest.get("cash_policy", "legacy_v1")}))
        path = Path(root) / run_id
        for name, expected in manifest["files"].items():
            file = path / name
            if Path(name).name != name or file.is_symlink() or hashlib.sha256(file.read_bytes()).hexdigest() != expected:
                raise QuantError("CORRUPT_RESEARCH_REPORT", "比较运行的文件指纹不一致")
        nav = pd.read_csv(path / "nav.csv", index_col=0) / manifest["config"]["research_capital"]
        for member in nav.columns:
            key = run_id[:8] + ":" + member
            curves[key] = nav[member]
            metrics[key] = manifest["metrics"][member]
    if len(set(policies)) != 1:
        raise QuantError("INCOMPARABLE_RUNS", "数据、区间、代码/依赖或成交假设不同；请重新建立统一实验，不做收益排名")
    curve = pd.DataFrame(curves)
    if curve.isna().any().any():
        raise QuantError("INCOMPARABLE_RUNS", "观察日期不同")
    return {"status": "SUCCESS", "run_ids": run_ids, "metrics": metrics,
            "comparison": "相同行情、区间、资金、费用、代码与成交政策；已观察历史研究"}, curve
