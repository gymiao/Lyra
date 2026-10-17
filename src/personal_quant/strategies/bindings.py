"""Explicit account bindings at a future monthly deadline, with frozen decisions."""
from __future__ import annotations

import json
from pathlib import Path
import pandas as pd

from ..common import QuantError, canonical, now_utc, utc
from ..data.store import DataStore
from ..execution.plans import PlanService
from ..locks import publication_lock
from .adapter import decode_signal, resolve
from .archive import SignalArchive
from .spec import DataBundle
from .store import StrategyStore


class BindingService:
    def __init__(self, ledger, config):
        self.ledger, self.config = ledger, config
        self.strategies = StrategyStore(ledger)

    def list(self, account_id):
        return [dict(row) for row in self.ledger.connection.execute(
            "SELECT * FROM strategy_bindings WHERE account_id=? ORDER BY binding_seq DESC", (account_id,))]

    def sequence(self, account_id):
        return self.ledger.connection.execute("SELECT COALESCE(max(binding_seq),0) FROM strategy_bindings WHERE account_id=?", (account_id,)).fetchone()[0]

    def request(self, account_id, strategy_id, revision, calendar, *, as_of=None,
                effective_session=None, expected_binding_seq=None, expected_account_seq=None):
        self.ledger._require_account(account_id)
        if as_of is not None and self.config.environment != "demo":
            raise QuantError("HISTORICAL_TIME_FORBIDDEN", "前向绑定使用实际系统时钟")
        instant = utc(as_of or now_utc())
        spec = self.strategies.get(strategy_id, revision)
        context = resolve(self.config, spec)
        context.config.require_execution()
        if context.config.max_weight < spec.content()["weight_cap"]:
            raise QuantError("BINDING_RISK_CONFLICT", "策略目标上限超过账户风险上限，请建立兼容的新规格")
        months = [day for day in calendar.month_ends() if
                  instant < (calendar.close(day) + pd.Timedelta(minutes=spec.content()["publication_delay_minutes"])).to_pydatetime()]
        if not months:
            raise QuantError("MISSING_FUTURE_CALENDAR", "日历未覆盖未来合格月末")
        first = str(months[0].date())
        effective = effective_session or first
        if effective not in {str(day.date()) for day in months}:
            raise QuantError("BINDING_DEADLINE_PASSED", "不能追溯绑定或在月中生效；请选择尚未截止的已确认月末")
        with publication_lock(self.ledger.path.parent),self.ledger.transaction():
            if expected_binding_seq is not None and expected_binding_seq != self.sequence(account_id):
                raise QuantError("STALE_BINDING_PREVIEW", "其他操作已更新绑定，请重新查看")
            if expected_account_seq is not None and expected_account_seq != self.ledger.sequence(account_id):
                raise QuantError("STALE_ACCOUNT_PREVIEW", "账户已改变，请重新查看")
            pending = self.ledger.connection.execute("SELECT * FROM strategy_bindings WHERE account_id=? AND status='PENDING'", (account_id,)).fetchone()
            if pending and pending["spec_hash"] == spec.spec_hash and pending["effective_session"] == effective:
                return dict(pending)
            if self.ledger.connection.execute("SELECT 1 FROM plans WHERE account_id=? AND (manual_pending=1 OR execution_status IN ('READY','PARTIAL'))", (account_id,)).fetchone():
                raise QuantError("PENDING_PLAN", "存在未结束计划/人工在途订单，先核对完成情况；不会释放旧预留")
            if pending:
                self.ledger.connection.execute("UPDATE strategy_bindings SET status='SUPERSEDED' WHERE binding_seq=?", (pending["binding_seq"],))
            cursor = self.ledger.connection.execute("INSERT INTO strategy_bindings(account_id,strategy_id,revision,spec_hash,effective_session,requested_at,status,details) VALUES(?,?,?,?,?,?,?,?)",
                (account_id, strategy_id, revision, spec.spec_hash, effective, instant.isoformat(), "PENDING",
                 canonical({"deadline": (calendar.close(effective) + pd.Timedelta(minutes=spec.content()["publication_delay_minutes"])).isoformat(),
                            "account_seq": self.ledger.sequence(account_id)})))
            return dict(self.ledger.connection.execute("SELECT * FROM strategy_bindings WHERE binding_seq=?", (cursor.lastrowid,)).fetchone())

    def selected(self, account_id, session):
        # Selection is based on effective history, including bindings since superseded.
        row = self.ledger.connection.execute("SELECT * FROM strategy_bindings WHERE account_id=? AND effective_session<=? AND status IN ('PENDING','ACTIVE','RETIRED','BLOCKED') ORDER BY effective_session DESC,binding_seq DESC LIMIT 1",
            (account_id, str(pd.Timestamp(session).date()))).fetchone()
        if not row:
            raise QuantError("NO_ACCOUNT_BINDING", "该月尚无生效的账户策略绑定，研究结果不能代替绑定")
        return dict(row)

    def decide(self, account_id, bundle, session, *, as_of=None,option_valuation=None):
        if as_of is not None and self.config.environment != "demo":
            raise QuantError("HISTORICAL_TIME_FORBIDDEN", "前向月度决策使用实际系统时钟")
        instant = as_of or now_utc()
        store = DataStore(Path(self.config.runtime_dir) / "data")
        frame, metadata, calendar = store.load(bundle.signal_snapshot_id)
        day = str(pd.Timestamp(session).date())
        with publication_lock(self.ledger.path.parent),self.ledger.transaction():
            binding = self.selected(account_id, day)
            spec = self.strategies.get(binding["strategy_id"], binding["revision"])
            config = resolve(self.config, spec).config
            cutoff = calendar.close(day) + pd.Timedelta(minutes=config.publication_delay_minutes)
            if utc(instant) < cutoff.to_pydatetime() or utc(binding["requested_at"]) >= cutoff.to_pydatetime():
                raise QuantError("BINDING_DEADLINE_PASSED", "绑定/决策未满足本月截止约定")
            previous = self.ledger.connection.execute("SELECT * FROM monthly_decisions WHERE account_id=? AND decision_session=?", (account_id, day)).fetchone()
            if previous:
                if previous["binding_seq"] != binding["binding_seq"] or previous["spec_hash"] != spec.spec_hash:
                    raise QuantError("FROZEN_MONTHLY_DECISION", "已存在该月冻结决策，禁止切换规格覆盖")
                if previous["outcome"] in {"READY", "NO_ACTION"}:
                    return json.loads(previous["payload"])
            if binding["status"] == "BLOCKED":
                return {"status": "BLOCKED", "code": "BINDING_SWITCH_BLOCKED", "binding_seq": binding["binding_seq"],
                        "reason": "原生效月末切换受阻，请先解决旧占用并明确提交新的生效月份"}
            if binding["status"] == "PENDING":
                if self.ledger.connection.execute("SELECT 1 FROM plans WHERE account_id=? AND (manual_pending=1 OR execution_status IN ('READY','PARTIAL'))", (account_id,)).fetchone():
                    result = {"status": "BLOCKED", "code": "BINDING_SWITCH_BLOCKED", "binding_seq": binding["binding_seq"],
                              "reason": "旧意图/人工在途订单尚未完成；切换未生效，不自动顺延"}
                    self.ledger.connection.execute("UPDATE strategy_bindings SET status='BLOCKED',details=? WHERE binding_seq=?",
                        (canonical(result), binding["binding_seq"]))
                    self.ledger.connection.execute("INSERT INTO monthly_decisions VALUES(?,?,?,?,?,?,?,?)",
                        (account_id, day, binding["binding_seq"], spec.spec_hash, None, "BLOCKED", canonical(result), now_utc()))
                    return result
                self.ledger.connection.execute("UPDATE strategy_bindings SET status='RETIRED' WHERE account_id=? AND status='ACTIVE'", (account_id,))
                self.ledger.connection.execute("UPDATE strategy_bindings SET status='ACTIVE' WHERE binding_seq=?", (binding["binding_seq"],))
            state = self.ledger.snapshot(account_id, instant)
            record = SignalArchive(self.ledger).generate(frame, metadata, calendar, config, day,
                decision_time=instant if config.environment == "demo" else None, account_state=state, bundle=bundle)
            value = decode_signal(record["signal"])
            result = {"status": "BLOCKED", "binding_seq": binding["binding_seq"], "spec_hash": spec.spec_hash,
                      "signal_archive_id": record["archive_id"], "signal": value.content()}
            if value.status == "READY":
                if not any(value.target_weights.values()) and not state["positions"]:
                    result.update(status="NO_ACTION", reason="有效规则全部保留现金，无持仓需要卖出")
                else:
                    try:
                        if not bundle.execution_snapshot_id:
                            raise QuantError("MISSING_EXECUTION_SNAPSHOT", "缺少核验的实际价格快照；研究仍可查看")
                        raw, raw_meta, raw_calendar = store.load(bundle.execution_snapshot_id)
                        if raw_calendar.close(day) != calendar.close(day) or raw_calendar.close(value.eligible_session) != calendar.close(value.eligible_session):
                            raise QuantError("CALENDAR_CONFLICT", "信号/执行日历收盘时点不一致")
                        plan = PlanService(self.ledger, config).create(account_id, value, raw, raw_meta, raw_calendar, instant,option_valuation=option_valuation)
                        result.update(status="BLOCKED" if plan["check_status"] == "BLOCKED" else "NO_ACTION" if plan["payload"]["no_action"] else "READY",
                                      plan_id=plan["plan_id"], checks=plan["payload"]["checks"])
                    except QuantError as exc:
                        result.update(code=exc.code, reason=str(exc))
            self.ledger.connection.execute("INSERT INTO monthly_decisions VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(account_id,decision_session) DO UPDATE SET archive_id=excluded.archive_id,outcome=excluded.outcome,payload=excluded.payload,updated_at=excluded.updated_at",
                (account_id, day, binding["binding_seq"], spec.spec_hash, record["archive_id"], result["status"], canonical(result), now_utc()))
            return result
