"""Plan projections updated inside the same SQLite transaction as account facts."""
from __future__ import annotations

import json

from ..common import canonical, decimal as D, utc
from ..execution.context import intent_context


def block_account_plans(ledger, account_id: str, reconciliation_id: int) -> None:
    """Invalidate checks without changing fills, intent progress or commitments."""
    rows = ledger.connection.execute(
        "SELECT plan_id,payload FROM plans WHERE account_id=? "
        "AND (execution_status IN ('READY','PARTIAL') OR manual_pending=1)", (account_id,)).fetchall()
    for row in rows:
        body = json.loads(row["payload"])
        body["checks"] = [{"code": "UNRESOLVED_RECONCILIATION",
                           "message": "新对账存在差异，暂停剩余交易；核对后重新检查计划",
                           "reconciliation_id": reconciliation_id}]
        ledger.connection.execute("UPDATE plans SET check_status='BLOCKED',payload=? WHERE plan_id=?",
                                  (canonical(body), row["plan_id"]))


def refresh_plan(ledger, plan_id: str, as_of: str) -> None:
    row = ledger.connection.execute("SELECT * FROM plans WHERE plan_id=?", (plan_id,)).fetchone()
    if row is None:
        return
    plan = dict(row)
    body = json.loads(plan["payload"])
    items = (body.get("sizing") or {}).get("lines", [])
    events = ledger.active_events(plan["account_id"], as_of)
    expected = {(line["symbol"], line["side"]) for line in items}
    anomalies = []
    for event in events:
        if event["plan_id"] == plan_id and event["kind"] in {"BUY", "SELL"} and (event["symbol"], event["kind"]) not in expected:
            anomalies.append("非建议方向或标的成交：" + event["event_id"])
    remaining = []
    any_fill = False
    def split_factor(symbol, after):
        result = D(1)
        for event in events:
            if event["kind"] == "SPLIT" and event["symbol"] == symbol and utc(event["effective_at"]) > after:
                result *= D(event["ratio"])
        return result
    for line in items:
        ratio = split_factor(line["symbol"], utc(body["as_of"]))
        expected_quantity = D(line["quantity"]) * ratio
        filled = sum((D(e["quantity"]) * split_factor(e["symbol"], utc(e["effective_at"])) for e in events if e["plan_id"] == plan_id
                      and e["kind"] == line["side"] and e["symbol"] == line["symbol"]), D(0))
        any_fill |= filled > 0
        if filled > expected_quantity:
            anomalies.append("超计划成交：" + line["symbol"])
        quantity = max(D(0), expected_quantity - filled)
        if quantity:
            remaining.append({**line, "quantity": str(expected_quantity), "price": str(D(line["price"]) / ratio),
                              "unit_split_factor": str(ratio), "filled_quantity": str(filled), "remaining_quantity": str(quantity)})
    body["remaining"], body["actual_anomalies"] = remaining, anomalies
    body["last_checked_as_of"] = utc(as_of).isoformat()
    state, check = plan["execution_status"], plan["check_status"]
    basis_seq = body.get('execution_basis_sequence',(body.get("snapshot") or {}).get("ledger_seq", 0))
    changed = [e for e in events if e["seq"] > basis_seq and e["plan_id"] != plan_id]
    cashflow = any(e["kind"] in {"DEPOSIT", "WITHDRAWAL"} for e in changed)
    active = state in {"READY", "PARTIAL"}
    # Completion is a fact. A later unrelated deposit cannot undo completed fills.
    if active and not remaining:
        state = "FILLED"
    elif active:
        if any_fill:
            state = "PARTIAL"
        if cashflow:
            state, check = "CANCELLED", "BLOCKED"
            body["checks"] = [{"code": "NEW_EXTERNAL_CASHFLOW", "message": "外部资金变化，关闭未提交部分并等待下一月末"}]
        elif changed:
            check = "BLOCKED"
            body["checks"] = [{"code": "ACCOUNT_RECHECK_REQUIRED", "message": "出现计划外或公司行动事件，剩余计划需要重新检查"}]
        if str(utc(as_of).date()) > intent_context(body)["valid_through_session"]:
            state = "EXPIRED"
            check = "BLOCKED"
            body["checks"] = [{"code": "EXPIRED_SIGNAL", "message": "目标意图有效窗口已结束"}]
    if anomalies or (plan["execution_status"] == "FILLED" and remaining):
        check = "BLOCKED"
        body["checks"] = [{"code": "ACTUAL_FILL_DIFFERENCE", "message": "实际成交与建议不一致，保留事实并重新核对"}]
    if state in {"CANCELLED", "EXPIRED", "SUPERSEDED"} or cashflow and body.get("deferred_buy_targets"):
        body["intent_status"] = "CLOSED"
    elif state == "FILLED":
        body["intent_status"] = "WAITING_SETTLEMENT" if body.get("deferred_buy_targets") else "COMPLETE"
        if body["intent_status"] == "WAITING_SETTLEMENT" and str(utc(as_of).date()) > intent_context(body)["valid_through_session"]:
            body["intent_status"] = "CLOSED"
    elif state in {"READY", "PARTIAL"}:
        body["intent_status"] = "OPEN"
        if body.get("execution_deadline") and utc(as_of) > utc(body["execution_deadline"]):
            check = "BLOCKED"
            body["checks"] = [{"code": "DAY_PLAN_EXPIRED", "message": "日计划成交时点已过去，保留执行事实；重新检查并修订未完成部分"}]

    reserve, positions = D(0), {}
    assumptions = body.get("execution_config")
    if state in {"READY", "PARTIAL"} or plan["manual_pending"]:
        if assumptions is None:
            # Legacy plans lack frozen fees. Preserve their commitments conservatively.
            reserve = D(plan["reserved_cash"])
            positions = json.loads(plan["reserved_positions"])
            check = "BLOCKED"
            body["checks"] = [{"code": "MISSING_PLAN_ASSUMPTIONS", "message": "旧计划缺少冻结执行假设，请核对在途状态后重新规划"}]
        else:
            rate = (D(assumptions["commission_bps"]) + D(assumptions["slippage_bps"])) / 10000
            for line in remaining:
                quantity = D(line["remaining_quantity"])
                if line["side"] == "BUY":
                    reserve += quantity * D(line["price"]) * (1 + rate) + D(assumptions["fixed_fee"])
                else:
                    positions[line["symbol"]] = str(quantity)
    ledger.connection.execute(
        "UPDATE plans SET execution_status=?,check_status=?,payload=?,reserved_cash=?,reserved_positions=? WHERE plan_id=?",
        (state, check, canonical(body), str(reserve), canonical(positions), plan_id),
    )


def refresh_account_plans(ledger, account_id: str, as_of: str) -> None:
    for row in ledger.connection.execute("SELECT plan_id,payload FROM plans WHERE account_id=?", (account_id,)).fetchall():
        body = json.loads(row["payload"])
        # Late historical facts cannot move a projection backwards before its creation.
        cutoff = max(utc(as_of), utc(body["as_of"])).isoformat()
        refresh_plan(ledger, row["plan_id"], cutoff)
