import json
from types import SimpleNamespace
from pathlib import Path

from personal_quant.common import QuantError, decimal as D
from personal_quant.data.quotes import quote_set
from personal_quant.portfolio.report import account_report, report_from_store, load_account_report, xirr
from conftest import event
import pytest


def test_stale_or_unqualified_quote_does_not_turn_into_current_equity(ledger, market, config, tmp_path):
    store, frame, _, calendar = market
    clock = "2024-08-01T21:00:00Z"
    ledger.import_events("sample", [event("deposit", "DEPOSIT", amount=1000),
                                    event("buy", "BUY", symbol="SPY", quantity=5, price=100,
                                          settlement_at="2024-07-02T20:00:00Z")])
    missing = frame.loc[~((frame.symbol == "SPY") & (frame.session_date == "2024-08-01"))]
    store.save(missing, calendar)
    report = report_from_store(ledger, "sample", clock, store, config, tmp_path / "reports")
    assert report["equity"] is None
    assert report["investment_pnl"] is None
    assert report["valuation"]["quotes"]["SPY"]["status"] == "STALE"
    assert D(report["settled_cash"]) == 500
    altered = frame.copy()
    altered["price_basis"] = "provider_split_adjusted"
    result = quote_set(altered, calendar, config, clock, ["SPY"])
    assert result["prices"] == {}
    assert result["quotes"]["SPY"]["status"] == "UNQUALIFIED_UNIT"


def test_quote_freshness_on_weekend_uses_last_completed_session(market, config):
    _, frame, _, calendar = market
    result = quote_set(frame, calendar, config, "2024-08-04T21:00:00Z", ["SPY"])
    assert result["expected_session"] == "2024-08-02"
    assert result["status"] == "COMPLETE"
    assert result["quotes"]["SPY"]["session"] == "2024-08-02"


def test_cash_only_account_valuation_does_not_require_fake_quotes(ledger, market, config, tmp_path):
    store = market[0]
    report = report_from_store(ledger, "sample", "2026-10-08T21:00:00Z", store, config, tmp_path / "reports")
    assert D(report["equity"]) == 0
    assert report["valuation"]["status"] == "CASH_ONLY"


def test_account_report_revisions_preserve_previous_content(ledger, tmp_path):
    directory = tmp_path / "reports"
    ledger.import_events("sample", [event("deposit", "DEPOSIT", amount=1000)])
    first = account_report(ledger, "sample", "2024-07-31T21:00:00Z", {}, directory)
    previous = directory / "versions" / first["report_id"] / "account.json"
    content = previous.read_bytes()
    ledger.import_events("sample", [event("salary", "DEPOSIT", amount=500)])
    second = account_report(ledger, "sample", "2024-07-31T21:00:00Z", {}, directory)
    assert first["report_id"] != second["report_id"]
    assert previous.read_bytes() == content
    assert D(load_account_report(directory)["equity"]) == 1500
    assert D(load_account_report(directory)["investment_pnl"]) == 0


def test_corrupt_published_report_is_not_silently_reused(ledger, tmp_path):
    first = account_report(ledger, "sample", "2024-07-31T21:00:00Z", {}, tmp_path)
    (tmp_path / "versions" / first["report_id"] / "account.md").write_text("corrupt")
    with pytest.raises(QuantError, match="哈希"):
        load_account_report(tmp_path)


def test_xirr_rejects_nonfinite_library_result(ledger, monkeypatch):
    ledger.import_events("sample", [event("deposit", "DEPOSIT", amount=1000)])
    monkeypatch.setitem(__import__('sys').modules, 'pyxirr', SimpleNamespace(xirr=lambda *args: float('nan')))
    result = xirr(ledger, "sample", "2024-07-31T21:00:00Z", 1000)
    assert result["value"] is None and "非有限" in result["reason"]


def test_actual_xirr_does_not_count_new_contributions_as_profit(ledger):
    pytest.importorskip("pyxirr", reason="真实XIRR库验收需要personal-return扩展")
    ledger.import_events("sample", [
        event("opening", "DEPOSIT", amount=1000),
        event("salary", "DEPOSIT", amount=500, effective_at="2024-10-01T20:00:00Z"),
    ])
    # Cash only: $1500 terminal assets are exactly $1000 + $500 contributions.
    result = xirr(ledger, "sample", "2025-07-01T20:00:00Z", 1500)
    assert result["reason"] is None
    assert result["value"] == pytest.approx(0, abs=1e-10)


def test_actual_xirr_matches_one_year_investor_cash_flows(ledger):
    pytest.importorskip("pyxirr", reason="真实XIRR库验收需要personal-return扩展")
    ledger.import_events("sample", [event("opening", "DEPOSIT", amount=1000)])
    # 2024-07-01 to 2025-07-01 is 365 days. One 1000 outflow and 1100
    # terminal value yield 10%; internal buy/sell/dividend flows are excluded.
    result = xirr(ledger, "sample", "2025-07-01T20:00:00Z", 1100)
    assert result["reason"] is None
    assert result["value"] == pytest.approx(0.1, abs=1e-10)
