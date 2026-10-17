from dataclasses import replace

import pytest

from personal_quant.common import QuantError, decimal as D
from personal_quant.execution.plans import PlanService
from personal_quant.execution.simulator import simulate
from personal_quant.strategies import signal
from conftest import event


def rotation(ledger, market, config):
    cfg = replace(config, symbols=("SPY", "IEF"), weights=(0, 1), active_strategy="fixed",
                  commission_bps=0, slippage_bps=0, fixed_fee=0, cash_buffer=0, max_weight=1)
    store, frame, _, calendar = market
    frame = frame.copy()
    frame[["open", "high", "low", "close", "adj_close"]] = 100.0
    meta = store.save(frame, calendar)
    ledger.import_events("sample", [event("deposit", "DEPOSIT", amount=1000),
                                    event("initial-buy", "BUY", symbol="SPY", quantity=10, price=100,
                                          settlement_at="2024-07-02T20:00:00Z")])
    ledger.reconcile("sample", {"account_id": "sample", "currency": "USD", "as_of": "2024-07-31T21:00:00Z",
                               "cash_basis": "settled", "cash": 0, "positions": {"SPY": 10}}, {"SPY": 100})
    value = signal(frame, calendar, cfg, "2024-07-31", "fixed", meta["snapshot_id"])
    service = PlanService(ledger, cfg)
    plan = service.create("sample", value, frame, meta, calendar, "2024-07-31T21:00:00Z")
    assert plan["execution_status"] == "READY", plan["payload"]["checks"]
    return service, plan, frame, meta, calendar


def test_sell_then_settlement_then_buy_without_fake_reconciliation(ledger, market, config):
    service, first, frame, meta, calendar = rotation(ledger, market, config)
    assert [(l["side"], l["symbol"], D(l["quantity"])) for l in first["payload"]["sizing"]["lines"]] == [("SELL", "SPY", D(10))]
    simulate(service, first["plan_id"], frame, calendar, "2024-08-01T21:00:00Z")
    first = service.get(first["plan_id"])
    assert first["execution_status"] == "FILLED"
    assert first["payload"]["intent_status"] == "WAITING_SETTLEMENT"
    assert D(ledger.snapshot("sample", "2024-08-01T21:00:00Z")["receivables"]) == 1000
    waiting = service.revise(first["plan_id"], frame, meta, calendar, "2024-08-01T21:00:00Z")
    assert waiting["payload"]["intent_status"] == "WAITING_SETTLEMENT"
    assert waiting["payload"]["sizing"]["lines"] == []
    assert service.revise(waiting["plan_id"], frame, meta, calendar, "2024-08-01T21:05:00Z")["plan_id"] == waiting["plan_id"]
    next_plan = service.revise(waiting["plan_id"], frame, meta, calendar, "2024-08-02T21:00:00Z")
    assert next_plan["execution_status"] == "READY", next_plan["payload"]["checks"]
    assert next_plan["payload"]["execution_session"] == "2024-08-05"
    assert next_plan["payload"]["reconciliation"]["advanced_events"] == 1
    simulate(service, next_plan["plan_id"], frame, calendar, "2024-08-05T21:00:00Z")
    final = service.get(next_plan["plan_id"])
    assert final["execution_status"] == "FILLED"
    assert final["payload"]["intent_status"] == "COMPLETE"
    snapshot = ledger.snapshot("sample", "2024-08-06T21:00:00Z", {"IEF": 100})
    assert D(snapshot["equity"]) == 1000
    assert D(snapshot["settled_cash"]) == 0
    assert {s: D(q) for s, q in snapshot["positions"].items()} == {"IEF": D(10)}
    with pytest.raises(QuantError) as failure:
        service.revise(next_plan["plan_id"], frame, meta, calendar, "2024-08-06T21:00:00Z")
    assert failure.value.code == "CLOSED_INTENT"


def test_config_change_cannot_open_second_intent_in_same_month(ledger, market, config):
    service, first, frame, meta, calendar = rotation(ledger, market, config)
    cfg = replace(service.config, fixed_fee=1)
    changed_signal = signal(frame, calendar, cfg, "2024-07-31", "fixed", meta["snapshot_id"])
    result = PlanService(ledger, cfg).create("sample", changed_signal, frame, meta, calendar, "2024-07-31T21:00:00Z")
    assert result["plan_id"] == first["plan_id"]
    assert ledger.connection.execute("SELECT count(*) FROM plans").fetchone()[0] == 1


def test_new_deposit_closes_waiting_intent_without_rewriting_filled_sell(ledger, market, config):
    service, first, frame, meta, calendar = rotation(ledger, market, config)
    simulate(service, first["plan_id"], frame, calendar, "2024-08-01T21:00:00Z")
    ledger.import_events("sample", [event("salary", "DEPOSIT", amount=100, effective_at="2024-08-02T21:00:00Z")])
    first = service.get(first["plan_id"])
    assert first["execution_status"] == "FILLED"
    assert first["payload"]["intent_status"] == "CLOSED"
    with pytest.raises(QuantError, match="意图已结束"):
        service.revise(first["plan_id"], frame, meta, calendar, "2024-08-02T21:00:00Z")


def test_unassociated_fill_and_late_reversal_invalidate_baseline(ledger, market, config):
    service, _, _, _, _ = rotation(ledger, market, config)
    ledger.import_events("sample", [event("unassociated", "SELL", symbol="SPY", quantity=1, price=100,
                                        effective_at="2024-08-01T20:00:00Z", settlement_at="2024-08-02T20:00:00Z")])
    with pytest.raises(QuantError, match="未关联"):
        ledger.check_reconciliation("sample", "2024-08-02T21:00:00Z", 7)
    ledger.import_events("sample", [event("reverse", "REVERSAL", reference_event_id="unassociated", effective_at="2024-08-01T20:00:00Z")])
    with pytest.raises(QuantError, match="更正"):
        ledger.check_reconciliation("sample", "2024-08-02T21:00:00Z", 7)


def test_day_expiry_does_not_erase_partial_fact(ledger, market, config):
    service, plan, _, _, _ = rotation(ledger, market, config)
    ledger.import_events("sample", [event("partial", "SELL", symbol="SPY", quantity=4, price=100,
                                        plan_id=plan["plan_id"], effective_at="2024-08-01T20:00:00Z",
                                        settlement_at="2024-08-02T20:00:00Z")])
    updated = service.refresh(plan["plan_id"], "2024-08-02T21:00:00Z")
    assert updated["execution_status"] == "PARTIAL"
    assert updated["check_status"] == "BLOCKED"
    assert updated["payload"]["checks"][0]["code"] == "DAY_PLAN_EXPIRED"
    assert D(updated["reserved_positions"]["SPY"]) == 6


def test_actual_statement_advancement_requires_explicit_complete_coverage(ledger, market, config):
    service, plan, _, _, _ = rotation(ledger, market, config)
    ledger.import_events("sample", [event("actual-fill", "SELL", symbol="SPY", quantity=10, price=100,
                                        plan_id=plan["plan_id"], evidence_type="actual", effective_at="2024-08-01T20:00:00Z",
                                        settlement_at="2024-08-02T20:00:00Z")])
    with pytest.raises(QuantError, match="覆盖"):
        ledger.check_reconciliation("sample", "2024-08-02T21:00:00Z", 7)
    ledger.record_coverage("sample", "2024-08-02T21:00:00Z", "independent_statement_fixture", "a" * 64)
    checked = ledger.check_reconciliation("sample", "2024-08-02T21:00:00Z", 7)
    assert checked["advanced_events"] == 1


def test_late_manual_notification_preserves_expired_commitments(ledger, market, config):
    service, plan, _, _, _ = rotation(ledger, market, config)
    service.manual_pending(plan["plan_id"], True, "2024-08-09T21:00:00Z")
    late = service.get(plan["plan_id"])
    assert late["execution_status"] == "EXPIRED"
    assert late["manual_pending"] == 1
    assert D(late["reserved_positions"]["SPY"]) == 10
    with pytest.raises(QuantError, match="人工订单"):
        service.cancel(plan["plan_id"])
    service.manual_pending(plan["plan_id"], False, "2024-08-09T21:00:00Z")
    assert service.get(plan["plan_id"])["reserved_positions"] == {}


def test_split_normalizes_partial_fill_and_remaining_sell_resources(ledger, market, config):
    service, plan, frame, _, calendar = rotation(ledger, market, config)
    ledger.import_events("sample", [event("partial-before-split", "SELL", symbol="SPY", quantity=4, price=100,
                                        plan_id=plan["plan_id"], effective_at="2024-08-01T20:00:00Z",
                                        settlement_at="2024-08-02T20:00:00Z"),
                                    event("split", "SPLIT", symbol="SPY", ratio=2, effective_at="2024-08-02T13:30:00Z")])
    partial = service.get(plan["plan_id"])
    assert partial["execution_status"] == "PARTIAL"
    assert partial["check_status"] == "BLOCKED"
    assert D(partial["reserved_positions"]["SPY"]) == 12  # (10-4)*2
    assert D(partial["payload"]["remaining"][0]["filled_quantity"]) == 8
    frame = frame.copy()
    frame.loc[(frame.symbol == "SPY") & (frame.session_date >= "2024-08-02"), ["open", "high", "low", "close"]] = 50
    frame.loc[(frame.symbol == "SPY") & (frame.session_date == "2024-08-02"), "split_ratio"] = 2
    store = market[0]
    meta = store.save(frame, calendar)
    next_plan = service.revise(plan["plan_id"], frame, meta, calendar, "2024-08-02T21:00:00Z")
    assert next_plan["execution_status"] == "READY", next_plan["payload"]["checks"]
    sales = [l for l in next_plan["payload"]["sizing"]["lines"] if l["side"] == "SELL"]
    assert len(sales) == 1 and D(sales[0]["quantity"]) == 12


def test_events_already_imported_after_baseline_time_still_require_coverage(ledger):
    # A statement contains both dates before the older snapshot is reconciled.
    ledger.import_events("sample", [event("initial", "DEPOSIT", amount=1000, evidence_type="actual"),
        event("later", "DEPOSIT", amount=100, evidence_type="actual", effective_at="2024-07-20T20:00:00Z")])
    ledger.reconcile("sample", {"account_id": "sample", "currency": "USD", "as_of": "2024-07-15T21:00:00Z",
        "cash_basis": "settled", "cash": 1000, "positions": {}})
    with pytest.raises(QuantError) as exc:
        ledger.check_reconciliation("sample", "2024-07-21T21:00:00Z", 7)
    assert exc.value.code == "INCOMPLETE_STATEMENT_COVERAGE"
    ledger.record_coverage("sample", "2024-07-21T21:00:00Z", "independent_statement", "a" * 64)
    assert ledger.check_reconciliation("sample", "2024-07-21T21:00:00Z", 7)["advanced_events"] == 1
