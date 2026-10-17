from dataclasses import replace
import pytest
from personal_quant.common import QuantError, decimal as D
from personal_quant.execution.plans import size_orders, PlanService
from personal_quant.strategies import signal
from conftest import event

AS_OF = "2024-07-31T21:00:00Z"


def ready(ledger, market, config):
    config = replace(config, active_strategy="fixed")
    _, frame, metadata, calendar = market
    ledger.import_events("sample", [event("deposit", "DEPOSIT", amount=10000)])
    ledger.reconcile("sample", {"account_id": "sample", "currency": "USD", "as_of": AS_OF, "cash_basis": "settled", "cash": 10000, "positions": {}})
    signal_value = signal(frame, calendar, config, "2024-07-31", "fixed", metadata["snapshot_id"])
    service = PlanService(ledger, config)
    plan = service.create("sample", signal_value, frame, metadata, calendar, AS_OF)
    return service, plan


def test_manual_budget_example(config):
    cfg = replace(config, symbols=("A", "B"), weights=(0.5, 0.5), commission_bps=0, slippage_bps=0, fixed_fee=1, cash_buffer=0.02)
    snapshot = {"positions": {}, "equity": "1000", "anomalies": [], "available_cash": "1000"}
    result = size_orders(snapshot, {"A": 0.5, "B": 0.5}, {"A": 100, "B": 50}, cfg)
    assert [(x["symbol"], D(x["quantity"])) for x in result["lines"]] == [("A", D(4)), ("B", D(9))]
    assert D(result["reserve"]) == 852
    assert D(result["estimated_fee"]) == 2


def test_removed_position_produces_sell(config):
    snapshot = {"positions": {"SPY": "10"}, "equity": "2000", "anomalies": [], "available_cash": "1000"}
    result = size_orders(snapshot, {"IEF": 0.5}, {"SPY": 100, "IEF": 100}, config)
    assert any(l["symbol"] == "SPY" and l["side"] == "SELL" and D(l["quantity"]) == 10 for l in result["lines"])


def test_reduce_buy_lots_to_account_for_sell_fees_and_post_trade_limit(config):
    cfg = replace(config, commission_bps=0, slippage_bps=0, fixed_fee=300, cash_buffer=0, max_weight=0.6)
    snapshot = {"positions": {"SPY": "5"}, "equity": "1500", "anomalies": [], "available_cash": "1000"}
    result = size_orders(snapshot, {"SPY": 0, "IEF": 0.6}, {"SPY": 100, "IEF": 1}, cfg)
    buys = [line for line in result["lines"] if line["side"] == "BUY"]
    # Selling costs 300 and buying costs 300: final equity is 900.
    # A 60% cap permits 540 one-dollar units, not the pre-fee 900-unit target.
    assert len(buys) == 1 and D(buys[0]["quantity"]) == 540
    assert D(result["estimated_fee"]) == 600
    assert D(result["projected_weights"]["IEF"]) == D("0.6")


def test_missing_price_and_empty_account(config):
    snapshot = {"positions": {"SPY": "10"}, "equity": None, "anomalies": [], "available_cash": "1000"}
    with pytest.raises(QuantError, match="不完整"):
        size_orders(snapshot, {"IEF": 0.5}, {"IEF": 100}, config)
    with pytest.raises(QuantError, match="空账户"):
        size_orders({"positions": {}, "equity": "0", "anomalies": [], "available_cash": "0"}, {"IEF": 0.5}, {"IEF": 100}, config)


def test_plan_rerun_and_reservation_conserve_nav(ledger, market, config):
    service, plan = ready(ledger, market, config)
    assert plan["execution_status"] == "READY", plan["payload"]["checks"]
    _, frame, metadata, calendar = market
    second = service.create("sample", signal(frame, calendar, service.config, "2024-07-31", "fixed", metadata["snapshot_id"]), frame, metadata, calendar, AS_OF)
    assert plan["plan_id"] == second["plan_id"]
    snapshot = ledger.snapshot("sample", AS_OF)
    assert D(snapshot["equity"]) == 10000
    assert D(snapshot["reserved_cash"]) > 0
    assert ledger.connection.execute("SELECT count(*) FROM plans").fetchone()[0] == 1


def test_pending_manual_order_cannot_release_funds(ledger, market, config):
    service, plan = ready(ledger, market, config)
    service.manual_pending(plan["plan_id"], True)
    before = ledger.snapshot("sample", AS_OF)["reserved_cash"]
    with pytest.raises(QuantError, match="人工订单"):
        service.cancel(plan["plan_id"])
    assert ledger.snapshot("sample", AS_OF)["reserved_cash"] == before


def test_partial_and_late_fill_after_cancel(ledger, market, config):
    service, plan = ready(ledger, market, config)
    first = plan["payload"]["sizing"]["lines"][0]
    fill = event("partial", "BUY", symbol=first["symbol"], quantity=1, price=first["price"], plan_id=plan["plan_id"], effective_at="2024-08-01T20:00:00Z", settlement_at="2024-08-02T20:00:00Z")
    ledger.import_events("sample", [fill])
    updated = service.refresh(plan["plan_id"], "2024-08-01T21:00:00Z")
    assert updated["execution_status"] == "PARTIAL"
    ledger.import_events("sample", [fill])
    assert service.refresh(plan["plan_id"], "2024-08-01T21:00:00Z")["payload"]["remaining"] == updated["payload"]["remaining"]
    service.cancel(plan["plan_id"])
    ledger.import_events("sample", [{**fill, "event_id": "late", "quantity": 2}])
    assert D(ledger.snapshot("sample", "2024-08-05T21:00:00Z", {first["symbol"]: first["price"]})["positions"][first["symbol"]]) == 3


def test_unresolved_reconciliation_blocks_plan(ledger, market, config):
    _, frame, metadata, calendar = market
    ledger.import_events("sample", [event("deposit", "DEPOSIT", amount=10000)])
    cfg = replace(config, active_strategy="fixed")
    value = signal(frame, calendar, cfg, "2024-07-31", "fixed", metadata["snapshot_id"])
    plan = PlanService(ledger, cfg).create("sample", value, frame, metadata, calendar, AS_OF)
    assert plan["execution_status"] == "DRAFT"
    assert plan["check_status"] == "BLOCKED"
    assert plan["reserved_cash"] == "0"
    assert plan["payload"]["checks"][0]["code"] == "UNRESOLVED_RECONCILIATION"
