"""No-key v1.5 delivery: CLI research, PIT factors, binding, fills and recovery."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import time
from uuid import uuid4

REPO = Path(__file__).resolve().parents[1]
WRITABLE_ALIAS = Path('/mnt/c/quant/project/lyra')
if WRITABLE_ALIAS.is_dir() and WRITABLE_ALIAS.samefile(REPO):
    REPO = WRITABLE_ALIAS
sys.path.insert(0, str(REPO / "src"))

import pandas as pd
from personal_quant.cli import main, references
from personal_quant.common import decimal as D, now_utc, write_json
from personal_quant.config import Config
from personal_quant.data.store import DataStore
from personal_quant.portfolio import Ledger
from personal_quant.strategies.archive import source_fingerprint
from personal_quant.strategies.spec import StrategySpec


def verify(real_price_cache=None):
    original = Path.cwd()
    output = REPO / "reports/v15-validation" / uuid4().hex
    output.mkdir(parents=True)
    workspace = output / "workspace"
    workspace.mkdir()
    records = []
    settings = Config.load(REPO / "configs/demo.toml")
    config_path = workspace / "config.json"
    write_json(config_path, settings.content())

    def run(*args, expected=0):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--config", str(config_path), *args])
        # bt progress can precede the CLI's one JSON result.
        lines = (out.getvalue() or err.getvalue()).strip().splitlines()
        result = json.loads(lines[-1])
        records.append({"command": list(args), "config": str(config_path), "exit_code": code, "result": result})
        if code != expected:
            raise AssertionError(f"{args[0]}: exit {code}, {result}")
        return result

    try:
        os.chdir(workspace)
        run("fixture")
        run("workbench-init")
        specs = {}
        for template in ("fixed", "trend", "momentum_rotation", "mean_reversion", "inverse_volatility", "multi_factor"):
            spec = StrategySpec.create(template, settings.symbols,
                weights={symbol: .95 / len(settings.symbols) for symbol in settings.symbols}
                    if template in {"fixed", "trend", "mean_reversion"} else None)
            path = Path("specs") / (template + ".json")
            write_json(path, spec.export()); run("strategies", "--file", str(path))
            specs[template] = {"strategy_id": template, "revision": 1}
        run("strategies")
        store = DataStore(Path(settings.runtime_dir) / "data")
        frame, meta, calendar = store.load()
        bundle = {"signal_snapshot_id": meta["snapshot_id"], "calendar_hash": calendar.hash,
                  "execution_snapshot_id": meta["snapshot_id"], "factor_snapshot_id": None}
        write_json(Path("bundle.json"), bundle)
        request = {"members": specs, "benchmark_member_id": "fixed", "data_bundle": bundle, "purpose": "validation"}
        write_json(Path("experiment.json"), request)
        first = run("research", "--experiment", "experiment.json")
        repeated = run("research", "--experiment", "experiment.json")
        assert repeated["run_id"] == first["run_id"]
        second = run("research", "--experiment", "experiment.json", "--rerun")
        assert second["run_id"] != first["run_id"]
        assert first["metrics"] == second["metrics"]
        for name in first["files"]:
            if name.endswith(".csv"):
                assert first["files"][name] == second["files"][name]
        run("compare", "--runs", first["run_id"], second["run_id"])
        run("research-status"); run("research-recover")

        # Synthetic factor records have explicit source and system receipt times.
        rows = []
        for day in calendar.month_ends():
            if not settings.evaluation_start <= str(day.date()) <= settings.evaluation_end:
                continue
            period = (day.to_period("Q").start_time - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
            available = (calendar.close(day) + pd.Timedelta(minutes=30)).isoformat()
            for n, symbol in enumerate(sorted(settings.symbols), start=1):
                for factor, value in (("book_to_market", n * .2), ("roe_ttm", n * .03)):
                    rows.append({"asset_id": symbol, "factor_name": factor, "value": value, "unit": "ratio",
                        "period_end": period, "published_at": available, "available_at": available,
                        "value_as_of": str(day.date()), "source": "lyrax_synthetic_factor_demo",
                        "source_record_id": f"{day.date()}-{symbol}-{factor}", "revision": 1,
                        "currency": "USD", "data_type": "synthetic", "definition_version": "test.v1"})
        pd.DataFrame(rows).to_csv("test_factors.csv", index=False)
        write_json(Path("factor_metadata.json"), {"source": "lyrax_synthetic_factor_demo",
            "source_reference": "Deterministic engineering fixture; no real ETF fundamentals",
            "permission_note": "local test fixture", "qualification": "test", "availability_evidence": "synthetic test assumptions",
            "definitions": {name: {"unit": "ratio", "version": "test.v1", "description": "synthetic ratio for contract tests"}
                            for name in ("book_to_market", "roe_ttm")}})
        factor = run("import-factors", "--file", "test_factors.csv", "--metadata", "factor_metadata.json")
        assert run("import-factors", "--file", "test_factors.csv", "--metadata", "factor_metadata.json")["snapshot_id"] == factor["snapshot_id"]
        fundamental = StrategySpec.create("multi_factor", settings.symbols, strategy_id="fundamental_test", parameters={"mode": "fundamental"})
        write_json(Path("specs/fundamental_test.json"), fundamental.export())
        run("strategies", "--file", "specs/fundamental_test.json")
        factor_request = {"members": {"baseline": specs["fixed"], "value_quality_test": {"strategy_id": "fundamental_test", "revision": 1}},
            "benchmark_member_id": "baseline", "data_bundle": {**bundle, "factor_snapshot_id": factor["snapshot_id"]}}
        write_json(Path("factor_experiment.json"), factor_request)
        factor_run = run("research", "--experiment", "factor_experiment.json", "--background")
        attempt_id = factor_run["attempt_id"]
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            book = Ledger(Path(settings.runtime_dir) / "account.sqlite", "demo")
            row = book.connection.execute("SELECT status,run_id,details FROM research_attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
            book.close()
            if row["status"] in {"SUCCESS", "FAILED", "INTERRUPTED"}:
                break
            time.sleep(.2)
        assert row["status"] == "SUCCESS", dict(row)
        factor_manifest = json.loads((Path(settings.runtime_dir) / "reports/research" / attempt_id / "manifest.json").read_text())
        assert factor_manifest["data_type"] == "mixed_test_factors"

        run("account", "--account-id", "v15-demo")
        Path("opening.csv").write_text("event_id,kind,amount,effective_at,source,evidence_type\nopening,DEPOSIT,10000,2024-07-01T20:00:00Z,independent_demo_statement,test\n")
        preview = run("import-events", "--account-id", "v15-demo", "--file", "opening.csv", "--as-of", "2024-07-31T20:30:00Z")
        run("import-events", "--account-id", "v15-demo", "--file", "opening.csv", "--commit",
            "--expected-sequence", str(preview["expected_sequence"]), "--expected-hash", preview["batch_hash"])
        write_json(Path("opening_snapshot.json"), {"account_id": "v15-demo", "currency": "USD", "as_of": "2024-07-31T20:30:00Z",
            "cash_basis": "settled", "cash": 10000, "positions": {}, "source": "independent_demo_statement"})
        run("reconcile", "--account-id", "v15-demo", "--file", "opening_snapshot.json")
        binding = run("strategy-bind", "--account-id", "v15-demo", "--strategy-id", "momentum_rotation", "--revision", "1", "--as-of", "2024-07-01T20:30:00Z")
        assert binding["effective_session"] == "2024-07-31"
        decision = run("monthly-decision", "--account-id", "v15-demo", "--session", "2024-07-31", "--bundle", "bundle.json", "--as-of", "2024-07-31T20:30:00Z")
        assert decision["status"] == "READY"
        assert run("plan", "--account-id", "v15-demo", "--session", "2024-07-31", "--as-of", "2024-07-31T20:30:00Z")["plan_id"] == decision["plan_id"]
        run("simulate", "--plan-id", decision["plan_id"], "--as-of", "2024-08-01T20:30:00Z")
        assert run("simulate", "--plan-id", decision["plan_id"], "--as-of", "2024-08-01T20:30:00Z")["status"] == "NO_ACTION"
        account_report = run("report", "--account-id", "v15-demo", "--as-of", "2024-08-02T20:30:00Z")
        book = Ledger(Path(settings.runtime_dir) / "account.sqlite", "demo")
        facts = book.active_events("v15-demo", "2024-08-02T20:30:00Z")
        book.close()
        expected_cash = D(10000) - sum((D(item["quantity"]) * D(item["price"]) + D(item["fee"]) for item in facts if item["kind"] == "BUY"), D(0))
        assert D(account_report["settled_cash"]) == expected_cash and D(account_report["net_contributions"]) == 10000
        run("backup-bundle", "--destination", str(output / "backup"))
        run("verify-backup", "--source", str(output / "backup"), "--environment", "demo")
        run("restore", "--source", str(output / "backup"), "--environment", "demo", "--destination", str(output / "restored"))

        real_result = None
        if real_price_cache:
            live = output / "real-price-research"; live.mkdir(); os.chdir(live)
            shutil.copytree(real_price_cache, Path("runtime/demo/data"))
            _, real_meta, real_calendar = DataStore(Path("runtime/demo/data")).load()
            raw_config = settings.content(); raw_config["evaluation_end"] = real_meta["end"]
            config_path = live / "config.json"; write_json(config_path, raw_config)
            run("workbench-init")
            for template in specs:
                run("strategies", "--file", str(workspace / "specs" / (template + ".json")))
            real_request = {**request, "data_bundle": {"signal_snapshot_id": real_meta["snapshot_id"],
                "calendar_hash": real_calendar.hash, "execution_snapshot_id": None, "factor_snapshot_id": None}}
            write_json(Path("experiment.json"), real_request)
            real_result = run("research", "--experiment", "experiment.json")
            again = run("research", "--experiment", "experiment.json", "--rerun")
            assert real_result["metrics"] == again["metrics"]
            assert real_result["data_type"] == "real_market"
            book = Ledger(Path("runtime/demo/account.sqlite"), "demo")
            assert book.connection.execute("SELECT count(*) FROM events").fetchone()[0] == 0
            assert book.connection.execute("SELECT count(*) FROM accounts").fetchone()[0] == 0
            book.close()
        result = {"status": "PASS_V15_END_TO_END", "source_hash": source_fingerprint(), "generated_at": now_utc(),
            "commands": len(records), "offline_run_ids": [first["run_id"], second["run_id"]],
            "factor_test_run_id": attempt_id, "real_run_id": real_result["run_id"] if real_result else None,
            "real_research_report": str(output / "real-price-research/runtime/demo/reports/research" / real_result["run_id"]) if real_result else None,
            "offline_report": str(workspace / "runtime/demo/reports/research" / first["run_id"]),
            "account": {"settled_cash": account_report["settled_cash"], "net_contributions": account_report["net_contributions"]},
            "real_fundamental_qualification": "BLOCKED_NO_SUPPLIED_QUALIFIED_SOURCE",
            "records": records}
        write_json(output / "verification.json", result)
        write_json(REPO / "reports/v15-validation/latest.json", {"verification": str(output / "verification.json")})
        print(json.dumps({k: v for k, v in result.items() if k != "records"}, ensure_ascii=False))
    finally:
        os.chdir(original)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--real-price-cache", type=Path, help="已核验的真实行情缓存目录；不触发在线下载")
    args = parser.parse_args()
    verify(args.real_price_cache.resolve() if args.real_price_cache else None)
