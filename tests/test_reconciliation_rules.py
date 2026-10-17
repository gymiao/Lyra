from dataclasses import replace
import json

import pytest

from personal_quant.common import QuantError, decimal as D
from personal_quant.portfolio import Ledger
from personal_quant.portfolio.reconciliation import ReconciliationRules
from personal_quant.execution.plans import PlanService
from conftest import event
from test_revisions import rotation

AS_OF = "2024-07-31T21:00:00Z"


def holding(ledger):
    ledger.import_events("sample", [event("deposit", "DEPOSIT", amount=1100),
        event("buy", "BUY", symbol="SPY", quantity=1, price=100, settlement_at="2024-07-02T20:00:00Z")])
    return {"account_id": "sample", "currency": "USD", "as_of": AS_OF, "cash_basis": "settled",
            "cash": "1000.1", "positions": {"SPY": "1.001"}, "equity": "1100.01"}


def test_independent_tolerance_boundaries_preserve_exact_facts(ledger):
    expected = holding(ledger)
    rules = ReconciliationRules("0.1", "0.001", "0.01")
    result = ledger.reconcile("sample", expected, {"SPY": 100}, rules=rules)
    assert result["status"] == "PASSED"
    assert result["rules"] == {"schema_version": 1, "cash": "0.1", "quantity": "0.001", "equity": "0.01"}
    assert D(result["snapshot"]["settled_cash"]) == 1000
    assert D(result["snapshot"]["positions"]["SPY"]) == 1
    assert D(result["snapshot"]["equity"]) == 1100


@pytest.mark.parametrize("field", ["cash", "quantity", "equity"])
def test_one_unit_beyond_each_tolerance_exposes_that_difference(ledger, field):
    expected = holding(ledger)
    if field == "quantity":
        expected["positions"]["SPY"] = "1.00100001"
        key = "SPY"
    else:
        expected[field] = "1000.10000001" if field == "cash" else "1100.01000001"
        key = field
    result = ledger.reconcile("sample", expected, {"SPY": 100}, rules=ReconciliationRules("0.1", "0.001", "0.01"))
    assert result["status"] == "DIFFERENCES"
    assert set(result["differences"]) == {key}


def test_zero_tolerance_does_not_hide_fractional_difference(ledger):
    expected = holding(ledger)
    result = ledger.reconcile("sample", expected, {"SPY": 100}, rules=ReconciliationRules(0, 0, 0))
    assert set(result["differences"]) == {"cash", "SPY", "equity"}


def test_changed_rules_block_plan_revision_until_reconciliation(ledger, market, config):
    service, first, frame, meta, calendar = rotation(ledger, market, config)
    cfg = replace(service.config, reconciliation_cash_tolerance=0)
    updated = PlanService(ledger, cfg).revise(first["plan_id"], frame, meta, calendar, AS_OF)
    assert updated["check_status"] == "BLOCKED"
    assert updated["payload"]["checks"][0]["code"] == "RECONCILIATION_RULES_CHANGED"
    ledger.reconcile("sample", {"account_id": "sample", "currency": "USD", "as_of": AS_OF,
        "cash_basis": "settled", "cash": 0, "positions": {"SPY": 10}}, {"SPY": 100},
        rules=ReconciliationRules.from_config(cfg))
    retry = PlanService(ledger, cfg).revise(updated["plan_id"], frame, meta, calendar, AS_OF)
    assert retry["execution_status"] == "READY", retry["payload"]["checks"]
    saved = ledger.connection.execute("SELECT details FROM reconciliations ORDER BY id DESC LIMIT 1").fetchone()[0]
    assert json.loads(saved)["rules_hash"] == retry["payload"]["reconciliation"]["rules_hash"]


def test_real_reconciliation_requires_explicit_tolerances(tmp_path):
    real = Ledger(tmp_path / "real.sqlite", "real")
    try:
        real.account("real")
        expected = {"account_id": "real", "currency": "USD", "as_of": AS_OF, "cash_basis": "settled",
            "cash": 0, "positions": {}, "source": "broker_empty_account_fixture", "evidence_hash": "a" * 64}
        with pytest.raises(QuantError) as exc:
            real.reconcile("real", expected)
        assert exc.value.code == "MISSING_RECONCILIATION_CONFIG"
        assert real.connection.execute("SELECT count(*) FROM reconciliations").fetchone()[0] == 0
        assert real.reconcile("real", expected, rules=ReconciliationRules(0, 0, 0))["status"] == "PASSED"
    finally:
        real.close()


@pytest.mark.parametrize("value", [-0.01, float("nan"), float("inf"), True])
def test_invalid_tolerances_are_rejected(config, value):
    with pytest.raises(QuantError):
        replace(config, reconciliation_cash_tolerance=value).validate()


def test_numerically_equivalent_tolerances_have_same_rule_identity():
    assert ReconciliationRules("0.0100", "0.0000000100", "0.010").hash == ReconciliationRules().hash


def test_real_baseline_needs_complete_coverage_after_its_time_even_without_imports(tmp_path):
    book = Ledger(tmp_path / "real.sqlite", "real")
    try:
        book.account("real")
        book.reconcile("real", {"account_id": "real", "currency": "USD", "as_of": "2024-07-15T21:00:00Z",
            "cash_basis": "settled", "cash": 0, "positions": {}, "source": "independent_empty_statement", "evidence_hash": "a" * 64},
            rules=ReconciliationRules(0, 0, 0))
        with pytest.raises(QuantError) as exc:
            book.check_reconciliation("real", "2024-07-16T21:00:00Z", 7, reference_time="2024-07-16T20:00:00Z")
        assert exc.value.code == "INCOMPLETE_STATEMENT_COVERAGE"
        book.record_coverage("real", "2024-07-16T21:00:00Z", "explicit_complete_statement", "b" * 64)
        assert book.check_reconciliation("real", "2024-07-16T21:00:00Z", 7)["advanced_events"] == 0
    finally:
        book.close()
