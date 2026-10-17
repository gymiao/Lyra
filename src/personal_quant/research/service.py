"""Persistent research attempts and crash safe publication; never writes accounts."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from uuid import uuid4

from ..common import QuantError, canonical, digest, now_utc, write_json
from ..locks import publication_lock
from ..config import Config
from ..data.factors import FactorStore
from ..data.store import DataStore
from ..execution.daily import daily_lock
from ..strategies.spec import DataBundle, StrategySpec
from .backtest import run_research
from .experiments import ResearchSpec


def process_identity(pid=None):
    pid = pid or os.getpid()
    try:
        stat = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        if stat[0] == "Z":
            return None
        return {"pid": pid, "start_ticks": stat[19],
                "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip()}
    except (OSError, IndexError):
        return None


def worker_alive(identity):
    return bool(identity and process_identity(identity.get("pid")) == identity)


class ResearchService:
    def __init__(self, ledger, *, after_publish=None):
        if ledger.connection.execute("SELECT version FROM schema_version").fetchone()[0] < 3:
            raise QuantError("WORKBENCH_NOT_ENABLED", "请先显式启用工作台并完成备份升级")
        self.ledger = ledger
        self.root = ledger.path.parent.resolve()
        self.reports = self.root / "reports/research"
        self.after_publish = after_publish

    def get(self, attempt_id):
        row = self.ledger.connection.execute("SELECT * FROM research_attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
        if not row:
            raise QuantError("UNKNOWN_RESEARCH_ATTEMPT", "研究任务不存在")
        result = dict(row)
        for field in ("details", "worker"):
            result[field] = json.loads(result[field]) if result[field] else None
        return result

    def list(self):
        return [self.get(row[0]) for row in self.ledger.connection.execute(
            "SELECT attempt_id FROM research_attempts ORDER BY created_at DESC LIMIT 100")]

    def experiment(self, experiment_hash):
        row = self.ledger.connection.execute("SELECT payload FROM research_experiments WHERE experiment_hash=?", (experiment_hash,)).fetchone()
        if not row:
            raise QuantError("UNKNOWN_EXPERIMENT", "冻结实验不存在")
        spec = ResearchSpec.from_dict(json.loads(row[0]))
        if spec.experiment_hash != experiment_hash:
            raise QuantError("CORRUPT_EXPERIMENT", "冻结实验内容与身份不匹配")
        return spec

    def submit(self, spec, *, rerun=False, suite_id=None):
        spec = ResearchSpec.from_dict(spec.content())
        config = Config.from_dict(spec.content()["config"])
        if Path(config.runtime_dir).resolve() != self.root or config.environment != self.ledger.environment:
            raise QuantError("ENVIRONMENT_MISMATCH", "研究任务必须属于当前隔离目录")
        from .artifacts import capture_source
        archive = capture_source(self.root)
        if archive.name != spec.content()['source_hash']:
            raise QuantError('EXPERIMENT_CODE_CHANGED','提交前源码已改变')
        with self.ledger.transaction():
            if self.ledger.connection.execute('SELECT version FROM schema_version').fetchone()[0] >= 4:
                owner = self.ledger.connection.execute("SELECT suite_id FROM validation_suites WHERE status='RUNNING'").fetchone()
                if owner and owner[0] != suite_id:
                    raise QuantError('VALIDATION_ALREADY_RUNNING','当前验证套件持有研究执行权')
            previous = self.ledger.connection.execute("SELECT attempt_id,status FROM research_attempts WHERE experiment_hash=? ORDER BY created_at DESC LIMIT 1",
                (spec.experiment_hash,)).fetchone()
            if previous and (not rerun or previous["status"] in {"CREATED", "RUNNING", "PUBLISHING"}):
                return self.get(previous["attempt_id"])
            active = self.ledger.connection.execute("SELECT attempt_id FROM research_attempts WHERE status IN ('CREATED','RUNNING','PUBLISHING')").fetchone()
            if active:
                raise QuantError("RESEARCH_ALREADY_RUNNING", "该目录已有研究任务；请查看进度或恢复中断任务")
            self.ledger.connection.execute("INSERT OR IGNORE INTO research_experiments VALUES(?,?,?)",
                (spec.experiment_hash, canonical(spec.content()), now_utc()))
            attempt = uuid4().hex
            self.ledger.connection.execute("INSERT INTO research_attempts(attempt_id,experiment_hash,status,created_at,details) VALUES(?,?,?,?,?)",
                (attempt, spec.experiment_hash, "CREATED", now_utc(), "{}"))
        return self.get(attempt)

    def launch(self, attempt_id):
        # Submission lock closes the interval between process creation and owner registration.
        with daily_lock(self.root / ".research-submission.lock"):
            row = self.get(attempt_id)
            if row["status"] != "CREATED" or worker_alive(row["worker"]):
                return row
            config = Config.from_dict(self.experiment(row["experiment_hash"]).content()["config"])
            config_path = self.root / "research-jobs" / attempt_id / "config.json"
            write_json(config_path, config.content())
            log = config_path.parent / "worker.log"
            environment = dict(os.environ)
            for key in ("PYTHONPATH", "PYTHONHOME"):
                environment.pop(key, None)
            environment["PYTHONNOUSERSITE"] = "1"
            try:
                with log.open("ab") as stream:
                    process = subprocess.Popen([sys.executable, "-m", "personal_quant", "--config", str(config_path),
                        "research-worker", "--attempt-id", attempt_id], stdout=stream, stderr=subprocess.STDOUT,
                        env=environment, cwd=Path.cwd(), start_new_session=True)
                owner = process_identity(process.pid)
                with self.ledger.transaction():
                    self.ledger.connection.execute("UPDATE research_attempts SET worker=?,details=? WHERE attempt_id=? AND status='CREATED'",
                        (canonical(owner) if owner else None, canonical({"log": str(log)}), attempt_id))
            except OSError as exc:
                self._finish(attempt_id, "FAILED", {"code": "WORKER_START_FAILED", "message": str(exc)})
            return self.get(attempt_id)

    def _finish(self, attempt_id, status, details, run_id=None):
        with self.ledger.transaction():
            self.ledger.connection.execute("UPDATE research_attempts SET status=?,finished_at=?,details=?,run_id=? WHERE attempt_id=?",
                (status, now_utc(), canonical(details), run_id, attempt_id))

    def _report(self, attempt_id, path=None):
        row = self.get(attempt_id)
        spec = self.experiment(row["experiment_hash"]).content()
        path = path or self.reports / attempt_id
        manifest = json.loads((path / "manifest.json").read_text())
        if (path / "manifest.json").is_symlink() or (row["status"] == "SUCCESS" and
                row["details"].get("manifest_hash") != digest(manifest)):
            raise QuantError("CORRUPT_RESEARCH_REPORT", "已注册报告的清单指纹不一致")
        if (manifest.get("run_id") != attempt_id or manifest.get("schema_version") != 2 or
            manifest.get("research_context", {}).get("experiment_hash") != row["experiment_hash"] or
            manifest.get("source_hash") != spec["source_hash"] or manifest.get("data_bundle") != spec["data_bundle"] or
            manifest.get("config") != spec["config"] or manifest.get("members") != spec["members"] or
            manifest.get("benchmark_member_id") != spec["benchmark_member_id"] or manifest.get("completeness") != "COMPLETE"):
            raise QuantError("CORRUPT_RESEARCH_REPORT", "报告与冻结实验不一致，禁止发布")
        files = manifest.get("files", {})
        if not files or set(files) != {item.name for item in path.iterdir() if item.name != "manifest.json"}:
            raise QuantError("CORRUPT_RESEARCH_REPORT", "报告文件清单不完整")
        for name, expected in files.items():
            item = path / name
            if Path(name).name != name or item.is_symlink() or not item.is_file() or hashlib.sha256(item.read_bytes()).hexdigest() != expected:
                raise QuantError("CORRUPT_RESEARCH_REPORT", "报告文件指纹不一致")
        return manifest

    def _publish(self, attempt_id):
        with daily_lock(self.root / ".daily.lock"), publication_lock(self.root):
            final = self.reports / attempt_id
            pending = self.reports / (".pending-" + attempt_id)
            manifest = self._report(attempt_id, final if final.exists() else pending)
            if not final.exists():
                os.replace(pending, final)
            if self.after_publish:
                self.after_publish("FILES_PUBLISHED")
            self._finish(attempt_id, "SUCCESS", {"report": str(final), "manifest_hash": digest(manifest)}, attempt_id)
            if self.after_publish:
                self.after_publish("DB_COMMITTED")
            write_json(self.reports / "latest.json", {"run_id": attempt_id})
            if self.after_publish:
                self.after_publish("LATEST_UPDATED")
            return manifest

    def run(self, attempt_id):
        with daily_lock(self.root / ".research.lock"):
            with self.ledger.transaction():
                row = self.get(attempt_id)
                if row["status"] == "SUCCESS":
                    return self._report(attempt_id)
                if row["status"] != "CREATED":
                    raise QuantError("ATTEMPT_NOT_STARTABLE", "该尝试不能重复计算；先恢复或显式新建重跑")
                self.ledger.connection.execute("UPDATE research_attempts SET status='RUNNING',started_at=?,worker=? WHERE attempt_id=?",
                    (now_utc(), canonical(process_identity()), attempt_id))
            try:
                spec = self.experiment(row["experiment_hash"])
                spec.require_current_implementation()
                body = spec.content()
                config = Config.from_dict(body["config"])
                bundle = DataBundle(**body["data_bundle"])
                factors = FactorStore(self.root / "factors")
                selector = (lambda strategy, decision: factors.select(bundle.factor_snapshot_id, strategy, decision)) if bundle.factor_snapshot_id else None
                run_research(DataStore(self.root / "data"), config, self.reports, bundle.signal_snapshot_id,
                    members={key: StrategySpec.from_dict(item) for key, item in body["members"].items()},
                    benchmark=body["benchmark_member_id"], bundle=bundle, factor_selector=selector,
                    execution_id=attempt_id, publish_latest=False, defer_publication=True,
                    research_context={"experiment_hash": row["experiment_hash"], "purpose": body["purpose"],
                        "evaluation_seen": body["evaluation_seen"], "contains_test_factors": body["contains_test_factors"]})
                with self.ledger.transaction():
                    self.ledger.connection.execute("UPDATE research_attempts SET status='PUBLISHING' WHERE attempt_id=?", (attempt_id,))
                return self._publish(attempt_id)
            except Exception as exc:
                if self.get(attempt_id)["status"] not in {"PUBLISHING", "SUCCESS"}:
                    self._finish(attempt_id, "FAILED", {"code": getattr(exc, "code", "RESEARCH_FAILED"), "message": str(exc)})
                raise

    def recover(self):
        result = []
        with daily_lock(self.root / ".research-submission.lock"), daily_lock(self.root / ".research.lock"):
            for row in self.list():
                status = row["status"]
                if status == "SUCCESS":
                    self._report(row["attempt_id"])
                    continue
                if status not in {"CREATED", "RUNNING", "PUBLISHING"}:
                    continue
                if worker_alive(row["worker"]):
                    result.append({"attempt_id": row["attempt_id"], "status": "WORKER_ALIVE"})
                    continue
                if status == "PUBLISHING":
                    try:
                        self._publish(row["attempt_id"])
                        result.append({"attempt_id": row["attempt_id"], "status": "RECOVERED"})
                    except (QuantError, OSError, ValueError) as exc:
                        if self.get(row["attempt_id"])["status"] != "SUCCESS":
                            self._finish(row["attempt_id"], "FAILED", {"code": "RECOVERY_REPORT_INVALID", "message": str(exc)})
                            result.append({"attempt_id": row["attempt_id"], "status": "FAILED"})
                        else:
                            raise
                elif status == "CREATED" and row["worker"] is None:
                    result.append({"attempt_id": row["attempt_id"], "status": "NEEDS_START"})
                else:
                    self._finish(row["attempt_id"], "INTERRUPTED", {"message": "原工作进程已结束；可显式建立新的重跑尝试"})
                    result.append({"attempt_id": row["attempt_id"], "status": "INTERRUPTED"})
            successful = self.ledger.connection.execute("SELECT run_id FROM research_attempts WHERE status='SUCCESS' ORDER BY finished_at DESC LIMIT 1").fetchone()
            if successful:
                with daily_lock(self.root / ".daily.lock"), publication_lock(self.root):
                    write_json(self.reports / "latest.json", {"run_id": successful[0]})
        return {"status": "SUCCESS", "recovered": result}
