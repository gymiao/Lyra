from pathlib import Path
import pytest

from personal_quant.common import QuantError, decimal as D
from personal_quant.portfolio.imports import event_csv, snapshot_csv

ROOT = Path(__file__).resolve().parents[1]


def test_frozen_statement_reconciles_with_independent_manual_snapshot(ledger):
    events = event_csv((ROOT / "examples/test_statement.csv").read_bytes())
    ledger.import_events("sample", events)
    expected = snapshot_csv((ROOT / "examples/test_snapshot.csv").read_bytes())
    result = ledger.reconcile("sample", expected, {"SPY": "49.5"})
    assert result["status"] == "PASSED"
    actual = result["snapshot"]
    assert D(actual["settled_cash"]) == D("503.5")
    assert D(actual["positions"]["SPY"]) == 10
    assert D(actual["equity"]) == D("998.5")
    assert D(actual["investment_pnl"]) == D("-1.5")
    assert ledger.import_events("sample", events)["duplicates"] == 5


def test_csv_rejects_ambiguous_direction_and_duplicate_headers():
    for data in ["kind,side\nBUY,SELL\n", "kind,kind\nBUY,BUY\n"]:
        with pytest.raises(QuantError):
            event_csv(data)


def test_snapshot_requires_consistent_complete_cash_and_quantity():
    header = "account_id,as_of,currency,cash_basis,cash,symbol,quantity,source\n"
    row = "sample,2024-07-31T21:00:00Z,USD,settled,1000,SPY,5,test\n"
    with pytest.raises(QuantError, match="重复"):
        snapshot_csv(header + row + row)
    with pytest.raises(QuantError, match="数量"):
        snapshot_csv(header + row.replace(",SPY,5,", ",SPY,,"))
    with pytest.raises(QuantError, match="不一致"):
        snapshot_csv(header + row + row.replace(",1000,SPY,", ",1001,IEF,"))


def test_missing_positions_are_not_assumed_zero(ledger):
    with pytest.raises(QuantError, match="持仓"):
        ledger.reconcile("sample", {"account_id": "sample", "currency": "USD", "as_of": "2024-07-31T21:00:00Z",
                                    "cash_basis": "settled", "cash": 0})
