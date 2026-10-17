from __future__ import annotations

from pathlib import Path
import hashlib
import json
import math
import os
import shutil
from uuid import uuid4
from ..common import QuantError, canonical, decimal as D, digest, write_json
from ..data.quotes import quote_set


def xirr(ledger, account_id, as_of, equity):
    if equity is None:
        return {"value": None, "reason": "权益估值不完整"}
    events = ledger.active_events(account_id, as_of)
    flows = [(e["effective_at"][:10], -D(e["amount"]) if e["kind"] == "DEPOSIT" else D(e["amount"]))
             for e in events if e["kind"] in {"DEPOSIT", "WITHDRAWAL"}]
    flows.append((as_of[:10], D(equity)))
    grouped = {}
    for date, amount in flows:
        grouped[date] = grouped.get(date, D(0)) + amount
    flows = [(date, amount) for date, amount in sorted(grouped.items()) if amount]
    signs = [amount > 0 for _, amount in flows]
    if len(flows) < 2 or not any(signs) or all(signs):
        return {"value": None, "reason": "现金流日期或正负方向不足，无法求 XIRR"}
    if sum(a != b for a, b in zip(signs, signs[1:])) != 1:
        return {"value": None, "reason": "现金流多次变号，V1 不认定 XIRR 唯一解"}
    try:
        import pyxirr
    except ImportError:
        return {"value": None, "reason": "未安装可选 pyxirr，账户盈亏仍可正常核对"}
    try:
        value = pyxirr.xirr([d for d, _ in flows], [float(a) for _, a in flows])
        if value is not None and (not math.isfinite(float(value)) or float(value) <= -1):
            return {"value": None, "reason": "XIRR 返回非有限或不在有效定义域的结果"}
        return {"value": value, "reason": None if value is not None else "现金流无有效解"}
    except Exception as exc:
        return {"value": None, "reason": f"XIRR 无有效解：{type(exc).__name__}"}


def account_report(ledger, account_id, as_of, prices, directory: Path, *, quote_info=None):
    snapshot = ledger.snapshot(account_id, as_of, prices)
    snapshot["effective_events_hash"] = digest(ledger.active_events(account_id, snapshot["as_of"]))
    snapshot["xirr"] = xirr(ledger, account_id, snapshot["as_of"], snapshot["equity"])
    snapshot["valuation"] = quote_info or {"status": "PROVIDED_REFERENCE_PRICES", "prices": prices,
                                          "reason": "显式提供的参考价格，须另行核对口径及截至时间"}
    source = Path(__file__).resolve().parents[1]
    snapshot["source_hash"] = digest({str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(source.rglob("*.py"))})
    snapshot["report_id"] = digest(snapshot)
    text = ["# LyraX 账户报告", "", f"账户类型：{ledger.environment}；截至：{snapshot['as_of']}；币种 USD。", "",
            f"资产：{snapshot['equity'] or '估值不完整'}", f"累计入金：{snapshot['deposits']}",
            f"累计出金：{snapshot['withdrawals']}", f"投资盈亏：{snapshot['investment_pnl'] or '估值不完整'}",
            f"已结算现金：{snapshot['settled_cash']}；应收：{snapshot['receivables']}；应付：{snapshot['payables']}。",
            f"预留现金：{snapshot['reserved_cash']}（仅影响购买力，不重复扣减资产）。", "",
            f"XIRR：{snapshot['xirr']['value'] if snapshot['xirr']['value'] is not None else snapshot['xirr']['reason']}", "",
            "| 标的 | 实际份额 | 参考价格 |", "|---|---|---|"]
    text += [f"| {s} | {q} | {snapshot['prices'].get(s, '缺失')} |" for s, q in snapshot["positions"].items()]
    if snapshot.get('option_positions'):
        text += ['', '| 期权合约 | 实际张数（负数为空头） | 每报价单位估值 |', '|---|---|---|']
        text += [f"| {s} | {q} | {snapshot['prices'].get(s, '缺失')} |" for s,q in snapshot['option_positions'].items()]
        text += ['', f"期权市值：{snapshot['option_market_value']}；履约现金担保：{snapshot['option_cash_collateral']}。",
                 '估值报价由账本按实际张数和冻结乘数计算，参考中价不等于实际成交价。']
    text += ["", "异常：" + ("；".join(snapshot["anomalies"]) or "无账务异常"),
             "估值检查：" + snapshot["valuation"]["status"],
             "价格截至交易日：" + str(snapshot["valuation"].get("expected_session", "显式参考价，需核对")),
             "逐标的报价状态、来源、时点和口径详见 account.json 的 valuation。",
             "模拟及测试账户报告不代表真实资产；到账与交易必须以实际凭据为准。"]
    version = directory / "versions" / snapshot["report_id"]
    rendered = "\n".join(text) + "\n"
    version.parent.mkdir(parents=True, exist_ok=True)
    if not version.exists():
        temporary = version.parent / (".pending-" + uuid4().hex)
        temporary.mkdir()
        try:
            write_json(temporary / "account.json", snapshot)
            (temporary / "account.md").write_text(rendered, encoding="utf-8")
            write_json(temporary / "manifest.json", {"report_id": snapshot["report_id"], "files": {
                name: hashlib.sha256((temporary / name).read_bytes()).hexdigest() for name in ["account.json", "account.md"]}})
            try:
                os.replace(temporary, version)
            except OSError:
                if not version.exists():
                    raise
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    _load_version(directory, snapshot["report_id"])
    write_json(directory / "account.json", snapshot)
    text_temp = directory / (".account-" + uuid4().hex)
    text_temp.write_text(rendered, encoding="utf-8")
    os.replace(text_temp, directory / "account.md")
    write_json(directory / "latest.json", {"report_id": snapshot["report_id"]})
    return snapshot


def _load_version(directory, report_id):
    if not isinstance(report_id, str) or len(report_id) != 64 or any(c not in "0123456789abcdef" for c in report_id):
        raise QuantError("CORRUPT_REPORT", "报告版本标识非法")
    version = directory / "versions" / report_id
    try:
        manifest = json.loads((version / "manifest.json").read_text())
        if manifest.get("report_id") != report_id or set(manifest["files"]) != {"account.json", "account.md"}:
            raise ValueError("invalid manifest")
        for name, expected in manifest["files"].items():
            if hashlib.sha256((version / name).read_bytes()).hexdigest() != expected:
                raise ValueError("hash mismatch")
        snapshot = json.loads((version / "account.json").read_text())
        if snapshot.get("report_id") != report_id or digest({k: v for k, v in snapshot.items() if k != "report_id"}) != report_id:
            raise ValueError("wrong report id")
        return snapshot
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise QuantError("CORRUPT_REPORT", "已发布账户报告不完整或内容哈希冲突，不能复用") from exc


def load_account_report(directory, report_id=None):
    if report_id is not None:
        return _load_version(directory,report_id)
    if (directory / "latest.json").exists():
        latest = json.loads((directory / "latest.json").read_text())
        return _load_version(directory, latest["report_id"])
    # Older development outputs have no published manifest. Mark that boundary.
    result = json.loads((directory / "account.json").read_text())
    result["legacy_unverified_report"] = True
    return result


def report_from_store(ledger, account_id, as_of, store, config, directory, *, option_valuation=None):
    state=ledger.snapshot(account_id, as_of)
    positions = state['positions']
    if (store.root / "latest.json").exists():
        try:
            frame, metadata, calendar = store.load_role("valuation")
            quotes = quote_set(frame, calendar, config, as_of, positions)
            quotes["snapshot_id"] = metadata["snapshot_id"]
        except QuantError as exc:
            quotes = {"status": "INCOMPLETE" if positions else "CASH_ONLY", "prices": {}, "quotes": {}, "expected_session": None,
                      "reason": {"code": exc.code, "message": str(exc)}}
    else:
        quotes = {"status": "INCOMPLETE" if positions else "CASH_ONLY", "prices": {}, "quotes": {}, "expected_session": None,
                  "reason": "尚无行情"}
    if state.get('option_positions'):
        option_info={'status':'INCOMPLETE','prices':{},'checks':['OPTION_VALUATION_REQUEST_REQUIRED']}
        if option_valuation is not None:
            from ..options.data import OptionDataStore
            from ..options.valuation import quote_set as option_quotes
            if not isinstance(option_valuation,dict) or set(option_valuation)!={'snapshot_id','limits'}:
                raise QuantError('INVALID_OPTION_VALUATION','期权估值需显式snapshot_id及limits')
            option_info=option_quotes(ledger,account_id,OptionDataStore(ledger.path.parent/'options/chains'),
                                     option_valuation['snapshot_id'],as_of,option_valuation['limits'])
        quotes['options']=option_info
        quotes['prices'].update(option_info['prices'])
        stock_complete=quotes['status'] in {'COMPLETE','CASH_ONLY'}
        quotes['status']='COMPLETE' if stock_complete and option_info['status']=='COMPLETE' else 'INCOMPLETE'
    return account_report(ledger, account_id, as_of, quotes["prices"], directory, quote_info=quotes)
