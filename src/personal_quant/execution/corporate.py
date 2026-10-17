"""Simple, explicit corporate action assumptions for isolated simulated accounts."""
from __future__ import annotations

from datetime import timedelta

from ..common import QuantError, decimal as D, digest, now_utc, utc
from ..portfolio.imports import _rows


def action_csv(value: bytes | str) -> list[dict]:
    return normalize_actions(_rows(value))


def normalize_actions(rows) -> list[dict]:
    normalized, identities = [], set()
    required = {"action_id", "kind", "symbol", "source", "data_type", "effective_at", "available_at"}
    allowed = required | {"qualification_at", "payment_at", "amount_per_share", "withholding_per_share", "ratio"}
    for raw in rows:
        if not required <= raw.keys() or set(raw) - allowed:
            raise QuantError("INVALID_ACTION", "公司行动缺字段或有未知字段，请使用标准模板")
        action = dict(raw)
        action["kind"] = str(action["kind"]).upper()
        if not all(action[k] for k in ("action_id", "symbol", "source")) or action["kind"] not in {"CASH_DIVIDEND", "SPLIT"} or action["data_type"] not in {"synthetic", "real_market"}:
            raise QuantError("INVALID_ACTION", "公司行动身份、类型或来源无效")
        identity = (action["source"], action["action_id"])
        if identity in identities:
            raise QuantError("ACTION_CONFLICT", "同一来源的公司行动 ID 重复，请去重或核对版本")
        identities.add(identity)
        for key in ("effective_at", "available_at", "qualification_at", "payment_at"):
            if action.get(key):
                action[key] = utc(action[key]).isoformat()
        if action["kind"] == "CASH_DIVIDEND":
            if not {"qualification_at", "amount_per_share", "withholding_per_share"} <= action.keys():
                raise QuantError("INVALID_ACTION", "模拟分红必须明确资格时点、每份总额及扣税假设；支付日可明确缺失")
            gross, tax = D(action["amount_per_share"]), D(action["withholding_per_share"])
            if gross <= 0 or not 0 <= tax <= gross or utc(action["qualification_at"]) > utc(action["effective_at"]):
                raise QuantError("INVALID_ACTION", "分红金额/税额或资格时点不合法")
            if action.get("payment_at") and utc(action["payment_at"]) < utc(action["effective_at"]):
                raise QuantError("INVALID_ACTION", "支付时点不能早于应收确认")
            action["amount_per_share"], action["withholding_per_share"] = str(gross), str(tax)
        else:
            ratio = D(action.get("ratio", 0))
            if ratio <= 0:
                raise QuantError("INVALID_ACTION", "拆股比例必须为正")
            action["ratio"] = str(ratio)
        normalized.append(action)
    simultaneous = [(a["symbol"], a["effective_at"]) for a in normalized]
    if len(simultaneous) != len(set(simultaneous)):
        raise QuantError("AMBIGUOUS_ACTION_ORDER", "同标的同时行动须提供分开的明确生效顺序，不按 CSV 行序猜测")
    return sorted(normalized, key=lambda a: (a["effective_at"], a["symbol"], a["source"], a["action_id"]))


def apply_actions(ledger, account_id, rows, as_of):
    if ledger.environment == "real":
        raise QuantError("REAL_SIMULATION_FORBIDDEN", "真实公司行动只依据实际凭据导入，不能写入模拟假设")
    actions = normalize_actions(rows)
    if ledger.environment == "paper" and (any(a["data_type"] != "real_market" for a in actions) or utc(as_of) > utc(now_utc())):
        raise QuantError("ENVIRONMENT_MISMATCH", "前向模拟需真实来源且不能推进未来时钟")
    task_id = digest({"account": account_id, "actions": actions, "as_of": utc(as_of).isoformat()})
    summary = {"status": "SUCCESS", "account_id": account_id, "as_of": utc(as_of).isoformat(),
               "simulation_assumption": "资格时点前持仓；明确支付日才模拟到账；不写真实账户",
               "added": 0, "duplicates": 0, "waiting": [], "no_entitlement": []}
    try:
        with ledger.transaction():
            ledger._require_account(account_id)
            for action in actions:
                if utc(action["available_at"]) > utc(as_of) or utc(action["effective_at"]) > utc(as_of):
                    summary["waiting"].append(action["action_id"])
                    continue
                identity = {"account": account_id, "environment": ledger.environment, "source": action["source"], "action": action["action_id"]}
                base = {"source": "lyra_company_simulation_v1/" + action["source"], "evidence_type": "simulated",
                        "symbol": action["symbol"], "effective_at": action["effective_at"]}
                if action["kind"] == "SPLIT":
                    events = [{**base, "event_id": digest({**identity, "kind": "SPLIT"}), "kind": "SPLIT", "ratio": action["ratio"]}]
                else:
                    cutoff = (utc(action["qualification_at"]) - timedelta(microseconds=1)).isoformat()
                    positions = ledger.snapshot(account_id, cutoff)["positions"]
                    quantity = D(positions.get(action["symbol"], 0))
                    if quantity < 0:
                        raise QuantError("INVALID_ENTITLEMENT", "资格时点持仓异常，不能推定分红资格")
                    if quantity == 0:
                        summary["no_entitlement"].append(action["action_id"])
                        continue
                    accrual_id = digest({**identity, "kind": "DIVIDEND_ACCRUAL"})
                    amount = quantity * D(action["amount_per_share"])
                    events = [{**base, "event_id": accrual_id, "kind": "DIVIDEND_ACCRUAL", "amount": str(amount)}]
                    if action.get("payment_at") and utc(action["payment_at"]) <= utc(as_of):
                        events.append({**base, "event_id": digest({**identity, "kind": "DIVIDEND_PAYMENT"}),
                                       "kind": "DIVIDEND_PAYMENT", "effective_at": action["payment_at"],
                                       "amount": str(amount), "fee": str(quantity * D(action["withholding_per_share"])),
                                       "reference_event_id": accrual_id})
                    else:
                        summary["waiting"].append(action["action_id"] + ":payment_unknown_or_future")
                result = ledger.import_events(account_id, events)
                summary["added"] += result["added"]
                summary["duplicates"] += result["duplicates"]
            if not summary["added"]:
                summary["status"] = "WAITING" if summary["waiting"] else "NO_ACTION"
            ledger.record_task(task_id, summary["status"], {**summary, "actions": actions})
    except Exception as exc:
        ledger.record_task(task_id, "FAILED", {"error": str(exc), "actions_hash": digest(actions)})
        raise
    return summary
