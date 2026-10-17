from dataclasses import replace
import json
from pathlib import Path

import pytest

from personal_quant.common import QuantError, write_json
from personal_quant.portfolio import Ledger
from personal_quant.strategies.store import enable_workbench
from personal_quant.strategies.spec import DataBundle
from personal_quant.research.experiments import ResearchSpec
from personal_quant.research.service import ResearchService, process_identity, worker_alive
from test_research_v15 import members


@pytest.fixture
def research_workspace(market, config, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings = replace(config, runtime_dir="runtime/demo")
    root = Path(settings.runtime_dir)
    from shutil import copytree
    copytree(market[0].root, root / "data")
    write_json(Path("config.json"), settings.content())
    book = Ledger(root / "account.sqlite", "demo")
    enable_workbench(book, Path("config.json"))
    bundle = DataBundle(market[2]["snapshot_id"], market[3].hash)
    spec = ResearchSpec.create(settings, members(settings), "benchmark", bundle)
    yield ResearchService(book), spec
    book.close()


def test_submission_deduplicates_attempts_and_preserves_explicit_reruns(research_workspace):
    service, spec = research_workspace
    first = service.submit(spec)
    assert service.submit(spec)["attempt_id"] == first["attempt_id"]
    report = service.run(first["attempt_id"])
    assert report["run_id"] == first["attempt_id"]
    assert service.submit(spec)["status"] == "SUCCESS"
    second = service.submit(spec, rerun=True)
    assert second["attempt_id"] != first["attempt_id"]
    assert len(service.list()) == 2
    assert service.get(first["attempt_id"])["status"] == "SUCCESS"
    assert service.ledger.connection.execute("SELECT count(*) FROM events").fetchone()[0] == 0


@pytest.mark.parametrize("boundary", ["FILES_PUBLISHED", "DB_COMMITTED"])
def test_publication_crash_recovers_without_recalculation(research_workspace, boundary):
    service, spec = research_workspace
    class Crash(BaseException):
        pass
    def crash(step):
        if step == boundary:
            raise Crash()
    service.after_publish = crash
    attempt = service.submit(spec)["attempt_id"]
    with pytest.raises(Crash):
        service.run(attempt)
    assert not (service.reports / "latest.json").exists()
    # A killed worker has no current owner. PID reuse cannot be mistaken for ownership.
    service.ledger.connection.execute("UPDATE research_attempts SET worker=NULL WHERE attempt_id=?", (attempt,))
    service.after_publish = None
    service.recover()
    assert service.get(attempt)["status"] == "SUCCESS"
    assert json.loads((service.reports / "latest.json").read_text())["run_id"] == attempt
    assert len(service.list()) == 1


def test_dead_worker_retains_attempt_and_pid_identity_is_not_pid_only(research_workspace):
    service, spec = research_workspace
    assert worker_alive(process_identity())
    fake = process_identity(); fake["start_ticks"] = "0"
    assert not worker_alive(fake)
    attempt = service.submit(spec)["attempt_id"]
    assert service.recover()["recovered"][0]["status"] == "NEEDS_START"
    service.ledger.connection.execute("UPDATE research_attempts SET status='RUNNING',worker=? WHERE attempt_id=?",
        (json.dumps(fake), attempt))
    assert service.recover()["recovered"][0]["status"] == "INTERRUPTED"
    assert service.submit(spec, rerun=True)["attempt_id"] != attempt


def test_tampered_report_cannot_be_republished(research_workspace):
    service, spec = research_workspace
    attempt = service.submit(spec)["attempt_id"]
    service.run(attempt)
    (service.reports / attempt / "nav.csv").write_text("tampered")
    with pytest.raises(QuantError, match="指纹"):
        service.recover()


def test_invalid_interrupted_publication_fails_and_allows_new_attempt(research_workspace):
    service, spec = research_workspace
    class Crash(BaseException):
        pass
    def crash(step):
        if step == "FILES_PUBLISHED":
            raise Crash()
    service.after_publish = crash
    attempt = service.submit(spec)["attempt_id"]
    with pytest.raises(Crash):
        service.run(attempt)
    (service.reports / attempt / "nav.csv").write_text("interrupted / corrupt")
    service.ledger.connection.execute("UPDATE research_attempts SET worker=NULL WHERE attempt_id=?", (attempt,))
    service.after_publish = None
    assert service.recover()["recovered"][0]["status"] == "FAILED"
    assert service.get(attempt)["details"]["code"] == "RECOVERY_REPORT_INVALID"
    assert not (service.reports / "latest.json").exists()
    assert service.submit(spec, rerun=True)["attempt_id"] != attempt
