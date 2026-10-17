from __future__ import annotations

import json
from decimal import ROUND_FLOOR, ROUND_CEILING
from pathlib import Path
import pandas as pd

from ..common import QuantError, canonical, decimal as D, digest, now_utc, utc
from ..locks import publication_lock
from ..config import Config
from ..data.calendar import Calendar
from ..data.quality import price_quality, require_quality
from ..portfolio.ledger import Ledger
from ..portfolio.reconciliation import ReconciliationRules
from ..portfolio.plan_state import refresh_plan
from ..strategies import Signal, decode_signal
from ..strategies.archive import SignalArchive


def size_orders(snapshot: dict, weights: dict, prices: dict, config: Config) -> dict:
    config.require_execution()
    if any(D(w) < 0 or D(w) > D(config.max_weight) for w in weights.values()) or sum(map(D, weights.values()), D(0)) > D(1) + D("1e-10"):
        raise QuantError("WEIGHT_LIMIT", "目标权重非法或超过单标的上限")
    positions = {s: D(q) for s, q in snapshot["positions"].items()}
    required = set(positions) | set(weights)
    if snapshot.get('pending_option_exits'):
        raise QuantError('PENDING_OPTION_EXIT', '存在未完成期权退出意图，暂停新调仓计划')
    if not required <= prices.keys() or snapshot["equity"] is None or snapshot["anomalies"]:
        raise QuantError("INCOMPLETE_ACCOUNT", "账户价格或记录不完整，不能计算数量")
    prices = {s: D(p) for s, p in prices.items()}
    equity = D(snapshot["equity"])
    if equity <= 0:
        raise QuantError("NO_CAPITAL", "真实空账户或没有可投资权益")
    lot, rate, fixed = D(config.lot_size), D(config.commission_bps + config.slippage_bps) / D(10000), D(config.fixed_fee)
    costs = lambda q, p: q * p * rate + (fixed if q > 0 else D(0))
    lines, buys = [], {}
    for symbol in sorted(required):
        price = prices[symbol]
        if price <= 0:
            raise QuantError("INVALID_PRICE", "参考价格必须为正")
        target = ((D(weights.get(symbol, 0)) * equity / price / lot).to_integral_value(rounding=ROUND_FLOOR)) * lot
        actual = positions.get(symbol, D(0))
        if actual < 0:
            raise QuantError("SHORT_POSITION", "实际持仓为负，需解决对账异常")
        difference = target - actual
        if difference < 0:
            quantity = ((-difference / lot).to_integral_value(rounding=ROUND_FLOOR)) * lot
            if quantity > actual - D(snapshot.get("reserved_positions", {}).get(symbol, 0)):
                raise QuantError("INSUFFICIENT_POSITION", "卖出份额已被其他在途计划占用")
            if quantity:
                lines.append({"symbol": symbol, "side": "SELL", "quantity": str(quantity), "price": str(price), "estimated_fee": str(costs(quantity, price))})
        elif difference > 0:
            buys[symbol] = difference
    budget = max(D(0), D(snapshot["available_cash"]) - equity * D(config.cash_buffer))
    desired = sum((q * prices[s] for s, q in buys.items()), D(0))
    fees = sum((costs(q, prices[s]) for s, q in buys.items()), D(0))
    scale = min(D(1), max(D(0), budget - fees) / desired) if desired else D(0)
    quantities = {s: (q * scale / lot).to_integral_value(rounding=ROUND_FLOOR) * lot for s, q in buys.items()}
    sold = {line["symbol"]: D(line["quantity"]) for line in lines}
    # Reductions are the same deterministic lot steps as the policy, computed in
    # batches to avoid billions of iterations for fractional trade units.
    while any(quantities.values()):
        fees_now = sum((D(line["estimated_fee"]) for line in lines), D(0)) + sum((costs(q, prices[s]) for s, q in quantities.items()), D(0))
        final_value = equity - fees_now
        projected_now = {s: positions.get(s, D(0)) - sold.get(s, D(0)) + quantities.get(s, D(0)) for s in required}
        over = sorted(s for s, q in projected_now.items() if q * prices[s] > D(config.max_weight) * final_value + D("1e-10"))
        if final_value > 0 and not over:
            break
        direct = [s for s in over if quantities.get(s, D(0)) > 0]
        if direct:
            symbol = direct[0]
            excess = projected_now[symbol] * prices[symbol] - D(config.max_weight) * final_value
            denominator = prices[symbol] * (1 - D(config.max_weight) * rate) * lot
            steps = (excess / denominator).to_integral_value(rounding=ROUND_CEILING) if denominator > 0 else quantities[symbol] / lot
        else:
            symbol = min((s for s, q in quantities.items() if q > 0), key=lambda s: ((buys[s] - quantities[s]) * prices[s], s))
            reduction_needed = max((projected_now[s] * prices[s] / D(config.max_weight) - final_value for s in over), default=-final_value)
            steps = (reduction_needed / (prices[symbol] * rate * lot)).to_integral_value(rounding=ROUND_CEILING) if rate > 0 else quantities[symbol] / lot
        quantities[symbol] = max(D(0), quantities[symbol] - max(D(1), steps) * lot)
    for symbol in sorted(quantities):
        quantity = quantities[symbol]
        if quantity:
            lines.append({"symbol": symbol, "side": "BUY", "quantity": str(quantity), "price": str(prices[symbol]), "estimated_fee": str(costs(quantity, prices[symbol]))})
    total_fees = sum((D(line["estimated_fee"]) for line in lines), D(0))
    final_equity = equity - total_fees
    projected = positions.copy()
    for line in lines:
        projected[line["symbol"]] = projected.get(line["symbol"], D(0)) + D(line["quantity"]) * (1 if line["side"] == "BUY" else -1)
    if final_equity <= 0 or any(q * prices[s] / final_equity > D(config.max_weight) + D("1e-10") for s, q in projected.items()):
        raise QuantError("PROJECTED_WEIGHT_LIMIT", "预计执行后仍超仓位上限，需减量或补齐退出条件")
    reserve = sum((D(l["quantity"]) * D(l["price"]) + D(l["estimated_fee"]) for l in lines if l["side"] == "BUY"), D(0))
    if reserve > budget:
        raise QuantError("INSUFFICIENT_CASH", "合计买入及费用超过统一现金预算")
    return {"lines": lines, "reserve": str(reserve), "projected_positions": {s: str(q) for s, q in projected.items()},
            "projected_weights": {s: str(q * prices[s] / final_equity) for s, q in projected.items()},
            "estimated_fee": str(total_fees), "cash_buffer": str(equity * D(config.cash_buffer)),
            "unallocated_buy_targets": {s: str(q - quantities.get(s, 0)) for s, q in buys.items() if q > quantities.get(s, 0)}}


class PlanService:
    def __init__(self, ledger: Ledger, config: Config):
        self.ledger, self.config = ledger, config

    def get(self, plan_id):
        row = self.ledger.connection.execute("SELECT * FROM plans WHERE plan_id=?", (plan_id,)).fetchone()
        if not row:
            raise QuantError("UNKNOWN_PLAN", "计划不存在")
        result = dict(row)
        result["payload"] = json.loads(result["payload"])
        if result["payload"].get("purpose") == "hedge_stage":
            from ..hedging.stock_plans import validate_references
            validate_references(self.ledger)
            from ..hedging.stock_activation import validate_references as validate_stock_activation
            validate_stock_activation(self.ledger)
        result["reserved_positions"] = json.loads(result["reserved_positions"])
        return result

    def create(self, account_id: str, signal: Signal, frame: pd.DataFrame, metadata: dict,
               calendar: Calendar, as_of: str, *, revise=False,option_valuation=None):
        with publication_lock(self.ledger.path.parent),self.ledger.transaction():
            return self._create(account_id,signal,frame,metadata,calendar,as_of,revise=revise,option_valuation=option_valuation)

    def _create(self, account_id, signal, frame, metadata, calendar, as_of, *, revise=False,option_valuation=None):
        self.config.require_execution()
        if self.ledger.environment != self.config.environment:
            raise QuantError("ENVIRONMENT_MISMATCH", "配置和账户环境不匹配")
        instant = utc(as_of)
        archived_signal = None
        if self.config.environment in {"paper", "real"}:
            if self.ledger.connection.execute('SELECT version FROM schema_version').fetchone()[0]>=5:
                from ..data.qualification import require_qualification
                from ..data.store import DataStore
                require_qualification(self.ledger.connection,self.ledger.path.parent,metadata,DataStore.series_identity(metadata),as_of)
            if metadata["data_type"] != "real_market" or signal.research_mode != "forward" or metadata["calendar_kind"] != "verified_market_sessions":
                raise QuantError("ENVIRONMENT_MISMATCH", "真实账户不能使用合成数据或历史重建信号")
            observed_by = instant if revise or self.ledger.connection.execute("SELECT version FROM schema_version").fetchone()[0]>=4 else utc(signal.decision_time)
            if utc(metadata["acquired_at"]) > observed_by:
                raise QuantError("DATA_NOT_OBSERVED", "信号决策前尚未取得该行情快照")
            archived_signal = SignalArchive(self.ledger).require(signal)
        else:
            try:
                archived_signal = SignalArchive(self.ledger).require(signal)
            except QuantError as exc:
                if exc.code != "UNARCHIVED_SIGNAL":
                    raise
        signal = decode_signal(signal.content())
        versioned = getattr(signal, "schema_version", 1) == 2
        if versioned:
            from ..strategies.spec import StrategySpec
            if not self.config.strategy_spec or signal.spec_hash != StrategySpec.from_dict(self.config.strategy_spec).spec_hash:
                raise QuantError("STRATEGY_CONFIG_CONFLICT", "计划必须使用该信号的完整冻结规格")
        if not versioned and self.ledger.connection.execute('SELECT version FROM schema_version').fetchone()[0]>=4:
            from ..data.store import DataStore
            store=DataStore(self.ledger.path.parent/'data')
            _,signal_metadata,signal_calendar=store.load(signal.snapshot_id)
            _,chosen_signal,_=store.load_role('signal')
            _,chosen_execution,_=store.load_role('execution')
            if store.series_identity(signal_metadata)!=store.series_identity(chosen_signal) or chosen_execution['snapshot_id']!=metadata['snapshot_id']:
                raise QuantError('INVALID_SIGNAL','信号/执行来源与明确用途不符')
            overlap=signal_calendar.sessions.intersection(calendar.sessions)
            if signal_calendar.kind!=calendar.kind or not signal_calendar.schedule.loc[overlap,'close_time'].equals(calendar.schedule.loc[overlap,'close_time']):
                raise QuantError('CALENDAR_CONFLICT','信号和执行交易时点不一致')
            expected_snapshot=metadata['snapshot_id']
        else:
            expected_snapshot = signal.data_bundle["execution_snapshot_id"] if versioned else signal.snapshot_id
        if signal.status != "READY" or signal.strategy != self.config.active_strategy or (not revise and expected_snapshot != metadata["snapshot_id"]):
            raise QuantError("INVALID_SIGNAL", "策略配置不一致或数据不足")
        intent = digest({"account": account_id, "environment": self.config.environment,
                         "decision_session": signal.decision_session})
        with self.ledger.transaction():
            binding_seq = None
            if versioned and not revise:
                from ..strategies.bindings import BindingService
                binding = BindingService(self.ledger, self.config).selected(account_id, signal.decision_session)
                if binding["status"] != "ACTIVE" or binding["spec_hash"] != signal.spec_hash:
                    raise QuantError("ACCOUNT_BINDING_CONFLICT", "计划规则与该月账户生效绑定不一致；通过月度决策入口生成")
                binding_seq = binding["binding_seq"]
            for pending in self.ledger.connection.execute("SELECT plan_id,payload FROM plans WHERE account_id=? AND execution_status IN ('READY','PARTIAL')", (account_id,)).fetchall():
                body = json.loads(pending["payload"])
                if utc(body["as_of"]) <= instant:
                    refresh_plan(self.ledger, pending["plan_id"], as_of)
            existing = self.ledger.connection.execute("SELECT plan_id FROM plans WHERE account_id=? AND json_extract(payload,'$.signal.decision_session')=? ORDER BY rowid DESC LIMIT 1",
                                                      (account_id, signal.decision_session)).fetchone()
            if existing and not revise:
                return self.get(existing[0])
            from ..hedging.monitor import require_planning
            require_planning(self.ledger,account_id,as_of)
            if existing:
                old = self.get(existing[0])
                intent = old["intent_id"]
                if signal.signal_id != old["payload"]["signal"]["signal_id"]:
                    raise QuantError("FROZEN_SIGNAL_REQUIRED", "修订须继续原有冻结月末信号，不能重新选择规则或目标")
                original_config = old["payload"].get("execution_config")
                rule_fields = ("lookback", "active_strategy", "market", "currency")
                if not original_config or any(original_config[k] != getattr(self.config, k) for k in rule_fields) or any(
                    tuple(original_config[k]) != tuple(getattr(self.config, k)) for k in ("symbols", "weights")):
                    raise QuantError("STRATEGY_CHANGE_PENDING", "月中规则/标的/权重不能改变，执行参数变更须单独修订")
                if old["payload"].get("revision_input_key") == self._revision_key(account_id, signal, metadata, calendar, as_of,option_valuation):
                    return old
                if old["manual_pending"]:
                    raise QuantError("PENDING_MANUAL_ORDER", "有未确认人工订单，不能替代并释放其预留")
                if old["execution_status"] in {"CANCELLED", "EXPIRED"} or old["execution_status"] == "FILLED" and old["payload"].get("intent_status") != "WAITING_SETTLEMENT":
                    raise QuantError("CLOSED_INTENT", "月度意图已结束，不因权重漂移重开")
                self.ledger.connection.execute("UPDATE plans SET execution_status=CASE WHEN execution_status='FILLED' THEN 'FILLED' ELSE 'SUPERSEDED' END,reserved_cash='0',reserved_positions='{}' WHERE plan_id=?", (existing[0],))
            else:
                old = None
                if revise or signal.config_hash != self.config.hash:
                    raise QuantError("INVALID_SIGNAL", "首次计划需要一致配置，修订需要已有月度意图")
            revision = old["revision"] + 1 if old else 1
            plan_id = digest({"intent": intent, "revision": revision})
            snapshot, sizing, checks, reconciliation, quality = None, None, [], None, None
            reference = None
            option_marks=None
            try:
                first_executable_plan = not old or not old["payload"].get("intent_limits")
                if instant < utc(signal.decision_time) or instant >= calendar.close(signal.eligible_session).to_pydatetime() and first_executable_plan:
                    raise QuantError("EXPIRED_SIGNAL", "首次计划必须在适用交易日成交前形成")
                if instant > calendar.close(signal.valid_through_session).to_pydatetime():
                    raise QuantError("EXPIRED_SIGNAL", "目标意图有效窗口结束")
                reference = calendar.latest_completed(as_of, self.config.publication_delay_minutes)
                if reference > pd.Timestamp(signal.valid_through_session):
                    raise QuantError("EXPIRED_SIGNAL", "执行窗口已结束")
                available = frame.loc[(frame.session_date == reference) & (frame.available_at <= pd.Timestamp(instant))]
                if set(available.price_basis) != {"unadjusted"}:
                    raise QuantError("UNQUALIFIED_EXECUTION_PRICE", "未确认的拆股调整 Close 只能研究，不能算真实份额")
                prices = dict(zip(available.symbol, available.close))
                from ..options.valuation import planning_marks
                valuation_prices,option_marks=planning_marks(self.ledger,account_id,prices,as_of,option_valuation,
                                                            calendar.close(reference).isoformat())
                snapshot = self.ledger.snapshot(account_id, as_of, valuation_prices)
                if not set(self.config.symbols) | set(snapshot["positions"]) <= set(prices):
                    raise QuantError("MISSING_PRICE", "当前或目标持仓缺少已发布的完整参考价")
                quality = price_quality(frame, calendar, self.config,
                    set(self.config.symbols) | set(snapshot["positions"]), reference, as_of, require_previous=True)
                require_quality(quality)
                other = self.ledger.connection.execute("SELECT plan_id FROM plans WHERE account_id=? AND (execution_status IN ('READY','PARTIAL') OR manual_pending=1)", (account_id,)).fetchone()
                if other:
                    raise QuantError("PENDING_PLAN", "账户已有未结束计划，需先导入成交或处理剩余交易")
                reconciliation = self.ledger.check_reconciliation(account_id, as_of, self.config.reconciliation_max_days,
                                                                 reference_time=calendar.close(reference).isoformat(),
                                                                 rules_hash=ReconciliationRules.from_config(self.config).hash)
                sizing = size_orders(snapshot, signal.target_weights, prices, self.config)
                if old and old["payload"].get("intent_limits"):
                    sizing = self._limit_revision(old, sizing, snapshot, prices, as_of)
                from ..hedging.monitor import require_projected_coverage
                sizing['hedge_projection']=require_projected_coverage(self.ledger,account_id,as_of,sizing['projected_positions'])
                checks.append({"code": "PASSED", "message": "权重、数据、费用、资金、对账及未完成计划检查通过"})
            except QuantError as exc:
                checks.append({"code": exc.code, "message": str(exc)})
            passed = bool(sizing is not None and checks[-1]["code"] == "PASSED")
            execution = "READY" if passed and sizing["lines"] else "FILLED" if passed else "DRAFT"
            payload = {"plan_id": plan_id, "intent_id": intent, "revision": revision,
                       "environment": self.config.environment, "created_at": now_utc(), "as_of": instant.isoformat(),
                       "execution_config": self.config.content(), "execution_config_hash": self.config.hash,
                       "signal": signal.content(), "reference_session": str(reference.date()) if reference is not None else None,
                       "signal_archive_id": archived_signal["archive_id"] if archived_signal else None,
                       "reference_snapshot_id": metadata["snapshot_id"], "reconciliation": reconciliation if sizing is not None else None,
                       "data_quality": quality,
                       "revision_input_key": self._revision_key(account_id, signal, metadata, calendar, as_of,option_valuation),
                       "option_valuation_request":option_valuation,"option_valuation":option_marks,
                       "snapshot": snapshot, "sizing": sizing, "checks": checks,
                       "no_action": passed and not sizing["lines"]}
            if versioned:
                payload["binding_seq"] = old["payload"]["binding_seq"] if old else binding_seq
            if old and old["payload"].get("intent_limits"):
                payload["intent_limits"] = old["payload"]["intent_limits"]
                payload["intent_reference_time"] = old["payload"].get("intent_reference_time", old["payload"]["as_of"])
            if reference is not None:
                payload["execution_session"] = str(calendar.next(reference).date())
                payload["execution_deadline"] = calendar.close(payload["execution_session"]).isoformat()
                if payload["execution_session"] > signal.valid_through_session:
                    payload["checks"] = [{"code": "EXPIRED_SIGNAL", "message": "新的适用成交日已超出目标意图窗口"}]
                    passed, execution = False, "DRAFT"
            reserve = sizing["reserve"] if passed else "0"
            reserved_positions = {l["symbol"]: l["quantity"] for l in sizing["lines"] if l["side"] == "SELL"} if passed else {}
            if passed:
                payload["intent_limits"] = old["payload"]["intent_limits"] if old and old["payload"].get("intent_limits") else {
                    line["symbol"]: {"side": line["side"], "quantity": str(D(line["quantity"]) + D(sizing["unallocated_buy_targets"].get(line["symbol"], 0)) if line["side"] == "BUY" else D(line["quantity"]))}
                    for line in sizing["lines"]}
                for symbol, quantity in sizing["unallocated_buy_targets"].items():
                    payload["intent_limits"].setdefault(symbol, {"side": "BUY", "quantity": quantity})
                payload["intent_reference_time"] = old["payload"].get("intent_reference_time", old["payload"]["as_of"]) if old else instant.isoformat()
                payload["deferred_buy_targets"] = {s: q for s, q in sizing["unallocated_buy_targets"].items() if D(q) >= D(self.config.lot_size)} if any(v["side"] == "SELL" for v in payload["intent_limits"].values()) else {}
            payload["intent_status"] = "OPEN" if execution == "READY" else "WAITING_SETTLEMENT" if passed and payload.get("deferred_buy_targets") else "COMPLETE" if execution == "FILLED" else "BLOCKED"
            self.ledger.connection.execute("INSERT INTO plans VALUES(?,?,?,?,?,?,?,?,?,?)",
                                          (plan_id, intent, revision, account_id, execution, "PASSED" if passed else "BLOCKED",
                                           canonical(payload), reserve, canonical(reserved_positions), 0))
            return self.get(plan_id)

    def revise(self, plan_id, frame, metadata, calendar, as_of,*,option_valuation=None):
        old = self.get(plan_id)
        if old["payload"].get("purpose") == "hedge_stage":
            raise QuantError("EXPLICIT_HEDGE_REVISION_REQUIRED", "对冲数量须显式修订父/执行组，不能用月度权重重新生成")
        value = decode_signal(old["payload"]["signal"])
        service = self
        if getattr(value, "schema_version", 1) == 2:
            service = PlanService(self.ledger, Config.from_dict(old["payload"]["execution_config"]))
        return service.create(old["account_id"], value, frame, metadata, calendar, as_of, revise=True,option_valuation=option_valuation)

    def _revision_key(self, account_id, signal, metadata, calendar, as_of,option_valuation=None):
        try:
            reference = str(calendar.latest_completed(as_of, self.config.publication_delay_minutes).date())
        except QuantError:
            reference = as_of
        reconciliation = self.ledger.connection.execute("SELECT max(id) FROM reconciliations WHERE account_id=?", (account_id,)).fetchone()[0]
        basis={"account": account_id, "ledger_seq": self.ledger.sequence(account_id), "signal": signal.signal_id,
                       "data": metadata["snapshot_id"], "config": self.config.hash, "reference": reference,
                       "reconciliation": reconciliation}
        if option_valuation is not None or self.ledger.snapshot(account_id,as_of).get('option_positions'):
            basis.update(option_valuation=option_valuation,option_as_of=utc(as_of).isoformat())
        return digest(basis)

    def _limit_revision(self, old, sizing, snapshot, prices, as_of):
        limits = old["payload"].get("intent_limits")
        if not limits:
            raise QuantError("MISSING_PLAN_ASSUMPTIONS", "旧计划缺少冻结意图数量，需要核对后等待下月")
        ids = {row[0] for row in self.ledger.connection.execute("SELECT plan_id FROM plans WHERE intent_id=?", (old["intent_id"],))}
        events = self.ledger.active_events(old["account_id"], as_of)
        reference = utc(old["payload"].get("intent_reference_time", old["payload"]["as_of"]))
        ratios = lambda symbol, after: self._split_factor(events, symbol, after)
        remaining = {}
        for symbol, limit in limits.items():
            completed = sum((D(e["quantity"]) * ratios(symbol, utc(e["effective_at"])) for e in events
                             if e["plan_id"] in ids and e["kind"] == limit["side"] and e["symbol"] == symbol), D(0))
            remaining[symbol] = max(D(0), D(limit["quantity"]) * ratios(symbol, reference) - completed)
        revised = []
        for line in sizing["lines"]:
            symbol = line["symbol"]
            if symbol not in limits or line["side"] != limits[symbol]["side"]:
                raise QuantError("DIRECTION_REVERSAL", "旧意图不开放新交易方向，等待下一月末")
            quantity = min(D(line["quantity"]), remaining[symbol])
            quantity = (quantity / D(self.config.lot_size)).to_integral_value(rounding=ROUND_FLOOR) * D(self.config.lot_size)
            if quantity:
                fee = quantity * D(line["price"]) * (D(self.config.commission_bps) + D(self.config.slippage_bps)) / 10000 + D(self.config.fixed_fee)
                revised.append({**line, "quantity": str(quantity), "estimated_fee": str(fee)})
        total_fee = sum((D(line["estimated_fee"]) for line in revised), D(0))
        projected = {s: D(q) for s, q in snapshot["positions"].items()}
        for line in revised:
            projected[line["symbol"]] = projected.get(line["symbol"], D(0)) + D(line["quantity"]) * (1 if line["side"] == "BUY" else -1)
        equity = D(snapshot["equity"]) - total_fee
        if equity <= 0 or any(q * D(prices[s]) / equity > D(self.config.max_weight) + D("1e-10") for s, q in projected.items()):
            raise QuantError("PROJECTED_WEIGHT_LIMIT", "限制旧意图数量后预计持仓仍超限")
        unallocated = {s: q - sum((D(l["quantity"]) for l in revised if l["symbol"] == s and l["side"] == "BUY"), D(0)) for s, q in remaining.items() if limits[s]["side"] == "BUY"}
        return {**sizing, "lines": revised, "reserve": str(sum((D(l["quantity"]) * D(l["price"]) + D(l["estimated_fee"]) for l in revised if l["side"] == "BUY"), D(0))),
                "estimated_fee": str(total_fee), "projected_positions": {s: str(q) for s, q in projected.items()},
                "projected_weights": {s: str(q * D(prices[s]) / equity) for s, q in projected.items()},
                "unallocated_buy_targets": {s: str(q) for s, q in unallocated.items() if q >= D(self.config.lot_size)}}

    @staticmethod
    def _split_factor(events, symbol, after):
        ratio = D(1)
        for event in events:
            if event["kind"] == "SPLIT" and event["symbol"] == symbol and utc(event["effective_at"]) > after:
                ratio *= D(event["ratio"])
        return ratio

    def manual_pending(self, plan_id, pending: bool, as_of=None):
        with self.ledger.transaction():
            plan = self.get(plan_id)
            clock = as_of or (now_utc() if self.config.environment != "demo" else plan["payload"].get("last_checked_as_of", plan["payload"]["as_of"]))
            # This records an already submitted manual order, not permission to submit.
            # Late notification must retain its commitments, even for an expired plan.
            self.ledger.connection.execute("UPDATE plans SET manual_pending=? WHERE plan_id=?", (int(pending), plan_id))
            refresh_plan(self.ledger, plan_id, clock)

    def cancel(self, plan_id):
        with self.ledger.transaction():
            plan = self.get(plan_id)
            if plan["manual_pending"]:
                raise QuantError("PENDING_MANUAL_ORDER", "先确认人工订单结束，不以本地取消冒充券商撤单")
            if plan["execution_status"] == "FILLED":
                raise QuantError("FILLED_PLAN", "已完成计划不能撤销真实成交")
            self.ledger.connection.execute("UPDATE plans SET execution_status='CANCELLED',reserved_cash='0',reserved_positions='{}' WHERE plan_id=?", (plan_id,))

    def refresh(self, plan_id, as_of):
        with self.ledger.transaction():
            self.get(plan_id)
            refresh_plan(self.ledger, plan_id, as_of)
            return self.get(plan_id)
