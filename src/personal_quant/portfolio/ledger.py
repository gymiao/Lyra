from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import json
from pathlib import Path
import sqlite3
from typing import Iterable

from ..common import QuantError, canonical, decimal as D, digest, now_utc, utc
from .plan_state import refresh_account_plans, block_account_plans
from .reconciliation import ReconciliationRules
from .schema import initialize

KINDS = {"DEPOSIT", "WITHDRAWAL", "BUY", "SELL", "FEE", "DIVIDEND_ACCRUAL", "DIVIDEND_PAYMENT", "SPLIT", "REVERSAL"}

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS schema_version(version INTEGER PRIMARY KEY);
INSERT OR IGNORE INTO schema_version VALUES(1);
CREATE TABLE IF NOT EXISTS accounts(id TEXT PRIMARY KEY, environment TEXT NOT NULL, currency TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, account_id TEXT NOT NULL REFERENCES accounts(id),
 event_id TEXT NOT NULL, content_hash TEXT NOT NULL, effective_at TEXT NOT NULL, recorded_at TEXT NOT NULL,
 payload TEXT NOT NULL, UNIQUE(account_id,event_id));
CREATE TABLE IF NOT EXISTS imports(id INTEGER PRIMARY KEY, account_id TEXT NOT NULL, content_hash TEXT NOT NULL,
 status TEXT NOT NULL, details TEXT NOT NULL, recorded_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS reconciliations(id INTEGER PRIMARY KEY, account_id TEXT NOT NULL,
 ledger_seq INTEGER NOT NULL, as_of TEXT NOT NULL, status TEXT NOT NULL, details TEXT NOT NULL, recorded_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS plans(plan_id TEXT PRIMARY KEY, intent_id TEXT NOT NULL, revision INTEGER NOT NULL,
 account_id TEXT NOT NULL REFERENCES accounts(id), execution_status TEXT NOT NULL, check_status TEXT NOT NULL,
 payload TEXT NOT NULL, reserved_cash TEXT NOT NULL, reserved_positions TEXT NOT NULL, manual_pending INTEGER NOT NULL DEFAULT 0,
 UNIQUE(intent_id,revision));
CREATE UNIQUE INDEX IF NOT EXISTS one_live_revision ON plans(intent_id)
 WHERE execution_status IN ('READY','PARTIAL');
CREATE TABLE IF NOT EXISTS tasks(task_id TEXT PRIMARY KEY, status TEXT NOT NULL, details TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS coverage(id INTEGER PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(id),
 through_time TEXT NOT NULL, source TEXT NOT NULL, evidence_hash TEXT NOT NULL, recorded_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS strategy_signals(archive_id TEXT PRIMARY KEY, signal_id TEXT NOT NULL,
 snapshot_id TEXT NOT NULL, strategy TEXT NOT NULL, decision_session TEXT NOT NULL, mode TEXT NOT NULL,
 content_hash TEXT NOT NULL, payload TEXT NOT NULL, recorded_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS signal_identity ON strategy_signals(signal_id,snapshot_id);
"""


class Ledger:
    @classmethod
    def read_only(cls,path,environment):
        """Use the existing projection methods in one immutable SQL read view."""
        if environment not in {'demo','paper','real'}:raise QuantError('INVALID_ENVIRONMENT','未知账户环境')
        path=Path(path)
        if not path.is_file():raise QuantError('UNKNOWN_LEDGER','只读账户数据库不存在')
        book=cls.__new__(cls);book.path=path;book.environment=environment;book._savepoint_sequence=0
        book.connection=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',isolation_level=None)
        book.connection.row_factory=sqlite3.Row
        try:
            book.connection.execute('BEGIN')
            if {r[0] for r in book.connection.execute('SELECT DISTINCT environment FROM accounts')}-{environment}:
                raise QuantError('ENVIRONMENT_MISMATCH','只读账户数据库属于另一环境')
            return book
        except Exception:
            book.close();raise

    def __init__(self, path: Path, environment: str):
        if environment not in {"demo", "paper", "real"}:
            raise QuantError("INVALID_ENVIRONMENT", "未知账户环境")
        self.path, self.environment = Path(path), environment
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self._savepoint_sequence = 0
        try:
            self.schema_info = initialize(self.connection, self.path, environment, SCHEMA)
        except Exception:
            self.connection.close()
            raise

    def close(self):
        self.connection.close()

    @contextmanager
    def transaction(self):
        nested = self.connection.in_transaction
        self._savepoint_sequence += 1
        savepoint = f"lyra_{self._savepoint_sequence}"
        self.connection.execute(f"SAVEPOINT {savepoint}" if nested else "BEGIN IMMEDIATE")
        try:
            yield
        except Exception:
            if nested:
                self.connection.execute(f"ROLLBACK TO {savepoint}")
                self.connection.execute(f"RELEASE {savepoint}")
            else:
                self.connection.execute("ROLLBACK")
            raise
        else:
            self.connection.execute(f"RELEASE {savepoint}" if nested else "COMMIT")

    def account(self, account_id: str):
        if not account_id or len(account_id) > 100:
            raise QuantError("INVALID_ACCOUNT", "账户 ID 不能为空或过长")
        with self.transaction():
            row = self.connection.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
            if row is None:
                if self.connection.execute("SELECT count(*) FROM accounts").fetchone()[0]:
                    raise QuantError("SINGLE_ACCOUNT", "V1 每个环境数据库只支持一个账户")
                self.connection.execute("INSERT INTO accounts VALUES(?,?,?)", (account_id, self.environment, "USD"))
        return account_id

    def _require_account(self, account_id):
        if self.connection.execute("SELECT id FROM accounts WHERE id=?", (account_id,)).fetchone() is None:
            raise QuantError("UNKNOWN_ACCOUNT", "请先显式建立空账户")

    def sequence(self, account_id):
        return self.connection.execute("SELECT COALESCE(max(seq),0) FROM events WHERE account_id=?", (account_id,)).fetchone()[0]

    def normalize_event(self, raw: dict, account_id: str) -> dict:
        if raw.get('kind') in {'OPTION_TRADE','OPTION_EXERCISE','OPTION_ASSIGNMENT','OPTION_EXPIRY','OPTION_CASH_SETTLEMENT'}:
            from ..options.ledger import normalize_option_event
            return normalize_option_event(self,raw,account_id)
        required = {"event_id", "kind", "effective_at", "source", "evidence_type"}
        allowed = required | {"account_id", "environment", "currency", "symbol", "plan_id", "reference_event_id", "amount", "quantity", "price", "fee", "ratio", "settlement_at"}
        if set(raw) - allowed:
            raise QuantError("INVALID_EVENT", f"未知事件字段：{sorted(set(raw) - allowed)}，请按标准模板映射")
        if not required <= raw.keys():
            raise QuantError("INVALID_EVENT", f"账务缺少字段：{sorted(required - raw.keys())}")
        if raw.get("account_id", account_id) != account_id or raw.get("environment", self.environment) != self.environment:
            raise QuantError("ENVIRONMENT_MISMATCH", "账单账户或运行环境不匹配")
        if raw.get("currency", "USD") != "USD":
            raise QuantError("CURRENCY_MISMATCH", "V1 不自动换算账单币种")
        kind = str(raw["kind"]).upper()
        if kind not in KINDS or not raw["event_id"] or not raw["source"]:
            raise QuantError("INVALID_EVENT", "事件类型、ID 或来源无效")
        if raw["evidence_type"] not in {"actual", "test", "simulated"} or (self.environment == "real" and raw["evidence_type"] != "actual"):
            raise QuantError("ENVIRONMENT_MISMATCH", "真实账本只接收明确实际凭据，不能导入模拟/测试记录")
        event = {"event_id": str(raw["event_id"]), "account_id": account_id, "environment": self.environment,
                 "currency": "USD", "kind": kind, "source": str(raw["source"]),
                 "evidence_type": raw["evidence_type"], "effective_at": utc(raw["effective_at"]).isoformat(),
                 "symbol": str(raw.get("symbol") or ""), "plan_id": str(raw.get("plan_id") or ""),
                 "reference_event_id": str(raw.get("reference_event_id") or "")}
        if self.environment == "real" and utc(event["effective_at"]) > utc(now_utc()):
            raise QuantError("FUTURE_ACCOUNT_EVENT", "尚未发生的真实资金/成交不能入账；未来结算时点可单独记录")
        if event["plan_id"]:
            plan = self.connection.execute("SELECT account_id FROM plans WHERE plan_id=?", (event["plan_id"],)).fetchone()
            if plan is None or plan[0] != account_id:
                raise QuantError("INVALID_PLAN_REFERENCE", "关联计划必须存在且属于同一账户；无法确认时请保留为未关联事实")
        for name in ["amount", "quantity", "price", "fee", "ratio"]:
            event[name] = str(D(raw.get(name) or (1 if name == "ratio" else 0)))
        if any(D(event[k]) < 0 for k in ["amount", "quantity", "price", "fee"]) or D(event["ratio"]) <= 0:
            raise QuantError("INVALID_EVENT", "数量、价格、金额、费用不可负；方向由事件类型表达")
        if kind in {"BUY", "SELL"} and (not event["symbol"] or D(event["quantity"]) <= 0 or D(event["price"]) <= 0):
            raise QuantError("INVALID_EVENT", "成交必须有标的、正数量及价格")
        if kind in {"DEPOSIT", "WITHDRAWAL", "FEE", "DIVIDEND_ACCRUAL", "DIVIDEND_PAYMENT"} and D(event["amount"]) <= 0:
            raise QuantError("INVALID_EVENT", "资金事件金额必须为正")
        if kind == "SPLIT" and not event["symbol"]:
            raise QuantError("INVALID_EVENT", "拆股必须有标的")
        settlement = raw.get("settlement_at")
        event["settlement_at"] = utc(settlement).isoformat() if settlement else None
        if settlement and utc(settlement) < utc(event["effective_at"]):
            raise QuantError("INVALID_EVENT", "结算时点不得早于成交")
        if kind == "REVERSAL":
            row = self.connection.execute("SELECT payload FROM events WHERE account_id=? AND event_id=?", (account_id, event["reference_event_id"])).fetchone()
            if not row or json.loads(row[0])["kind"] == "REVERSAL":
                raise QuantError("INVALID_REVERSAL", "冲销必须关联同账户已存在的原事件")
            original = json.loads(row[0])
            if event["effective_at"] != original["effective_at"]:
                raise QuantError("INVALID_REVERSAL", "冲销生效时点必须等于原事件，以重建受影响历史")
        return event

    def import_events(self, account_id: str, rows: Iterable[dict], expected_sequence: int | None = None,
                      *, coverage_through=None, coverage_source=None):
        self._require_account(account_id)
        rows = list(rows)
        batch_hash = digest(rows)
        added, duplicates = 0, 0
        try:
            with self.transaction():
                if expected_sequence is not None and expected_sequence != self.sequence(account_id):
                    raise QuantError("STALE_PREVIEW", "账户已变化，请重新预检")
                for raw in rows:
                    event = self.normalize_event(raw, account_id)
                    identity = digest(event)
                    previous = self.connection.execute("SELECT content_hash FROM events WHERE account_id=? AND event_id=?", (account_id, event["event_id"])).fetchone()
                    if previous:
                        if previous[0] != identity:
                            raise QuantError("EVENT_CONFLICT", f"同一事件 ID 内容冲突：{event['event_id']}")
                        duplicates += 1
                        continue
                    self.connection.execute("INSERT INTO events(account_id,event_id,content_hash,effective_at,recorded_at,payload) VALUES(?,?,?,?,?,?)",
                                            (account_id, event["event_id"], identity, event["effective_at"], now_utc(), canonical(event)))
                    added += 1
                latest_time = self.connection.execute("SELECT max(effective_at) FROM events WHERE account_id=?", (account_id,)).fetchone()[0]
                if latest_time:
                    self.snapshot(account_id, latest_time)
                    if added:
                        refresh_account_plans(self, account_id, latest_time)
                        if self.connection.execute('SELECT version FROM schema_version').fetchone()[0]>=5:
                            from ..options.lifecycle import refresh
                            refresh(self,account_id,latest_time)
                self.connection.execute("INSERT INTO imports(account_id,content_hash,status,details,recorded_at) VALUES(?,?,?,?,?)",
                                        (account_id, batch_hash, "SUCCESS", canonical({"added": added, "duplicates": duplicates}), now_utc()))
                if coverage_through is not None:
                    if not coverage_source:
                        raise QuantError("INVALID_COVERAGE", "完整覆盖声明必须指定独立账单来源")
                    self.record_coverage(account_id, coverage_through, coverage_source, batch_hash)
        except Exception as exc:
            self.connection.execute("INSERT INTO imports(account_id,content_hash,status,details,recorded_at) VALUES(?,?,?,?,?)",
                                    (account_id, batch_hash, "FAILED", canonical({"error": str(exc)}), now_utc()))
            raise
        return {"added": added, "duplicates": duplicates, "ledger_seq": self.sequence(account_id), "batch_hash": batch_hash}

    def preview(self, account_id: str, rows: Iterable[dict], as_of, prices=None):
        """Execute validation on the actual database transaction, then always roll back."""
        self._require_account(account_id)
        rows = list(rows)
        added, duplicates = [], []
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            sequence = self.sequence(account_id)
            for raw in rows:
                event = self.normalize_event(raw, account_id)
                identity = digest(event)
                previous = self.connection.execute("SELECT content_hash FROM events WHERE account_id=? AND event_id=?", (account_id, event["event_id"])).fetchone()
                if previous:
                    if previous[0] != identity:
                        raise QuantError("EVENT_CONFLICT", f"事件内容冲突：{event['event_id']}")
                    duplicates.append(event["event_id"])
                else:
                    self.connection.execute("INSERT INTO events(account_id,event_id,content_hash,effective_at,recorded_at,payload) VALUES(?,?,?,?,?,?)",
                                            (account_id, event["event_id"], identity, event["effective_at"], now_utc(), canonical(event)))
                    added.append(event["event_id"])
            if added:
                refresh_account_plans(self, account_id, as_of)
            snapshot = self.snapshot(account_id, as_of, prices)
            return {"expected_sequence": sequence, "batch_hash": digest(rows), "added": added,
                    "duplicates": duplicates, "projected_snapshot": snapshot}
        finally:
            self.connection.execute("ROLLBACK")


    def active_events(self, account_id, as_of, ledger_seq=None):
        cutoff = utc(as_of).isoformat()
        sequence = self.sequence(account_id) if ledger_seq is None else ledger_seq
        rows = self.connection.execute("SELECT seq,payload FROM events WHERE account_id=? AND effective_at<=? AND seq<=? ORDER BY effective_at,seq", (account_id, cutoff, sequence)).fetchall()
        events = [dict(json.loads(row["payload"]), seq=row["seq"]) for row in rows]
        reversed_ids = {e["reference_event_id"] for e in events if e["kind"] == "REVERSAL"}
        return [e for e in events if e["kind"] != "REVERSAL" and e["event_id"] not in reversed_ids]

    def snapshot(self, account_id: str, as_of, prices: dict | None = None, ledger_seq=None) -> dict:
        self._require_account(account_id)
        instant = utc(as_of)
        cash, receivable, payable, deposits, withdrawals = [D(0) for _ in range(5)]
        positions, accruals, anomalies = {}, {}, []
        option_positions,option_contracts={},{}
        for event in self.active_events(account_id, as_of, ledger_seq):
            kind, symbol = event["kind"], event["symbol"]
            amount, quantity, price, fee = (D(event[k]) for k in ["amount", "quantity", "price", "fee"])
            if kind == "DEPOSIT":
                cash += amount
                deposits += amount
            elif kind == "WITHDRAWAL":
                cash -= amount
                withdrawals += amount
            elif kind == "FEE":
                cash -= amount
            elif kind in {"BUY", "SELL"}:
                sign = 1 if kind == "BUY" else -1
                positions[symbol] = positions.get(symbol, D(0)) + sign * quantity
                net = quantity * price + fee if kind == "BUY" else quantity * price - fee
                settled = event["settlement_at"] is not None and utc(event["settlement_at"]) <= instant
                if settled:
                    cash += (-net if kind == "BUY" else net)
                elif kind == "BUY":
                    payable += net
                else:
                    receivable += net
                if event["settlement_at"] is None:
                    anomalies.append("结算时点未知：" + event["event_id"])
            elif kind == "DIVIDEND_ACCRUAL":
                accruals[event["event_id"]] = amount
                receivable += amount
            elif kind == "DIVIDEND_PAYMENT":
                reference = event["reference_event_id"]
                if reference:
                    accrued = accruals.get(reference)
                    if accrued != amount:
                        raise QuantError("DIVIDEND_MISMATCH", "分红支付与已确认应收金额不一致")
                    receivable -= amount
                    del accruals[reference]
                cash += amount - fee
            elif kind == "SPLIT":
                positions[symbol] = positions.get(symbol, D(0)) * D(event["ratio"])
                if any(option_positions.get(key,D(0)) and contract.underlying==symbol for key,contract in option_contracts.items()):
                    anomalies.append('标的拆股涉及未处理期权单位行动：'+event['event_id'])
            elif kind.startswith('OPTION_'):
                from ..options.ledger import apply_option_event
                delta_cash,delta_receivable,delta_payable=apply_option_event(event,instant,positions,option_positions,option_contracts,anomalies)
                cash+=delta_cash;receivable+=delta_receivable;payable+=delta_payable
        positions = {s: q for s, q in positions.items() if q != 0}
        prices = {s: D(p) for s, p in (prices or {}).items()}
        option_positions={s:q for s,q in option_positions.items() if q}
        missing = sorted((set(positions)|set(option_positions)) - set(prices))
        if any(p < 0 or (p==0 and s not in option_positions) for s,p in prices.items()):
            raise QuantError("INVALID_PRICE", "估值价格必须为正")
        value = sum((q * prices[s] for s, q in positions.items() if s in prices), D(0))
        option_value=sum((q*prices[s]*option_contracts[s].quote_multiplier for s,q in option_positions.items() if s in prices),D(0))
        value+=option_value
        unverified_option_units=[]
        if self.environment=='real':
            from ..options.ledger import verify_contract_evidence
            for symbol,contract in option_contracts.items():
                try:verify_contract_evidence(self.path.parent,contract)
                except QuantError:
                    unverified_option_units.append(symbol)
                    anomalies.append('实际合约单位凭据缺失或改变：'+symbol)
        equity = None if missing or unverified_option_units else cash + receivable - payable + value
        plans = self.connection.execute("SELECT reserved_cash,reserved_positions FROM plans WHERE account_id=?", (account_id,)).fetchall()
        if self.connection.execute('SELECT version FROM schema_version').fetchone()[0]>=5:
            from ..options.lifecycle import refresh
            historical={body['plan_id']:body for body in refresh(self,account_id,as_of,persist=False,ledger_seq=ledger_seq)}
            plans=list(plans)
            for row in self.connection.execute('SELECT * FROM option_plans WHERE account_id=?',(account_id,)):
                active=historical[row['plan_id']].get('active_reservation')
                state=historical[row['plan_id']].get('manual_execution')
                if active is not None:
                    plans.append({'reserved_cash':active['reserved_cash'],'reserved_positions':canonical(active['reserved_positions'])})
                    continue
                if json.loads(row['payload']).get('activation') and not historical[row['plan_id']].get('activation'):
                    plans.append({'reserved_cash':'0','reserved_positions':'{}'})
                    continue
                if state is not None:
                    plans.append({'reserved_cash':state['reserved_cash'],'reserved_positions':canonical(state['reserved_positions'])})
                elif json.loads(row['payload']).get('manual_execution'):
                    plans.append({'reserved_cash':'0','reserved_positions':'{}'})
                else:plans.append(row)
        reserved = sum((D(row["reserved_cash"]) for row in plans), D(0))
        reserved_positions = {}
        for row in plans:
            for symbol, quantity in json.loads(row["reserved_positions"]).items():
                reserved_positions[symbol] = reserved_positions.get(symbol, D(0)) + D(quantity)
        from ..options.ledger import collateral
        option_cash,option_shares,option_issues=collateral(positions,option_positions,option_contracts)
        anomalies.extend(option_issues)
        if cash-payable-reserved<option_cash:anomalies.append('期权现金担保不足，禁止新风险计划')
        for symbol,required in option_shares.items():
            if positions.get(symbol,D(0))-reserved_positions.get(symbol,D(0))<required:
                anomalies.append('期权覆盖证券已被其他计划占用：'+symbol)
            reserved_positions[symbol]=reserved_positions.get(symbol,D(0))+required
        if cash - payable < 0 or any(q < 0 for q in positions.values()):
            anomalies.append("实际凭据反映资金或持仓异常，需要核对；不裁剪事实余额")
        result={"account_id": account_id, "environment": self.environment, "currency": "USD", "as_of": instant.isoformat(),
                "ledger_seq": self.sequence(account_id) if ledger_seq is None else ledger_seq,
                "settled_cash": str(cash), "receivables": str(receivable), "payables": str(payable),
                "reserved_cash": str(reserved+option_cash), "available_cash": str(cash - payable - reserved-option_cash),
                "reserved_positions": {s: str(q) for s, q in reserved_positions.items()},
                "positions": {s: str(q) for s, q in positions.items()}, "prices": {s: str(p) for s, p in prices.items()},
                "equity": str(equity) if equity is not None else None, "missing_prices": missing,
                "deposits": str(deposits), "withdrawals": str(withdrawals), "net_contributions": str(deposits - withdrawals),
                "investment_pnl": str(equity - deposits + withdrawals) if equity is not None else None,
                "anomalies": anomalies}
        if self.connection.execute('SELECT version FROM schema_version').fetchone()[0]>=5:
            from ..options.lifecycle import refresh
            for body in refresh(self,account_id,as_of,persist=False,ledger_seq=ledger_seq):
                anomalies.extend(body['progress']['fact_anomalies'])
            from ..options.exit_tasks import pending_exits
            outstanding_exits=pending_exits(self,account_id,as_of,ledger_seq)
            result['pending_option_exits']=outstanding_exits
            if self.connection.execute('SELECT 1 FROM pending_option_events WHERE account_id=?',(account_id,)).fetchone():
                anomalies.append('存在未核实期权凭据，暂停可执行建议')
            result.update(option_positions={s:str(q) for s,q in option_positions.items()},option_market_value=str(option_value),
                option_cash_collateral=str(option_cash),option_covered_shares={s:str(q) for s,q in option_shares.items()})
            result['unverified_option_units']=sorted(unverified_option_units)
        return result

    def reconcile(self, account_id: str, expected: dict, prices=None, *, rules: ReconciliationRules | None = None):
        with self.transaction():
            return self._reconcile(account_id, expected, prices, rules=rules)

    def _reconcile(self, account_id: str, expected: dict, prices=None, *, rules=None):
        if expected.get("currency") != "USD" or expected.get("account_id") != account_id:
            raise QuantError("INVALID_RECONCILIATION", "快照账户与币种必须明确匹配")
        if not {"as_of", "cash", "positions", "cash_basis"} <= expected.keys() or not isinstance(expected["positions"], dict):
            raise QuantError("INVALID_RECONCILIATION", "快照必须明确提供时点、现金口径、现金及持仓映射，不能把缺失视为零")
        if self.environment == "real" and (not expected.get("source") or not expected.get("evidence_hash") or expected.get("source") == "internal_simulation_check"):
            raise QuantError("INVALID_RECONCILIATION", "真实账户对账需要独立来源及凭据哈希，内部自检不能作为券商证据")
        if rules is None:
            if self.environment == "real":
                raise QuantError("MISSING_RECONCILIATION_CONFIG", "真实账户对账必须显式提供容差规则，不能继承测试默认值")
            rules = ReconciliationRules()  # Direct offline API's documented test defaults.
        if not isinstance(rules, ReconciliationRules):
            raise QuantError("INVALID_RECONCILIATION_RULES", "对账规则类型无效")
        snapshot = self.snapshot(account_id, expected["as_of"], prices)
        basis = expected.get("cash_basis")
        if basis not in {"settled", "trade_date"}:
            raise QuantError("INVALID_RECONCILIATION", "必须指定 settled 或 trade_date 现金口径")
        cash = D(snapshot["settled_cash"])
        if basis == "trade_date":
            cash += D(snapshot["receivables"]) - D(snapshot["payables"])
        differences = {}
        if snapshot.get('option_positions') and not isinstance(expected.get('option_positions'),dict):
            differences['option_positions']={'actual':snapshot['option_positions'],'expected':'缺少完整期权持仓快照'}
        elif isinstance(expected.get('option_positions'),dict):
            for contract_id in set(snapshot.get('option_positions',{}))|set(expected['option_positions']):
                actual=D(snapshot.get('option_positions',{}).get(contract_id,0));target=D(expected['option_positions'].get(contract_id,0))
                if actual!=target:differences['option:'+contract_id]={'actual':str(actual),'expected':str(target)}
        if abs(cash - D(expected["cash"])) > rules.cash:
            differences["cash"] = {"actual": str(cash), "expected": str(expected["cash"])}
        for symbol in set(snapshot["positions"]) | set(expected.get("positions", {})):
            actual = D(snapshot["positions"].get(symbol, 0))
            target = D(expected.get("positions", {}).get(symbol, 0))
            if abs(actual - target) > rules.quantity:
                differences[symbol] = {"actual": str(actual), "expected": str(target)}
        if expected.get("equity") is not None:
            if snapshot["equity"] is None or abs(D(snapshot["equity"]) - D(expected["equity"])) > rules.equity:
                differences["equity"] = {"actual": snapshot["equity"], "expected": str(expected["equity"])}
        status = "PASSED" if not differences and not snapshot["anomalies"] else "DIFFERENCES"
        details = {"expected": expected, "snapshot": snapshot, "differences": differences,
                   "rules": rules.content(), "rules_hash": rules.hash}
        inserted = self.connection.execute("INSERT INTO reconciliations(account_id,ledger_seq,as_of,status,details,recorded_at) VALUES(?,?,?,?,?,?)",
                                (account_id, snapshot["ledger_seq"], utc(expected["as_of"]).isoformat(), status, canonical(details), now_utc()))
        if status != "PASSED":
            block_account_plans(self, account_id, inserted.lastrowid)
        return {"status": status, **details}

    def record_task(self, task_id, status, details):
        self.connection.execute("INSERT INTO tasks VALUES(?,?,?,?) ON CONFLICT(task_id) DO UPDATE SET status=excluded.status,details=excluded.details,updated_at=excluded.updated_at",
                                (task_id, status, canonical(details), now_utc()))

    def record_coverage(self, account_id, through, source, evidence_hash):
        """User's explicit statement of complete imports, never inferred from row dates."""
        self._require_account(account_id)
        through = utc(through).isoformat()
        if not source or len(evidence_hash) != 64 or any(c not in "0123456789abcdef" for c in evidence_hash):
            raise QuantError("INVALID_COVERAGE", "覆盖声明需要明确来源和 64 位 SHA-256 凭据哈希")
        if self.environment == "real" and (utc(through) > utc(now_utc()) or source == "internal_simulation_check"):
            raise QuantError("INVALID_COVERAGE", "真实覆盖不能指向未来或内部模拟自检")
        with self.transaction():
            self.connection.execute("INSERT INTO coverage(account_id,through_time,source,evidence_hash,recorded_at) VALUES(?,?,?,?,?)",
                                    (account_id, through, source, evidence_hash, now_utc()))
        return {"account_id": account_id, "through": through, "source": source, "evidence_hash": evidence_hash}

    def check_reconciliation(self, account_id, as_of, max_days, *, reference_time=None, rules_hash=None):
        row = self.connection.execute("SELECT * FROM reconciliations WHERE account_id=? ORDER BY id DESC LIMIT 1", (account_id,)).fetchone()
        if not row or row["status"] != "PASSED":
            raise QuantError("UNRESOLVED_RECONCILIATION", "尚未对账或存在未解决差异")
        if rules_hash is not None and json.loads(row["details"]).get("rules_hash") != rules_hash:
            raise QuantError("RECONCILIATION_RULES_CHANGED", "对账容差已改变或旧基线没有规则版本，需要按当前规则重新核对")
        age = (utc(as_of) - utc(row["as_of"])).total_seconds() / 86400
        if not 0 <= age <= max_days:
            raise QuantError("STALE_RECONCILIATION", "独立对账基线过期，需要重新核对")
        additions = self.connection.execute("SELECT payload FROM events WHERE account_id=? AND effective_at<=? AND (seq>? OR effective_at>?)",
                                             (account_id, utc(as_of).isoformat(), row["ledger_seq"], row["as_of"])).fetchall()
        events = [json.loads(e[0]) for e in additions]
        if any(e["kind"] == "REVERSAL" or utc(e["effective_at"]) <= utc(row["as_of"]) for e in events):
            raise QuantError("STALE_RECONCILIATION", "迟到或更正事件影响已对账历史，需重新独立对账")
        if self.snapshot(account_id, as_of)["anomalies"]:
            raise QuantError("UNRESOLVED_RECONCILIATION", "对账基线后的事件存在账户异常或未知结算")
        for event in events:
            if event['kind'].startswith('OPTION_'):
                raise QuantError('UNRESOLVED_RECONCILIATION','对账基线后有期权生命周期事实，请取得独立完整快照重新核对')
            if event["kind"] in {"BUY", "SELL"}:
                plan = self.connection.execute("SELECT payload FROM plans WHERE plan_id=?", (event["plan_id"],)).fetchone()
                if not plan or json.loads(plan[0]).get("actual_anomalies"):
                    raise QuantError("UNRESOLVED_RECONCILIATION", "基线后有未关联或超计划成交，需独立核对")
        if self.environment == "real" or any(e["evidence_type"] == "actual" for e in events):
            coverage = self.connection.execute("SELECT * FROM coverage WHERE account_id=? ORDER BY through_time DESC LIMIT 1", (account_id,)).fetchone()
            required = max([utc(e["effective_at"]) for e in events] + [utc(reference_time or as_of)])
            if required > utc(row["as_of"]) and (not coverage or utc(coverage["through_time"]) < required):
                raise QuantError("INCOMPLETE_STATEMENT_COVERAGE", "基线后的实际事件缺完整账单覆盖声明，不能由序号推断没有漏单")
        return {"reconciliation_id": row["id"], "rules_hash": json.loads(row["details"]).get("rules_hash"), "basis_sequence": row["ledger_seq"],
                "current_sequence": self.sequence(account_id), "advanced_events": len(events)}

    def backup(self, destination: Path):
        if destination.resolve() == self.path.resolve():
            raise QuantError("INVALID_BACKUP", "备份不可覆盖原数据库")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(destination) as output:
            self.connection.backup(output)
