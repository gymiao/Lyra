from pathlib import Path

from personal_quant.common import decimal as D
from personal_quant.config import Config
from personal_quant.execution.replay import lifecycle
from personal_quant.portfolio import Ledger


def test_three_month_decisions_company_actions_withdrawal_and_restart(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    config = Config.load(root / "configs/lifecycle.toml")
    monkeypatch.chdir(tmp_path)
    first = lifecycle(config)
    assert len(first["checkpoints"]) == 9
    assert len(first["plans"]) == 3
    assert first["ledger_seq"] == 9
    assert D(first["final"]["settled_cash"]) == 350
    assert D(first["final"]["equity"]) == 800
    assert D(first["final"]["net_contributions"]) == 900
    assert D(first["final"]["investment_pnl"]) == -100
    report = Path(first["report"])
    curve = (report / "account_curve.csv").read_bytes()
    second = lifecycle(config)
    assert second["ledger_seq"] == 9
    assert first["plans"] == second["plans"]
    assert first["checkpoints"] == second["checkpoints"]
    assert (report / "account_curve.csv").read_bytes() == curve
    # A new connection after replay is a genuine database restart, not cached state.
    book = Ledger(Path(config.runtime_dir) / "account.sqlite", "demo")
    try:
        snapshot = book.snapshot("lifecycle-account", "2024-10-03T20:30:00Z", {"IEF": 50})
        assert D(snapshot["settled_cash"]) == 350
        assert D(snapshot["positions"]["IEF"]) == 9
        assert book.sequence("lifecycle-account") == 9
    finally:
        book.close()
