from dataclasses import replace

import pytest

from personal_quant.common import QuantError, decimal as D, canonical
from personal_quant.execution.plans import PlanService, size_orders
from personal_quant.execution.simulator import simulate
from personal_quant.portfolio import Ledger
from personal_quant.strategies import signal
from conftest import event

DECISION = "2024-07-31T21:00:00Z"
EXECUTION = "2024-08-01T21:00:00Z"


def test_paper_simulator_cannot_advance_future_clock(tmp_path, config):
    book = Ledger(tmp_path / "paper.sqlite", "paper")
    try:
        book.account("paper")
        cfg = replace(config, environment="paper", runtime_dir="runtime/paper")
        with pytest.raises(QuantError) as exc:
            simulate(PlanService(book, cfg), "unsubmitted", None, None, "2099-01-01T00:00:00Z")
        assert exc.value.code == "FUTURE_SIMULATION_TIME"
        assert book.sequence("paper") == 0
    finally:
        book.close()


def planned(ledger, market, config, **overrides):
    config = replace(config, symbols=("SPY", "IEF"), weights=(0.5, 0.5), active_strategy="fixed",
                     commission_bps=0, slippage_bps=0, fixed_fee=1, cash_buffer=0.02,
                     **overrides)
    store, frame, _, calendar = market
    frame = frame.copy()
    for symbol, price in {"SPY": 100, "IEF": 50, "GLD": 100}.items():
        frame.loc[frame.symbol == symbol, ["open", "high", "low", "close", "adj_close"]] = price
    metadata = store.save(frame, calendar)
    ledger.import_events("sample", [event("deposit", "DEPOSIT", amount=1000)])
    ledger.reconcile("sample", {"account_id": "sample", "currency": "USD", "as_of": DECISION,
                               "cash_basis": "settled", "cash": 1000, "positions": {}})
    service = PlanService(ledger, config)
    value = signal(frame, calendar, config, "2024-07-31", "fixed", metadata["snapshot_id"])
    plan = service.create("sample", value, frame, metadata, calendar, DECISION)
    assert plan["execution_status"] == "READY", plan["payload"]["checks"]
    return service, plan, frame, calendar


def test_execution_matches_manual_cash_and_fees_and_is_idempotent(ledger, market, config):
    service, plan, frame, calendar = planned(ledger, market, config)
    result = simulate(service, plan["plan_id"], frame, calendar, EXECUTION)
    assert result["execution_status"] == "FILLED"
    before = ledger.snapshot("sample", EXECUTION, {"SPY": 100, "IEF": 50})
    assert {s: D(q) for s, q in before["positions"].items()} == {"IEF": D(9), "SPY": D(4)}
    assert D(before["settled_cash"]) == 1000
    assert D(before["payables"]) == 852
    assert D(before["equity"]) == 998
    assert D(before["reserved_cash"]) == 0
    assert D(before["available_cash"]) == 148
    settled = ledger.snapshot("sample", "2024-08-02T21:00:00Z", {"SPY": 100, "IEF": 50})
    assert D(settled["settled_cash"]) == 148
    assert D(settled["payables"]) == 0
    assert D(settled["investment_pnl"]) == -2
    sequence = ledger.sequence("sample")
    assert simulate(service, plan["plan_id"], frame, calendar, EXECUTION)["status"] == "NO_ACTION"
    assert ledger.sequence("sample") == sequence


def test_new_reconciliation_difference_blocks_existing_plan_without_releasing_resources(ledger, market, config):
    service, plan, frame, calendar = planned(ledger, market, config)
    before = ledger.snapshot("sample", DECISION)
    result = ledger.reconcile("sample", {"account_id": "sample", "currency": "USD", "as_of": DECISION,
                              "cash_basis": "settled", "cash": 999, "positions": {}})
    assert result["status"] == "DIFFERENCES"
    current = service.get(plan["plan_id"])
    assert current["execution_status"] == "READY"
    assert current["check_status"] == "BLOCKED"
    with pytest.raises(QuantError):
        simulate(service, plan["plan_id"], frame, calendar, EXECUTION)
    assert ledger.sequence("sample") == 1
    assert ledger.snapshot("sample", DECISION)["reserved_cash"] == before["reserved_cash"]
    assert ledger.snapshot("sample", EXECUTION)["positions"] == {}


def test_difference_does_not_erase_partial_fill_or_manual_commitments(ledger, market, config):
    service, plan, frame, calendar = planned(ledger, market, config)
    ledger.import_events("sample", [event("partial", "BUY", symbol="IEF", quantity=1, price=50, fee=1,
        plan_id=plan["plan_id"], effective_at="2024-08-01T20:00:00Z",
        settlement_at="2024-08-02T20:00:00Z")])
    service.manual_pending(plan["plan_id"], True, EXECUTION)
    before = service.get(plan["plan_id"])
    ledger.reconcile("sample", {"account_id": "sample", "currency": "USD", "as_of": EXECUTION,
        "cash_basis": "settled", "cash": 999, "positions": {"IEF": 1}})
    blocked = service.get(plan["plan_id"])
    assert blocked["execution_status"] == "PARTIAL"
    assert blocked["check_status"] == "BLOCKED"
    assert blocked["manual_pending"] == 1
    assert blocked["reserved_cash"] == before["reserved_cash"]
    assert ledger.snapshot("sample", EXECUTION, {"IEF":50})["positions"] == {"IEF":"1"}
    assert ledger.sequence("sample") == 2


def test_stale_reconciliation_prevents_execution_without_new_facts(ledger, market, config):
    service, plan, frame, calendar = planned(ledger, market, config, reconciliation_max_days=1)
    with pytest.raises(QuantError) as error:
        simulate(service, plan["plan_id"], frame, calendar, "2024-08-03T21:00:00Z")
    assert error.value.code == "STALE_RECONCILIATION"
    assert ledger.sequence("sample") == 1
    assert service.get(plan["plan_id"])["reserved_cash"] == plan["reserved_cash"]


@pytest.mark.parametrize("as_of", ["2024-08-01T19:59:00Z", "2024-08-01T20:01:00Z"])
def test_wait_for_close_and_actual_publication_without_writes(ledger, market, config, as_of):
    service, plan, frame, calendar = planned(ledger, market, config)
    sequence = ledger.sequence("sample")
    assert simulate(service, plan["plan_id"], frame, calendar, as_of)["status"] == "WAITING"
    assert ledger.sequence("sample") == sequence
    assert service.get(plan["plan_id"]) == plan


def test_execution_gap_cannot_overdraw_and_entire_batch_rolls_back(ledger, market, config):
    # Admit the deliberate 100% gap so this independently reaches the cash gate.
    service, plan, frame, calendar = planned(ledger, market, config, reference_deviation=2, price_jump_threshold=2)
    mask = frame.session_date == "2024-08-01"
    frame.loc[mask, "close"] *= 2
    with pytest.raises(QuantError) as error:
        simulate(service, plan["plan_id"], frame, calendar, EXECUTION)
    assert error.value.code == "INSUFFICIENT_CASH"
    assert ledger.sequence("sample") == 1
    assert service.get(plan["plan_id"]) == plan


def test_missing_execution_price_does_not_create_half_batch(ledger, market, config):
    service, plan, frame, calendar = planned(ledger, market, config)
    frame = frame.loc[~((frame.session_date == "2024-08-01") & (frame.symbol == "SPY"))]
    with pytest.raises(QuantError) as error:
        simulate(service, plan["plan_id"], frame, calendar, EXECUTION)
    assert error.value.code == "MISSING_PRICE"
    assert ledger.sequence("sample") == 1


def test_zero_volume_execution_bar_cannot_fill_a_ready_plan(ledger, market, config):
    service, plan, frame, calendar = planned(ledger, market, config)
    before = ledger.snapshot("sample", EXECUTION, {"SPY": 100, "IEF": 50})
    frame.loc[(frame.symbol == "SPY") & (frame.session_date == "2024-08-01"), "volume"] = 0
    with pytest.raises(QuantError) as error:
        simulate(service, plan["plan_id"], frame, calendar, EXECUTION)
    assert error.value.code == "DATA_QUALITY_BLOCKED"
    assert "NONPOSITIVE_VOLUME" in str(error.value)
    assert ledger.sequence("sample") == 1
    assert ledger.snapshot("sample", EXECUTION, {"SPY": 100, "IEF": 50}) == before
    assert service.get(plan["plan_id"]) == plan


def test_import_and_plan_projection_commit_together_before_restart(ledger, market, config):
    service, plan, _, _ = planned(ledger, market, config)
    ledger.import_events("sample", [event("one-fill", "BUY", symbol="SPY", quantity=1, price=100,
                                        fee=1, plan_id=plan["plan_id"], effective_at="2024-08-01T20:00:00Z",
                                        settlement_at="2024-08-02T20:00:00Z")])
    # No PlanService.refresh call: direct imports, UI imports and CLI imports share this path.
    book = Ledger(ledger.path, "demo")
    reopened = PlanService(book, config).get(plan["plan_id"])
    assert reopened["execution_status"] == "PARTIAL"
    assert D(reopened["reserved_cash"]) == 752  # 3*100+1 plus 9*50+1
    assert D(book.snapshot("sample", EXECUTION)["available_cash"]) == 147
    book.close()


def test_projection_failure_rolls_back_events_and_reservations(ledger, market, config, monkeypatch):
    service, plan, _, _ = planned(ledger, market, config)
    from personal_quant.portfolio import ledger as ledger_module
    real_update = ledger_module.refresh_account_plans

    def interrupted(*args):
        real_update(*args)
        raise RuntimeError("simulated process interruption before commit")

    monkeypatch.setattr(ledger_module, "refresh_account_plans", interrupted)
    with pytest.raises(RuntimeError, match="interruption"):
        ledger.import_events("sample", [event("new-cash", "DEPOSIT", amount=50,
                                             effective_at="2024-08-01T20:00:00Z")])
    assert ledger.sequence("sample") == 1
    assert service.get(plan["plan_id"]) == plan


def test_external_cash_closes_only_unsubmitted_remainder_and_preserves_pending(ledger, market, config):
    service, plan, _, _ = planned(ledger, market, config)
    service.manual_pending(plan["plan_id"], True)
    ledger.import_events("sample", [event("new-cash", "DEPOSIT", amount=50, effective_at="2024-08-01T20:00:00Z")])
    changed = service.get(plan["plan_id"])
    assert changed["execution_status"] == "CANCELLED"
    assert changed["check_status"] == "BLOCKED"
    assert D(changed["reserved_cash"]) == 852
    service.manual_pending(plan["plan_id"], False)
    assert D(service.get(plan["plan_id"])["reserved_cash"]) == 0


def test_completed_plan_survives_later_deposit(ledger, market, config):
    service, plan, frame, calendar = planned(ledger, market, config)
    simulate(service, plan["plan_id"], frame, calendar, EXECUTION)
    ledger.import_events("sample", [event("new-cash", "DEPOSIT", amount=50, effective_at="2024-08-02T21:00:00Z")])
    final = service.get(plan["plan_id"])
    assert final["execution_status"] == "FILLED"
    assert final["check_status"] == "PASSED"
    assert D(final["reserved_cash"]) == 0


def test_simulator_uses_frozen_costs_after_config_changes(ledger, market, config):
    service, plan, frame, calendar = planned(ledger, market, config)
    changed = PlanService(ledger, replace(service.config, fixed_fee=100, commission_bps=100))
    simulate(changed, plan["plan_id"], frame, calendar, EXECUTION)
    assert D(ledger.snapshot("sample", EXECUTION, {"SPY": 100, "IEF": 50})["equity"]) == 998


def test_preview_rolls_back_plan_changes_as_well_as_events(ledger, market, config):
    service, plan, _, _ = planned(ledger, market, config)
    result = ledger.preview("sample", [event("preview-cash", "DEPOSIT", amount=50,
                                            effective_at="2024-08-01T20:00:00Z")], EXECUTION)
    assert D(result["projected_snapshot"]["settled_cash"]) == 1050
    assert ledger.sequence("sample") == 1
    assert service.get(plan["plan_id"]) == plan
    assert ledger.connection.execute("SELECT count(*) FROM imports").fetchone()[0] == 1


def test_reserved_sell_units_cannot_be_reused(config):
    snapshot = {"positions": {"SPY": "10"}, "reserved_positions": {"SPY": "6"}, "equity": "1000",
                "anomalies": [], "available_cash": "0"}
    with pytest.raises(QuantError) as error:
        size_orders(snapshot, {"SPY": 0}, {"SPY": 100}, config)
    assert error.value.code == "INSUFFICIENT_POSITION"
