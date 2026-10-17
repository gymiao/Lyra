from pathlib import Path

import pytest

from personal_quant.common import QuantError, decimal as D
from personal_quant.execution.corporate import action_csv, apply_actions
from personal_quant.portfolio import Ledger
from conftest import event

ROOT = Path(__file__).resolve().parents[1]


def funded(ledger, amount=1000):
    ledger.import_events("sample", [event("deposit", "DEPOSIT", amount=amount),
                                    event("buy", "BUY", symbol="SPY", quantity=10, price=100,
                                          effective_at="2024-08-01T20:00:00Z", settlement_at="2024-08-02T20:00:00Z")])


def actions():
    return action_csv((ROOT / "examples/test_actions.csv").read_bytes())


def test_accrual_payment_split_and_rerun_conserve_assets(ledger):
    funded(ledger)
    definitions = actions()
    apply_actions(ledger, "sample", definitions, "2024-08-15T21:00:00Z")
    ex = ledger.snapshot("sample", "2024-08-15T21:00:00Z", {"SPY": 99})
    assert D(ex["settled_cash"]) == 0
    assert D(ex["receivables"]) == 10
    assert D(ex["equity"]) == 1000
    apply_actions(ledger, "sample", definitions, "2024-08-20T21:00:00Z")
    paid = ledger.snapshot("sample", "2024-08-20T21:00:00Z", {"SPY": 99})
    assert D(paid["settled_cash"]) == 10
    assert D(paid["receivables"]) == 0
    assert D(paid["equity"]) == 1000
    apply_actions(ledger, "sample", definitions, "2024-09-16T21:00:00Z")
    end = ledger.snapshot("sample", "2024-09-16T21:00:00Z", {"SPY": "49.5"})
    assert D(end["positions"]["SPY"]) == 20
    assert D(end["equity"]) == 1000
    sequence = ledger.sequence("sample")
    assert apply_actions(ledger, "sample", definitions, "2024-09-16T21:00:00Z")["added"] == 0
    assert ledger.sequence("sample") == sequence


def test_ex_day_new_buy_does_not_increase_dividend_entitlement(ledger):
    funded(ledger, 1500)
    ledger.import_events("sample", [event("ex-day-buy", "BUY", symbol="SPY", quantity=5, price=99,
                                        effective_at="2024-08-15T14:00:00Z", settlement_at="2024-08-16T20:00:00Z")])
    apply_actions(ledger, "sample", actions(), "2024-08-20T21:00:00Z")
    payments = [e for e in ledger.active_events("sample", "2024-08-20T21:00:00Z") if e["kind"] == "DIVIDEND_PAYMENT"]
    assert len(payments) == 1 and D(payments[0]["amount"]) == 10


def test_unknown_payment_date_does_not_manufacture_spendable_cash(ledger):
    funded(ledger)
    definition = actions()[0]
    definition.pop("payment_at")
    apply_actions(ledger, "sample", [definition], "2024-08-31T21:00:00Z")
    snap = ledger.snapshot("sample", "2024-08-31T21:00:00Z", {"SPY": 99})
    assert D(snap["available_cash"]) == 0
    assert D(snap["receivables"]) == 10


def test_withholding_is_cost_not_external_flow(ledger):
    funded(ledger)
    definition = {**actions()[0], "withholding_per_share": "0.2"}
    apply_actions(ledger, "sample", [definition], "2024-08-20T21:00:00Z")
    snap = ledger.snapshot("sample", "2024-08-20T21:00:00Z", {"SPY": 99})
    assert D(snap["settled_cash"]) == 8
    assert D(snap["equity"]) == 998
    assert D(snap["net_contributions"]) == 1000
    assert D(snap["investment_pnl"]) == -2


def test_action_not_available_yet_cannot_change_account(ledger):
    funded(ledger)
    definition = {**actions()[0], "available_at": "2024-08-16T21:00:00Z"}
    count = ledger.sequence("sample")
    assert apply_actions(ledger, "sample", [definition], "2024-08-15T21:00:00Z")["status"] == "WAITING"
    assert ledger.sequence("sample") == count


def test_action_revision_conflict_rolls_back_other_action_in_same_batch(ledger):
    funded(ledger)
    definition = actions()[0]
    apply_actions(ledger, "sample", [definition], "2024-08-15T21:00:00Z")
    count = ledger.sequence("sample")
    earlier_split = {**actions()[1], "effective_at": "2024-08-10T13:30:00Z", "available_at": "2024-08-01T21:00:00Z"}
    with pytest.raises(QuantError, match="冲突"):
        apply_actions(ledger, "sample", [earlier_split, {**definition, "amount_per_share": "2"}], "2024-08-20T21:00:00Z")
    assert ledger.sequence("sample") == count
    assert D(ledger.snapshot("sample", "2024-08-20T21:00:00Z", {"SPY": 99})["positions"]["SPY"]) == 10


def test_real_account_cannot_receive_assumed_company_events(tmp_path):
    ledger = Ledger(tmp_path / "real.sqlite", "real")
    ledger.account("actual")
    with pytest.raises(QuantError, match="真实公司行动"):
        apply_actions(ledger, "actual", actions(), "2024-08-20T21:00:00Z")
    assert ledger.sequence("actual") == 0
    ledger.close()
