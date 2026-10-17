from __future__ import annotations

import pandas as pd
from ..common import QuantError, decimal as D, digest, utc, now_utc
from ..config import Config
from ..portfolio.reconciliation import ReconciliationRules
from ..data.quality import price_quality, require_quality
from .plans import PlanService
from .context import intent_context
from ..locks import publication_lock


def simulate(service: PlanService, plan_id: str, frame, calendar, processing_as_of: str, *, state_as_of=None,option_valuation=None,hedge_stage_check=None):
    """One atomic batch at the planned close, using quantities fixed BEFORE that close."""
    if service.config.environment == "real":
        raise QuantError("REAL_SIMULATION_FORBIDDEN", "模拟器禁止写入真实账户")
    if service.config.environment == "paper" and utc(processing_as_of) > utc(now_utc()):
        raise QuantError("FUTURE_SIMULATION_TIME", "前向模拟不能推进尚未到达的处理时点")
    with publication_lock(service.ledger.path.parent),service.ledger.transaction():
        return _simulate(service, plan_id, frame, calendar, processing_as_of, state_as_of=state_as_of,option_valuation=option_valuation,hedge_stage_check=hedge_stage_check)


def _simulate(service, plan_id, frame, calendar, processing_as_of, *, state_as_of=None,option_valuation=None,hedge_stage_check=None):
    plan = service.get(plan_id)
    body = plan["payload"]
    from ..hedging.stock_simulation_audit import validate_references as validate_stock_simulation
    validate_stock_simulation(service.ledger)
    if plan["execution_status"] == "FILLED":
        return {"status": "NO_ACTION", "plan_id": plan_id}
    if (body.get("purpose")=="hedge_stage" and state_as_of is None
            and utc(processing_as_of)>utc(body["execution_deadline"])+pd.Timedelta(days=1)):
        raise QuantError("HEDGE_REPLAY_STATE_REQUIRED", "迟到股票阶段须显式冻结原成交状态时点，不能套用处理日风险")
    from ..hedging.stage_gate import require_for_plan
    # Stock direction is identified by the unique current group stage.
    from ..hedging.groups import history
    from ..hedging.group_revisions import heads
    matches=[s for g in heads(history(service.ledger,plan['account_id']),processing_as_of,service.ledger.sequence(plan['account_id']))
             for s in g['stages'] if s['plan_kind']=='stock' and s['plan_id']==plan_id and not s.get('historical_slice')]
    action=matches[0]['action'] if len(matches)==1 else 'OPEN'
    stage_check=require_for_plan(service.ledger,plan['account_id'],'stock',plan_id,action,processing_as_of,hedge_stage_check,state_as_of=state_as_of)
    from ..hedging.monitor import require_planning
    require_planning(service.ledger,plan['account_id'],processing_as_of,stage_check=stage_check)
    if plan["execution_status"] not in {"READY", "PARTIAL"} or plan["check_status"] != "PASSED":
        raise QuantError("NON_EXECUTABLE_PLAN", "该计划当前不能模拟执行")
    assumptions = body.get("execution_config")
    if assumptions is None or digest(assumptions) != body.get("execution_config_hash"):
        raise QuantError("MISSING_PLAN_ASSUMPTIONS", "计划缺少完整、经校验的冻结执行假设")
    config = Config.from_dict(assumptions)
    config.validate()
    config.require_execution()
    if config.environment != service.ledger.environment or config.environment == "real":
        raise QuantError("REAL_SIMULATION_FORBIDDEN", "模拟器及冻结计划环境必须一致且不得为 real")
    session = body["execution_session"] if body.get("execution_session") else intent_context(body)["eligible_session"]
    close = calendar.close(session)
    if utc(body["as_of"]) >= close.to_pydatetime():
        raise QuantError("LOOKAHEAD_EXECUTION", "计划必须在假设成交前形成")
    if config.environment == "paper" and utc(body["created_at"]) >= close.to_pydatetime():
        raise QuantError("LOOKAHEAD_EXECUTION", "前向模拟计划不能在过去补建")
    instant = pd.Timestamp(utc(processing_as_of))
    if instant < close:
        return {"status": "WAITING", "message": "尚未到达假设成交时点"}
    state_time = utc(state_as_of or processing_as_of).isoformat()
    if utc(state_time) > utc(processing_as_of) or utc(state_time) < close.to_pydatetime():
        raise QuantError("INVALID_SIMULATION_STATE_TIME", "成交状态时点需介于假设成交时点和实际处理时点之间")
    service.ledger.check_reconciliation(plan["account_id"], state_time,
        config.reconciliation_max_days, reference_time=close.isoformat(),
        rules_hash=ReconciliationRules.from_config(config).hash)
    if state_as_of is not None and utc(state_time) != close.to_pydatetime():
        raise QuantError("INVALID_SIMULATION_STATE_TIME", "日常迟到重放只允许使用已冻结的假设成交时点")
    if state_as_of is not None and any(e["plan_id"] == plan_id and utc(e["effective_at"]) > utc(state_time)
                                     for e in service.ledger.active_events(plan["account_id"], processing_as_of)):
        raise QuantError("CONFLICTING_SIMULATION_FILL_TIME", "已有成交晚于该假设成交时点，不能补算成更早的整批成交")
    rows = frame.loc[(frame.session_date == pd.Timestamp(session)) & (frame.available_at <= instant)]
    if rows.empty:
        return {"status": "WAITING", "message": "成交日行情尚未完整可用"}
    if set(rows.price_basis) != {"unadjusted"} or (rows.split_ratio != 1).any():
        raise QuantError("UNQUALIFIED_EXECUTION_PRICE", "成交价格口径未知或当日拆股需要修订数量")
    prices = dict(zip(rows.symbol, rows.close))
    required = {line["symbol"] for line in body["sizing"]["lines"]}
    if required - set(prices):
        raise QuantError("MISSING_PRICE", "当日价格缺失，整批不模拟成交")
    require_quality(price_quality(frame, calendar, config, required,
                                  session, processing_as_of, require_previous=True))
    from ..options.valuation import planning_marks
    valuation_prices,option_marks=planning_marks(service.ledger,plan['account_id'],prices,state_time,
                                                option_valuation,close.isoformat(),knowledge_cutoff=processing_as_of)
    snapshot = service.ledger.snapshot(plan["account_id"], state_time, valuation_prices)
    if snapshot["equity"] is None or snapshot["anomalies"]:
        raise QuantError("INCOMPLETE_ACCOUNT", "模拟执行账户状态不完整")
    extra = [e for e in service.ledger.active_events(plan["account_id"], state_time)
             if e["seq"] > body.get('execution_basis_sequence',body["snapshot"]["ledger_seq"]) and e["plan_id"] != plan_id]
    if extra:
        raise QuantError("ACCOUNT_CHANGED", "计划形成后存在外部账务变化，需要重新检查剩余计划")
    actual = {s: D(q) for s, q in snapshot["positions"].items()}
    events, debit, fees = [], D(0), D(0)
    existing = service.ledger.active_events(plan["account_id"], state_time)
    for line in body["sizing"]["lines"]:
        symbol, side = line["symbol"], line["side"]
        if symbol not in prices:
            raise QuantError("MISSING_PRICE", "当日价格缺失，整批不模拟成交")
        filled = sum((D(e["quantity"]) for e in existing if e["plan_id"] == plan_id and e["symbol"] == symbol and e["kind"] == side), D(0))
        quantity = max(D(0), D(line["quantity"]) - filled)
        if not quantity:
            continue
        price = D(prices[symbol])
        if abs(price / D(line["price"]) - 1) > D(config.reference_deviation):
            raise QuantError("PRICE_DEVIATION", "执行价格偏离参考价阈值，需修订后再执行，不能事后改写数量")
        fee = quantity * price * (D(config.commission_bps) + D(config.slippage_bps)) / 10000 + D(config.fixed_fee)
        fees += fee
        actual[symbol] = actual.get(symbol, D(0)) + quantity * (1 if side == "BUY" else -1)
        if side == "BUY":
            debit += quantity * price + fee
        elif actual[symbol] < 0:
            raise QuantError("INSUFFICIENT_POSITION", "卖出超过现有份额")
        settlement = calendar.close(calendar.next(session, config.settlement_lag_sessions)).isoformat()
        events.append({"event_id": digest({"plan": plan_id, "symbol": symbol, "side": side, "filled_before": str(filled)}),
                       "kind": side, "effective_at": close.isoformat(), "settlement_at": settlement,
                       "symbol": symbol, "quantity": str(quantity), "price": str(price), "fee": str(fee),
                       "plan_id": plan_id, "source": "lyra_close_simulation_v1",
                       "evidence_type": "simulated", "environment": config.environment})
    if not events:
        service.refresh(plan_id, state_time)
        return {"status": "NO_ACTION", "plan_id": plan_id}
    available = max(D(0), D(snapshot["available_cash"]) + D(plan["reserved_cash"]) - D(snapshot["equity"]) * D(config.cash_buffer))
    if debit > available:
        raise QuantError("INSUFFICIENT_CASH", "执行日价格及费用超过可用资金，整批不模拟成交")
    equity = D(snapshot["equity"]) - fees
    if equity <= 0 or any(q * D(prices[s]) / equity > D(config.max_weight) + D("1e-10") for s, q in actual.items()):
        raise QuantError("PROJECTED_WEIGHT_LIMIT", "执行日价格造成预计仓位超限")
    from ..hedging.monitor import require_projected_coverage
    projection=require_projected_coverage(service.ledger,plan['account_id'],state_time,actual,stage_check=stage_check)
    imported = service.ledger.import_events(plan["account_id"], events, expected_sequence=snapshot["ledger_seq"])
    updated = service.refresh(plan_id, state_time)
    if stage_check.get("status")=="CHECKED":
        from ..hedging.stock_simulation_audit import save as save_stock_simulation
        save_stock_simulation(service.ledger,plan["account_id"],plan_id,events,snapshot["ledger_seq"],
                              service.ledger.sequence(plan["account_id"]),stage_check,processing_as_of,state_time,action=action)
    return {"status": "SUCCESS", "plan_id": plan_id, "import": imported,'hedge_projection':projection,
            'option_valuation':option_marks,'hedge_stage_check':stage_check,
            "execution_session": session, "processing_as_of": processing_as_of,
            "state_as_of": state_time,
            "late_processing": instant > close + pd.Timedelta(days=1), "execution_status": updated["execution_status"]}
