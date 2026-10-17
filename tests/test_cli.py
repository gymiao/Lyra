import json
from contextlib import closing
from pathlib import Path

from personal_quant.cli import main
from personal_quant.portfolio import Ledger
from conftest import event


def test_default_historical_signals_have_both_strategies_and_stable_archives(tmp_path, config, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    configuration = Path(__file__).resolve().parents[1] / "configs/demo.toml"
    assert main(["--config", str(configuration), "fixture"]) == 0
    capsys.readouterr()
    expected_dates = {"2024-07-31", "2024-08-30", "2024-09-30", "2024-10-31", "2024-11-29", "2024-12-31"}
    previous_ids = None
    for _ in range(2):
        assert main(["--config", str(configuration), "signals"]) == 0
        result = json.loads(capsys.readouterr().out)
        assert result["mode"] == "historical_reconstruction"
        assert result["counts"] == {"fixed": 6, "trend": 6}
        assert len(set(result["archive_ids"])) == 12
        records = json.loads((tmp_path / config.runtime_dir / "signals.json").read_text())
        assert set(records) == {"fixed", "trend"}
        assert all({row["decision_session"] for row in rows} == expected_dates for rows in records.values())
        if previous_ids is not None:
            assert result["archive_ids"] == previous_ids
        previous_ids = result["archive_ids"]
    with closing(Ledger(tmp_path / config.runtime_dir / "account.sqlite", "demo")) as book:
        assert book.connection.execute("SELECT count(*) FROM strategy_signals").fetchone()[0] == 12
        assert book.connection.execute("SELECT count(*) FROM events").fetchone()[0] == 0


def test_repeated_status_is_read_only_and_does_not_nest_task_results(tmp_path, config, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    configuration = Path(__file__).resolve().parents[1] / "configs/demo.toml"
    with closing(Ledger(tmp_path / config.runtime_dir / "account.sqlite", "demo")) as book:
        book.account("sample")
        book.import_events("sample", [event("deposit", "DEPOSIT", amount=1000)])
        book.record_task("historical-status", "SUCCESS", {"command": "status",
                         "result": {"tasks": [{"nested_payload": "x" * 100000}]}})
        book.record_task("failed-download", "FAILED", {"command": "fetch", "code": "DOWNLOAD_FAILED",
                         "message": "测试下载失败"})
        previous = [tuple(row) for row in book.connection.execute("SELECT * FROM tasks ORDER BY task_id")]
        for _ in range(3):
            assert main(["--config", str(configuration), "status"]) == 0
            output = capsys.readouterr().out
            assert len(output) < 2000  # Historical nested bodies must not expand diagnostics.
            diagnostics = json.loads(output)
            failure = next(row for row in diagnostics["tasks"] if row["task_id"] == "failed-download")
            assert failure["status"] == "FAILED"
            assert failure["code"] == "DOWNLOAD_FAILED" and failure["message"] == "测试下载失败"
            assert [tuple(row) for row in book.connection.execute("SELECT * FROM tasks ORDER BY task_id")] == previous
            assert book.sequence("sample") == 1
