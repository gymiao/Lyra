import pytest
from personal_quant.common import QuantError, decimal as D
from personal_quant.portfolio import Ledger
from conftest import event

AS_OF = "2024-07-31T21:00:00+00:00"


def test_deposit_is_not_profit(ledger):
    ledger.import_events("sample", [event("deposit", "DEPOSIT", amount="1000"), event("buy", "BUY", symbol="SPY", quantity="5", price="100", settlement_at="2024-07-02T20:00:00Z")])
    before = ledger.snapshot("sample", AS_OF, {"SPY": 100})
    ledger.import_events("sample", [event("salary", "DEPOSIT", amount="500", effective_at="2024-07-10T20:00:00Z")])
    after = ledger.snapshot("sample", AS_OF, {"SPY": 100})
    assert D(before["equity"]) == 1000
    assert D(after["equity"]) == 1500
    assert D(after["investment_pnl"]) == 0


def test_fees_exactly_once(ledger):
    ledger.import_events("sample", [event("deposit", "DEPOSIT", amount="1000"), event("buy", "BUY", symbol="SPY", quantity=5, price=100, fee="1.5", settlement_at="2024-07-02T20:00:00Z")])
    snapshot = ledger.snapshot("sample", AS_OF, {"SPY": 100})
    assert D(snapshot["settled_cash"]) == D("498.5")
    assert D(snapshot["equity"]) == D("998.5")


def test_settlement_conserves_equity(ledger):
    ledger.import_events("sample", [event("deposit", "DEPOSIT", amount=500), event("buy", "BUY", symbol="SPY", quantity=5, price=100, settlement_at="2024-07-02T20:00:00Z"), event("sell", "SELL", symbol="SPY", quantity=5, price=100, effective_at="2024-07-03T20:00:00Z", settlement_at="2024-07-05T20:00:00Z")])
    pending = ledger.snapshot("sample", "2024-07-04T20:00:00Z", {"SPY": 100})
    settled = ledger.snapshot("sample", AS_OF, {"SPY": 100})
    assert D(pending["receivables"]) == 500
    assert D(pending["settled_cash"]) == 0
    assert D(pending["equity"]) == D(settled["equity"]) == 500
    assert D(settled["investment_pnl"]) == 0


def test_dividend_and_split_no_duplicate_assets(ledger):
    entries = [event("deposit", "DEPOSIT", amount=1000), event("buy", "BUY", symbol="SPY", quantity=10, price=100, settlement_at="2024-07-01T20:00:00Z"), event("div-ex", "DIVIDEND_ACCRUAL", amount=10, symbol="SPY", effective_at="2024-07-05T20:00:00Z")]
    ledger.import_events("sample", entries)
    ex = ledger.snapshot("sample", "2024-07-06T20:00:00Z", {"SPY": 99})
    assert D(ex["equity"]) == 1000
    payment = event("div-pay", "DIVIDEND_PAYMENT", amount=10, reference_event_id="div-ex", effective_at="2024-07-10T20:00:00Z")
    split = event("split", "SPLIT", symbol="SPY", ratio=2, effective_at="2024-07-15T20:00:00Z")
    ledger.import_events("sample", [payment, split])
    ledger.import_events("sample", [payment, split])
    snapshot = ledger.snapshot("sample", AS_OF, {"SPY": "49.5"})
    assert D(snapshot["positions"]["SPY"]) == 20
    assert D(snapshot["settled_cash"]) == 10
    assert D(snapshot["receivables"]) == 0
    assert D(snapshot["equity"]) == 1000


def test_duplicate_conflict_and_atomic_import(ledger):
    initial = event("deposit", "DEPOSIT", amount=1000)
    ledger.import_events("sample", [initial])
    assert ledger.import_events("sample", [initial])["duplicates"] == 1
    before = ledger.sequence("sample")
    with pytest.raises(QuantError, match="冲突"):
        ledger.import_events("sample", [event("new", "DEPOSIT", amount=10), {**initial, "amount": 2000}])
    assert ledger.sequence("sample") == before
    assert D(ledger.snapshot("sample", AS_OF)["settled_cash"]) == 1000


def test_identical_distinct_trades_both_recorded(ledger):
    ledger.import_events("sample", [event("deposit", "DEPOSIT", amount=2000), *[event(i, "BUY", symbol="SPY", quantity=5, price=100, settlement_at="2024-07-02T20:00:00Z") for i in ["fill1", "fill2"]]])
    assert D(ledger.snapshot("sample", AS_OF, {"SPY": 100})["positions"]["SPY"]) == 10


def test_reversal_restates_but_preserves_old_sequence(ledger):
    ledger.import_events("sample", [event("deposit", "DEPOSIT", amount=1000)])
    old_sequence = ledger.sequence("sample")
    ledger.import_events("sample", [event("undo", "REVERSAL", reference_event_id="deposit"), event("correct", "DEPOSIT", amount=900)])
    assert D(ledger.snapshot("sample", AS_OF)["settled_cash"]) == 900
    assert D(ledger.snapshot("sample", AS_OF, ledger_seq=old_sequence)["settled_cash"]) == 1000


def test_reconciliation_exposes_differences(ledger):
    ledger.import_events("sample", [event("deposit", "DEPOSIT", amount=1000)])
    expected = {"account_id": "sample", "currency": "USD", "as_of": AS_OF, "cash_basis": "settled", "cash": 999, "positions": {}}
    assert ledger.reconcile("sample", expected)["status"] == "DIFFERENCES"
    assert ledger.reconcile("sample", {**expected, "cash": 1000})["status"] == "PASSED"


def test_real_account_starts_empty_and_rejects_test_records(tmp_path):
    real = Ledger(tmp_path / "real.sqlite", "real")
    real.account("actual")
    assert D(real.snapshot("actual", AS_OF)["equity"]) == 0
    with pytest.raises(QuantError, match="真实账本"):
        real.import_events("actual", [event("fake", "DEPOSIT", amount=1000)])
    real.close()


def test_backup_restore(ledger, tmp_path):
    ledger.import_events("sample", [event("deposit", "DEPOSIT", amount=1000)])
    path = tmp_path / "backup.sqlite"
    ledger.backup(path)
    restored = Ledger(path, "demo")
    assert restored.snapshot("sample", AS_OF) == ledger.snapshot("sample", AS_OF)
    assert restored.import_events("sample", [event("deposit", "DEPOSIT", amount=1000)])["duplicates"] == 1
    restored.close()


def test_invalid_dividend_payment_rolls_back(ledger):
    with pytest.raises(QuantError, match="分红"):
        ledger.import_events("sample", [event("bad", "DIVIDEND_PAYMENT", amount=10, reference_event_id="missing")])
    assert ledger.sequence("sample") == 0


def test_stale_preview_rejected(ledger):
    ledger.import_events("sample", [event("deposit", "DEPOSIT", amount=1000)])
    with pytest.raises(QuantError, match="预检"):
        ledger.import_events("sample", [event("later", "DEPOSIT", amount=10)], expected_sequence=0)

