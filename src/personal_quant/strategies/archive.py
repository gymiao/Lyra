"""Immutable signal evidence shared by CLI, plans and the dashboard."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ..common import QuantError, canonical, digest, now_utc, utc
from .monthly import Signal, VERSION, signal
from .adapter import decode_signal, signal_v2
from .spec import StrategySpec, DataBundle


def source_fingerprint():
    root = Path(__file__).resolve().parents[1]
    return digest({str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in sorted(root.rglob("*.py"))})


class SignalArchive:
    def __init__(self, ledger):
        self.ledger = ledger

    def get(self, archive_id):
        row = self.ledger.connection.execute("SELECT * FROM strategy_signals WHERE archive_id=?", (archive_id,)).fetchone()
        if row is None:
            raise QuantError("UNKNOWN_SIGNAL", "信号归档不存在")
        try:
            body = json.loads(row["payload"])
            if digest(body) != row["content_hash"] or body["archive_id"] != archive_id:
                raise ValueError("内容哈希不匹配")
            value = decode_signal(body["signal"])
            if value.signal_id != row["signal_id"] or value.snapshot_id != row["snapshot_id"]:
                raise ValueError("归档身份不匹配")
            if body["environment"] != self.ledger.environment:
                raise ValueError("环境不匹配")
        except (KeyError, TypeError, ValueError) as exc:
            raise QuantError("CORRUPT_SIGNAL", "信号归档损坏，不作为交易依据") from exc
        return body

    def list(self, *, mode=None, limit=100):
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 1000:
            raise QuantError("INVALID_SIGNAL_QUERY", "信号查询最多 1000 条")
        if mode not in {None, "forward", "historical_reconstruction"}:
            raise QuantError("INVALID_MODE", "信号查询模式无效")
        rows = self.ledger.connection.execute(
            "SELECT archive_id FROM strategy_signals WHERE (? IS NULL OR mode=?) ORDER BY rowid DESC LIMIT ?",
            (mode, mode, limit)).fetchall()
        return [self.get(row[0]) for row in rows]

    def require(self, value):
        rows = self.ledger.connection.execute(
            "SELECT archive_id FROM strategy_signals WHERE signal_id=? AND snapshot_id=? ORDER BY rowid DESC",
            (value.signal_id, value.snapshot_id)).fetchall()
        for row in rows:
            body = self.get(row[0])
            if body["signal"] == value.content():
                return body
        raise QuantError("UNARCHIVED_SIGNAL", "前向计划必须引用已冻结的完整信号归档，不能从历史报告或临时对象生成")

    def generate(self, frame, metadata, calendar, config, session, *, strategy=None,
                 decision_time=None, mode=None, account_state=None, bundle=None):
        if self.ledger.environment != config.environment:
            raise QuantError("ENVIRONMENT_MISMATCH", "信号归档与配置环境不同")
        mode = mode or ("historical_reconstruction" if config.environment == "demo" else "forward")
        if config.environment != "demo" and mode != "forward":
            raise QuantError("ENVIRONMENT_MISMATCH", "真实/前向环境只能归档实际前向信号")
        if mode == "forward" and decision_time is not None:
            raise QuantError("HISTORICAL_TIME_FORBIDDEN", "前向信号使用系统实际时钟，不能手工回填决策时间")
        strategy = strategy or config.active_strategy
        spec = StrategySpec.from_dict(config.strategy_spec) if config.strategy_spec else None
        if spec:
            bundle = bundle or DataBundle(metadata["snapshot_id"], calendar.hash,
                                           execution_snapshot_id=metadata["snapshot_id"])
            if bundle.signal_snapshot_id != metadata["snapshot_id"] or bundle.calendar_hash != calendar.hash:
                raise QuantError("INVALID_DATA_BUNDLE", "归档输入必须与冻结数据包一致")
            if strategy != spec.template_id:
                raise QuantError("STRATEGY_CONFIG_CONFLICT", "归档策略必须来自冻结规格")
        # A stable request key preserves the first generation time on retries.
        identity = {"environment": config.environment, "mode": mode, "session": str(calendar.close(session).date()),
                    "strategy": strategy, "strategy_version": spec.content()["implementation_version"] if spec else VERSION, "snapshot_id": metadata["snapshot_id"],
                    "config_hash": config.hash, "source_hash": source_fingerprint(),
                    "historical_decision_time": utc(decision_time).isoformat() if decision_time else None}
        if spec:
            identity.update(spec_hash=spec.spec_hash, data_bundle=bundle.content())
        archive_id = digest(identity)
        with self.ledger.transaction():
            if self.ledger.connection.execute("SELECT 1 FROM strategy_signals WHERE archive_id=?", (archive_id,)).fetchone():
                return self.get(archive_id)
            if metadata["calendar_hash"] != calendar.hash or metadata["calendar_kind"] != calendar.kind:
                raise QuantError("INVALID_SIGNAL_DATA", "信号日历与数据快照不一致")
            actual_time = now_utc()
            if mode == "forward":
                if metadata["data_type"] != "real_market" or set(frame.data_type) != {"real_market"} or calendar.kind != "verified_market_sessions":
                    raise QuantError("ENVIRONMENT_MISMATCH", "前向信号需要真实行情和核验市场日历，不能使用合成样本")
                if config.publication_delay_minutes is None:
                    raise QuantError("MISSING_EXECUTION_CONFIG", "前向信号需明确日线发布延迟")
                if utc(metadata["acquired_at"]) > utc(actual_time):
                    raise QuantError("DATA_NOT_OBSERVED", "实际生成信号时尚未取得该数据快照")
                if calendar.latest_completed(actual_time, config.publication_delay_minutes).date() != calendar.close(session).date():
                    raise QuantError("STALE_SIGNAL_DATA", "前向信号必须使用当前最近完整发布的月末日线")
            if spec:
                factors = error = None
                if spec.template_id == "multi_factor" and spec.content()["parameters"]["mode"] == "fundamental":
                    from ..data.factors import FactorStore
                    import pandas as pd
                    try:
                        if not bundle.factor_snapshot_id:
                            raise QuantError("MISSING_FACTORS", "基本面策略缺少冻结因子快照")
                        cutoff = decision_time or (calendar.close(session) + pd.Timedelta(minutes=config.publication_delay_minutes)).isoformat()
                        factors = FactorStore(Path(config.runtime_dir) / "factors").select(bundle.factor_snapshot_id, spec,
                            actual_time if mode == "forward" else cutoff, forward=mode == "forward")
                    except QuantError as exc:
                        error = exc
                value = signal_v2(frame, calendar, config, spec, session, bundle,
                    decision_time=actual_time if mode == "forward" else decision_time, research_mode=mode,
                    account_state=account_state, factor_values=factors, factor_error=error)
            else:
                value = signal(frame, calendar, config, session, strategy, metadata["snapshot_id"],
                               decision_time=actual_time if mode == "forward" else decision_time,
                               research_mode=mode, account_state=account_state)
            body = {"schema_version": 2 if spec else 1, "archive_id": archive_id, "environment": config.environment,
                    "request": identity, "signal": value.content(), "config": config.content(),
                    "data": {name: metadata[name] for name in ("snapshot_id", "data_hash", "data_type", "source",
                                                               "price_basis", "acquired_at", "calendar_hash", "calendar_kind")},
                    "historical_availability_assumed": metadata.get("historical_availability_assumed", True),
                    "account_input": account_state,
                    "eligible_at": calendar.close(value.eligible_session).isoformat(),
                    "expires_at": calendar.close(value.valid_through_session).isoformat()}
            self.ledger.connection.execute("INSERT INTO strategy_signals VALUES(?,?,?,?,?,?,?,?,?)",
                (archive_id, value.signal_id, value.snapshot_id, value.strategy, value.decision_session,
                 value.research_mode, digest(body), canonical(body), now_utc()))
            # The first call and a retry use the same JSON-normalized representation.
            return self.get(archive_id)
