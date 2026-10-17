"""Independent arithmetic acceptance scenario, not a replacement for bt."""
from __future__ import annotations

from pathlib import Path
import pandas as pd

from ..common import QuantError, decimal as D, write_json
from ..data.calendar import Calendar
from ..data.fixture import create_lifecycle_fixture
from ..data.store import DataStore
from ..portfolio import Ledger
from ..portfolio.reconciliation import ReconciliationRules
from ..portfolio.report import account_report
from ..strategies import Signal
from ..strategies.archive import SignalArchive
from .corporate import apply_actions
from .plans import PlanService
from .simulator import simulate


def lifecycle(config):
    expected_config = {"environment": "demo", "active_strategy": "trend", "research_capital": 1000,
                       "commission_bps": 0, "slippage_bps": 0, "fixed_fee": 0, "cash_buffer": 0,
                       "lot_size": 1, "lookback": 126, "evaluation_start": "2024-07-01", "evaluation_end": "2024-10-03"}
    if any(getattr(config, k) != v for k, v in expected_config.items()) or tuple(config.symbols) != ("SPY", "IEF") or tuple(config.weights) != (0.5, 0.5):
        raise QuantError("FIXTURE_CONFIG", "独立手算演示请显式使用 configs/lifecycle.toml，不改变用户参数")
    root = Path(config.runtime_dir)
    prices_file, calendar_file = create_lifecycle_fixture(root / "lifecycle-fixture")
    calendar = Calendar.csv(calendar_file, "synthetic_test_sessions")
    store = DataStore(root / "data")
    metadata = store.save(pd.read_csv(prices_file), calendar)
    frame, _, _ = store.load(metadata["snapshot_id"])
    book = Ledger(root / "account.sqlite", "demo")
    account = "lifecycle-account"
    output = root / "reports/lifecycle"
    output.mkdir(parents=True, exist_ok=True)
    actions = [
        {"action_id": "dividend-a", "kind": "CASH_DIVIDEND", "symbol": "SPY", "source": "lifecycle_fixture_v1", "data_type": "synthetic",
         "effective_at": "2024-08-15T13:30:00Z", "available_at": "2024-08-01T20:30:00Z", "qualification_at": "2024-08-15T13:30:00Z",
         "payment_at": "2024-08-20T13:30:00Z", "amount_per_share": "1", "withholding_per_share": "0"},
        {"action_id": "split-a", "kind": "SPLIT", "symbol": "SPY", "source": "lifecycle_fixture_v1", "data_type": "synthetic",
         "effective_at": "2024-09-16T13:30:00Z", "available_at": "2024-09-01T20:30:00Z", "ratio": "2"},
    ]
    # All values below are manual expectations, not derived from the tested ledger.
    expected = {
        "2024-07-31": (1000, {}, 1000),
        "2024-08-02": (0, {"SPY": 5, "IEF": 10}, 1000),
        "2024-08-15": (0, {"SPY": 5, "IEF": 10}, 1000),
        "2024-08-20": (5, {"SPY": 5, "IEF": 10}, 1000),
        "2024-08-30": (5, {"SPY": 5, "IEF": 10}, 1000),
        "2024-09-16": (5, {"SPY": 10, "IEF": 10}, 1000),
        "2024-09-30": (5, {"SPY": 10, "IEF": 10}, 900),
        "2024-10-02": (450, {"IEF": 9}, 900),
        "2024-10-03": (350, {"IEF": 9}, 800),
    }
    checkpoints, curves, plans = [], [], []
    try:
        book.account(account)
        book.import_events(account, [{"event_id": "fixture:deposit", "kind": "DEPOSIT", "amount": "1000",
                                      "effective_at": "2024-07-01T20:00:00Z", "source": "lifecycle_fixture_v1", "evidence_type": "test"}])
        service = PlanService(book, config)
        for day in calendar.sessions:
            session = str(day.date())
            if not config.evaluation_start <= session <= config.evaluation_end:
                continue
            clock = (calendar.close(day) + pd.Timedelta(minutes=30)).isoformat()
            apply_actions(book, account, actions, clock)
            today = frame.loc[frame.session_date == day]
            prices = dict(zip(today.symbol, today.close))
            for row in book.connection.execute("SELECT plan_id,payload FROM plans WHERE execution_status IN ('READY','PARTIAL')").fetchall():
                plan = service.get(row["plan_id"])
                if plan["payload"].get("execution_session") == session:
                    simulate(service, row["plan_id"], frame, calendar, clock)
            if session == "2024-10-03":
                book.import_events(account, [{"event_id": "fixture:withdrawal", "kind": "WITHDRAWAL", "amount": "100",
                                              "effective_at": "2024-10-03T20:15:00Z", "source": "lifecycle_fixture_v1", "evidence_type": "test"}])
            if session in expected:
                cash, positions, equity = expected[session]
                result = book.reconcile(account, {"account_id": account, "currency": "USD", "as_of": clock,
                                                  "cash_basis": "settled", "cash": str(cash), "positions": positions,
                                                  "equity": str(equity), "source": "independent_manual_fixture_v1"}, prices,
                                        rules=ReconciliationRules.from_config(config))
                if result["status"] != "PASSED":
                    raise QuantError("FIXTURE_RECONCILIATION", "独立节点对账失败：" + session)
                checkpoints.append({"session": session, "expected_cash": cash, "expected_positions": positions,
                                    "expected_equity": equity, "status": result["status"]})
            if day in calendar.month_ends():
                archived = SignalArchive(book).generate(frame, metadata, calendar, config, day)
                value = Signal(**archived["signal"])
                plan = service.create(account, value, frame, metadata, calendar, clock)
                if plan["check_status"] != "PASSED":
                    raise QuantError("FIXTURE_PLAN", str(plan["payload"]["checks"]))
                plans.append(plan["plan_id"])
            snap = book.snapshot(account, clock, prices)
            curves.append({"session": session, **{k: snap[k] for k in ("equity", "settled_cash", "receivables", "payables", "net_contributions", "investment_pnl")}})
        final_clock = "2024-10-03T20:30:00Z"
        final = account_report(book, account, final_clock, {"SPY": "39.5", "IEF": "50"}, output)
        if D(final["net_contributions"]) != 900 or D(final["investment_pnl"]) != -100:
            raise QuantError("FIXTURE_PROFIT", "出金不得计成投资亏损或收益")
        pd.DataFrame(curves).to_csv(output / "account_curve.csv", index=False)
        summary = {"status": "SUCCESS", "mode": "frozen_lifecycle_account_replay", "not_bt_acceptance": True,
                   "not_forward_evidence": True, "data_type": "synthetic", "snapshot_id": metadata["snapshot_id"],
                   "config": config.content(), "ledger_seq": book.sequence(account), "plans": plans,
                   "checkpoints": checkpoints, "actions": actions, "report": str(output), "final": final}
        write_json(output / "verification.json", summary)
        return summary
    finally:
        book.close()
