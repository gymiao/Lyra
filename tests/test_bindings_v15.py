from dataclasses import replace
from pathlib import Path

import pytest

from personal_quant.common import QuantError, write_json
from personal_quant.portfolio import Ledger
from personal_quant.portfolio.reconciliation import ReconciliationRules
from personal_quant.portfolio.backup import create_bundle, restore_bundle, verify_bundle
from personal_quant.strategies.store import StrategyStore, enable_workbench
from personal_quant.strategies.bindings import BindingService
from personal_quant.strategies.spec import DataBundle, StrategySpec
from personal_quant.execution.plans import PlanService
from personal_quant.execution.simulator import simulate
from personal_quant.cli import references
from conftest import event


@pytest.fixture
def bound_workspace(market, config, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from shutil import copytree
    copytree(market[0].root, Path(config.runtime_dir) / "data")
    write_json(Path("config.json"), config.content())
    book = Ledger(Path(config.runtime_dir) / "account.sqlite", "demo")
    book.account("sample")
    enable_workbench(book, Path("config.json"))
    spec = StrategySpec.create("momentum_rotation", config.symbols)
    StrategyStore(book).publish(spec)
    yield BindingService(book, config), spec, market[1], market[2], market[3]
    book.close()


def test_deadline_and_concurrent_binding_preview(bound_workspace):
    service, spec, _, _, calendar = bound_workspace
    row = service.request("sample", "momentum_rotation", 1, calendar, as_of="2024-07-31T20:29:59Z",
                          expected_binding_seq=0, expected_account_seq=0)
    assert row["effective_session"] == "2024-07-31"
    with pytest.raises(QuantError, match="更新绑定"):
        service.request("sample", "momentum_rotation", 1, calendar, as_of="2024-07-31T20:29:59Z", expected_binding_seq=0)
    with pytest.raises(QuantError, match="追溯"):
        service.request("sample", "momentum_rotation", 1, calendar, as_of="2024-07-31T20:30:00Z", effective_session="2024-07-31")
    later = service.request("sample", "momentum_rotation", 1, calendar, as_of="2024-07-31T20:30:00Z")
    assert later["effective_session"] == "2024-08-30"


def test_full_plan_fill_idempotence_and_v3_backup_restore(bound_workspace):
    service, spec, frame, metadata, calendar = bound_workspace
    book = service.ledger
    book.import_events("sample", [event("cash", "DEPOSIT", amount=10000)])
    service.request("sample", "momentum_rotation", 1, calendar, as_of="2024-07-01T20:30:00Z")
    clock = "2024-07-31T20:30:00Z"
    quotes = references(frame, clock)
    book.reconcile("sample", {"account_id": "sample", "currency": "USD", "as_of": clock,
        "cash_basis": "settled", "cash": "10000", "positions": {}, "source": "independent_test_statement"},
        quotes, rules=ReconciliationRules.from_config(service.config))
    bundle = DataBundle(metadata["snapshot_id"], calendar.hash, execution_snapshot_id=metadata["snapshot_id"])
    result = service.decide("sample", bundle, "2024-07-31", as_of=clock)
    assert result["status"] == "READY"
    plan_id = result["plan_id"]
    assert service.decide("sample", bundle, "2024-07-31", as_of=clock)["plan_id"] == plan_id
    old = book.sequence("sample")
    outcome = simulate(PlanService(book, service.config), plan_id, frame, calendar, "2024-08-01T20:30:00Z")
    assert outcome["status"] == "SUCCESS"
    assert book.sequence("sample") > old
    assert simulate(PlanService(book, service.config), plan_id, frame, calendar, "2024-08-01T20:30:00Z")["status"] == "NO_ACTION"
    snapshot = book.snapshot("sample", "2024-08-02T20:30:00Z", references(frame, "2024-08-02T20:30:00Z"))
    assert snapshot["net_contributions"] == "10000"
    from personal_quant.strategies.drafts import DraftStore
    saved_draft = DraftStore(Path(service.config.runtime_dir) / "drafts").save(spec)
    create_bundle(Path(service.config.runtime_dir), Path("config.json"), Path("backup"))
    assert verify_bundle(Path("backup"), "demo")["database"]["version"] == 3
    restore_bundle(Path("backup"), Path("restored"), "demo")
    restored = Ledger(Path("restored/runtime/demo/account.sqlite"), "demo")
    try:
        assert restored.sequence("sample") == book.sequence("sample")
        assert StrategyStore(restored).get("momentum_rotation", 1).spec_hash == spec.spec_hash
        assert DraftStore(Path("restored/runtime/demo/drafts")).load(saved_draft["draft_id"])["hash"] == saved_draft["hash"]
        assert restored.snapshot("sample", "2024-08-02T20:30:00Z", references(frame, "2024-08-02T20:30:00Z")) == snapshot
    finally:
        restored.close()


def test_no_action_is_frozen_without_empty_plan(bound_workspace):
    service, _, frame, metadata, calendar = bound_workspace
    cash_spec = StrategySpec.create("fixed", service.config.symbols, strategy_id="cash",
        weights={symbol: 0 for symbol in service.config.symbols})
    StrategyStore(service.ledger).publish(cash_spec)
    service.request("sample", "cash", 1, calendar, as_of="2024-07-01T20:30:00Z")
    bundle = DataBundle(metadata["snapshot_id"], calendar.hash)
    result = service.decide("sample", bundle, "2024-07-31", as_of="2024-07-31T20:30:00Z")
    assert result["status"] == "NO_ACTION"
    assert service.ledger.connection.execute("SELECT count(*) FROM plans").fetchone()[0] == 0
    assert service.ledger.connection.execute("SELECT outcome FROM monthly_decisions").fetchone()[0] == "NO_ACTION"


def test_split_adjusted_execution_data_remains_blocked(bound_workspace):
    service, _, frame, metadata, calendar = bound_workspace
    from personal_quant.data.store import DataStore
    frame = frame.copy(); frame["price_basis"] = "provider_split_adjusted"
    raw_meta = DataStore(Path(service.config.runtime_dir) / "data").save(frame, calendar)
    service.request("sample", "momentum_rotation", 1, calendar, as_of="2024-07-01T20:30:00Z")
    bundle = DataBundle(metadata["snapshot_id"], calendar.hash, execution_snapshot_id=raw_meta["snapshot_id"])
    result = service.decide("sample", bundle, "2024-07-31", as_of="2024-07-31T20:30:00Z")
    assert result["status"] == "BLOCKED"
    assert result["checks"][0]["code"] == "UNQUALIFIED_EXECUTION_PRICE"


def test_deadline_blocked_switch_never_rolls_into_later_month(bound_workspace):
    service, _, frame, metadata, calendar = bound_workspace
    book = service.ledger
    book.import_events("sample", [event("cash", "DEPOSIT", amount=10000)])
    service.request("sample", "momentum_rotation", 1, calendar, as_of="2024-07-01T20:30:00Z", effective_session="2024-08-30")
    clock = "2024-07-31T20:30:00Z"
    book.reconcile("sample", {"account_id": "sample", "currency": "USD", "as_of": clock,
        "cash_basis": "settled", "cash": 10000, "positions": {}, "source": "independent_test"},
        references(frame, clock), rules=ReconciliationRules.from_config(service.config))
    from personal_quant.strategies import signal
    value = signal(frame, calendar, service.config, "2024-07-31", "trend", metadata["snapshot_id"])
    old_plan = PlanService(book, service.config).create("sample", value, frame, metadata, calendar, clock)
    assert old_plan["execution_status"] == "READY"
    PlanService(book, service.config).manual_pending(old_plan["plan_id"], True, clock)
    bundle = DataBundle(metadata["snapshot_id"], calendar.hash, execution_snapshot_id=metadata["snapshot_id"])
    blocked = service.decide("sample", bundle, "2024-08-30", as_of="2024-08-30T20:30:00Z")
    assert blocked["code"] == "BINDING_SWITCH_BLOCKED"
    assert service.list("sample")[0]["status"] == "BLOCKED"
    later = service.decide("sample", bundle, "2024-09-30", as_of="2024-09-30T20:30:00Z")
    assert later["code"] == "BINDING_SWITCH_BLOCKED"
    assert PlanService(book, service.config).get(old_plan["plan_id"])["manual_pending"] == 1


def test_daily_uses_bound_basket_and_no_action_covers_only_its_account(bound_workspace):
    service, _, frame, _, calendar = bound_workspace
    from personal_quant.data.store import DataStore
    from personal_quant.execution.daily import DailyRunner
    spec = StrategySpec.create("fixed", ["SPY", "IEF"], strategy_id="two_asset_cash", weights={"SPY": 0, "IEF": 0})
    StrategyStore(service.ledger).publish(spec)
    store = DataStore(Path(service.config.runtime_dir) / "data")
    store.save(frame.loc[frame.symbol.isin(["SPY", "IEF"])], calendar)
    service.request("sample", "two_asset_cash", 1, calendar, as_of="2024-07-01T20:30:00Z")
    runner = DailyRunner(service.ledger, service.config, store)
    result = runner.run("sample", as_of="2024-07-31T20:30:00Z")
    assert result["planning"]["status"] == "NO_ACTION"
    assert runner.config.symbols == ("IEF", "SPY")
    later = runner.run("sample", as_of="2024-08-02T20:30:00Z")
    assert later["tracking_gaps"]["months"] == []
    assert service.ledger.connection.execute("SELECT count(*) FROM events").fetchone()[0] == 0


def test_signal_prices_and_execution_prices_have_independent_roles(bound_workspace):
    service, _, frame, metadata, calendar = bound_workspace
    from decimal import Decimal, ROUND_FLOOR
    from personal_quant.data.store import DataStore
    raw = frame.copy()
    raw["source"] = "independent_synthetic_raw_prices"
    for column in ["open", "high", "low", "close"]:
        raw[column] *= 2
    raw_meta = DataStore(Path(service.config.runtime_dir) / "data").save(raw, calendar)
    book = service.ledger
    book.import_events("sample", [event("cash", "DEPOSIT", amount=10000)])
    clock = "2024-07-31T20:30:00Z"
    book.reconcile("sample", {"account_id": "sample", "currency": "USD", "as_of": clock,
        "cash_basis": "settled", "cash": 10000, "positions": {}, "source": "independent_test"},
        references(raw, clock), rules=ReconciliationRules.from_config(service.config))
    service.request("sample", "momentum_rotation", 1, calendar, as_of="2024-07-01T20:30:00Z")
    bundle = DataBundle(metadata["snapshot_id"], calendar.hash, execution_snapshot_id=raw_meta["snapshot_id"])
    result = service.decide("sample", bundle, "2024-07-31", as_of=clock)
    assert result["status"] == "READY"
    plan = PlanService(book, service.config).get(result["plan_id"])
    assert plan["payload"]["signal"]["snapshot_id"] == metadata["snapshot_id"]
    assert plan["payload"]["reference_snapshot_id"] == raw_meta["snapshot_id"]
    quotes = references(raw, clock)
    for line in plan["payload"]["sizing"]["lines"]:
        assert line["side"] == "BUY"
        expected = (Decimal(str(plan["payload"]["signal"]["target_weights"][line["symbol"]])) * 10000 / Decimal(str(quotes[line["symbol"]]))).to_integral_value(rounding=ROUND_FLOOR)
        assert Decimal(line["quantity"]) == expected
        assert float(line["price"]) == quotes[line["symbol"]]
