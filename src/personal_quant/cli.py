from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import timedelta
import importlib.util
import json
from pathlib import Path
import subprocess
import sqlite3
import sys
import pandas as pd

from .common import QuantError, canonical, decimal as D, digest, now_utc, write_json
from .config import Config
from .data.calendar import Calendar
from .data.fixture import create_fixture
from .data.online import download
from .data.update import update_online
from .data.store import DataStore
from .execution.plans import PlanService
from .execution.simulator import simulate
from .execution.corporate import action_csv, apply_actions
from .execution.replay import lifecycle
from .execution.daily import DailyRunner
from .portfolio import Ledger
from .portfolio.reconciliation import ReconciliationRules
from .portfolio.imports import event_csv, read_snapshot
from .portfolio.report import account_report, report_from_store
from .portfolio.backup import create_bundle, restore_bundle, verify_bundle
from .research.backtest import run_research
from .strategies import history, signal, Signal, decode_signal
from .strategies.archive import SignalArchive


def read_events(path: Path):
    return event_csv(path.read_bytes())


def references(frame, as_of):
    current = frame.loc[frame.available_at <= pd.Timestamp(as_of)].sort_values("session_date").drop_duplicates("symbol", keep="last")
    return dict(zip(current.symbol, current.close))


def demo_account(config: Config):
    if config.environment != "demo":
        raise QuantError("DEMO_ISOLATION", "测试资金演示只能在 demo 环境运行")
    if config.demo_deposit is None:
        raise QuantError("MISSING_DEMO_CAPITAL", "演示需明确配置demo_deposit，不从研究资金或真实资金推断")
    config.validate()
    config.require_execution()
    delay = config.publication_delay_minutes
    root = Path(config.runtime_dir)
    price_file, calendar_file = create_fixture(root / "fixtures")
    calendar = Calendar.csv(calendar_file, "synthetic_test_sessions")
    store = DataStore(root / "data")
    store.save(pd.read_csv(price_file), calendar)
    frame, metadata, calendar = store.load()
    ledger = Ledger(root / "account.sqlite", "demo")
    ledger.account("demo-account")
    initial_day = calendar.sessions[calendar.sessions >= config.evaluation_start][0]
    initial_time = (calendar.close(initial_day) + pd.Timedelta(minutes=delay)).isoformat()
    ledger.import_events("demo-account", [{"event_id": "demo-opening-deposit", "kind": "DEPOSIT", "amount": format(D(config.demo_deposit).normalize(), "f"),
                                           "effective_at": initial_time, "source": "lyra_test_statement_v1", "evidence_type": "test"}])
    service = PlanService(ledger, config)
    report_rows, blocked = [], []
    for day in calendar.sessions:
        if not config.evaluation_start <= str(day.date()) <= config.evaluation_end:
            continue
        as_of = (calendar.close(day) + pd.Timedelta(minutes=delay)).isoformat()
        for row in ledger.connection.execute("SELECT plan_id FROM plans WHERE execution_status IN ('READY','PARTIAL')").fetchall():
            plan = service.get(row[0])
            execution = plan["payload"].get("execution_session")
            if execution and str(day.date()) >= execution:
                try:
                    simulate(service, row[0], frame, calendar, as_of)
                except QuantError as exc:
                    blocked.append({"date": str(day.date()), "plan_id": row[0], "code": exc.code, "message": str(exc)})
                    service.cancel(row[0])
        prices = references(frame, as_of)
        snapshot = ledger.snapshot("demo-account", as_of, prices)
        if day in calendar.month_ends():
            # Simulation self-consistency gate, explicitly not a broker reconciliation claim.
            ledger.reconcile("demo-account", {"account_id": "demo-account", "currency": "USD", "as_of": as_of,
                                             "cash_basis": "settled", "cash": snapshot["settled_cash"],
                                             "positions": snapshot["positions"], "source": "internal_simulation_check"}, prices,
                             rules=ReconciliationRules.from_config(config))
            archived = SignalArchive(ledger).generate(frame, metadata, calendar, config, day,
                                                     account_state=snapshot)
            decision = decode_signal(archived["signal"])
            plan = service.create("demo-account", decision, frame, metadata, calendar, as_of)
            if plan["check_status"] == "BLOCKED":
                blocked.append({"date": str(day.date()), "plan_id": plan["plan_id"], "checks": plan["payload"]["checks"]})
        report_rows.append({"date": str(day.date()), **{k: snapshot[k] for k in ["equity", "settled_cash", "receivables", "payables", "net_contributions", "investment_pnl"]}})
    output = root / "reports" / "account-demo"
    output.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(report_rows).to_csv(output / "account_curve.csv", index=False)
    last_day = calendar.sessions[(calendar.sessions >= config.evaluation_start) & (calendar.sessions <= config.evaluation_end)][-1]
    as_of = (calendar.close(last_day) + pd.Timedelta(minutes=delay)).isoformat()
    snapshot = account_report(ledger, "demo-account", as_of, references(frame, as_of), output)
    write_json(output / "simulation.json", {"config": config.content(), "snapshot_id": metadata["snapshot_id"],
               "blocked": blocked, "mode": "frozen_fixture_account_replay", "not_a_backtest": True,
               "not_forward_evidence": True, "as_of": as_of})
    ledger.record_task("account-demo", "SUCCESS", {"report": str(output), "blocked_batches": len(blocked)})
    ledger.close()
    return {"status": "SUCCESS", "report": str(output), "snapshot": snapshot, "blocked_batches": len(blocked)}


def parser():
    command = argparse.ArgumentParser(description="LyraX：研究、模拟跟踪和人工成交记录；无券商下单")
    command.add_argument("--config", default="configs/demo.toml")
    sub = command.add_subparsers(dest="command", required=True)
    input_package=sub.add_parser('input-package',help='冻结输入包、合成场景；不授予真实来源资格')
    input_package.add_argument('action',choices=['import','scenario','verify','assemble'])
    input_package.add_argument('--file',type=Path)
    input_package.add_argument('--source',type=Path)
    input_package.add_argument('--destination',type=Path)
    for name in ["fixture", "research", "demo-account", "demo-lifecycle", "demo", "status", "ui"]:
        sub.add_parser(name)
    sub.choices['ui'].add_argument('--workspace',type=Path)
    sub.choices['ui'].add_argument('--port',type=int,default=8501)
    workspace=sub.add_parser('workspace',help='建立/检查独立模拟工作区')
    workspace.add_argument('action',choices=['init','status','diagnostic','backup-review','recovery-drill','allocation-preview','tasks','task-review','inputs','operation','schedule-preview','task-retry','task-files','task-index'])
    workspace.add_argument('--workspace',type=Path,required=True)
    workspace.add_argument('--spec',type=Path)
    workspace.add_argument('--destination',type=Path)
    workspace.add_argument('--source',type=Path)
    workspace.add_argument('--file',type=Path)
    workspace.add_argument('--job-id')
    workspace.add_argument('--run-id')
    workspace.add_argument('--limit',type=int,default=100)
    workspace.add_argument('--offset',type=int,default=0)
    workspace.add_argument('--request-id')
    workspace.add_argument('--max-seconds',type=float)
    simulation_run=sub.add_parser('simulation',help='推进/暂停/恢复隔离历史模拟')
    simulation_run.add_argument('action',choices=['prepare','start','step','pause','resume','batch'])
    simulation_run.add_argument('--workspace',type=Path,required=True)
    simulation_run.add_argument('--run-id')
    simulation_run.add_argument('--through')
    simulation_run.add_argument('--file',type=Path)
    simulation_run.add_argument('--engine-root',type=Path)
    simulation_run.add_argument('--dotnet',type=Path)
    simulation_run.add_argument('--fee-per-contract',type=float)
    simulation_run.add_argument('--max-sessions',type=int)
    simulation_run.add_argument('--max-seconds',type=float)
    simulation_run.add_argument('--min-free-bytes',type=int)
    simulation_run.add_argument('--background',action='store_true')
    simulation_run.add_argument('--request-id')
    experiment=sub.add_parser('experiment',help='独立模拟实验列表、复制与公平比较')
    experiment.add_argument('action',choices=['list','clone','compare','annotate','export','compare-export','compare-verify','compare-restore'])
    experiment.add_argument('--workspace',type=Path)
    experiment.add_argument('--destination',type=Path)
    experiment.add_argument('--file',type=Path)
    experiment.add_argument('--run-id')
    experiment.add_argument('--source',type=Path)
    research = sub.choices["research"]
    research.add_argument("--experiment", type=Path)
    research.add_argument("--rerun", action="store_true")
    research.add_argument("--background", action="store_true")
    sub.add_parser("workbench-init", help="完整备份后显式升级策略工作台")
    diagnostic = sub.add_parser("doctor", help="只读检查，不创建账户或修改数据")
    diagnostic.add_argument("--as-of")
    diagnostic.add_argument("--verify-reports", action="store_true", help="显式核验全部历史研究报告文件")
    options = sub.add_parser('options', help='期权目录、理论情景与报价CSV诊断；不下单')
    paper_summary=sub.add_parser('paper-summary',help='只读汇总独立paper工作区')
    paper_summary.add_argument('--file',type=Path,required=True)
    paper_summary.add_argument('--as-of',required=True)
    options.add_argument('--action', required=True, choices=['catalog','scenario','price','stress','risk-compare','select','monthly-freeze','monthly-forward','monthly-replay','monthly-compare','engine-assess','plan-activate','plan-simulate','exit-freeze','exit-simulate','exit-cancel','exit-review','source-register','permissions-register','permissions-assess','greek-register','greek-assess','account-report','plan-draft','manual-record','plan-review','pending-list','resolve-pending','import-facts','fixture-replay','import-chain','check-chain','engine-smoke','register-contracts','wheel-state'])
    options.add_argument('--template-id')
    options.add_argument('--stock-commission-bps',type=float)
    options.add_argument('--scope')
    options.add_argument('--publication-delay-minutes',type=int)
    options.add_argument('--max-generation-delay-minutes',type=int)
    options.add_argument('--plan-id')
    options.add_argument('--event-id')
    options.add_argument('--include-exercise',action='store_true')
    options.add_argument('--market-on-close',action='store_true')
    options.add_argument('--capital',type=float)
    options.add_argument('--fee-per-contract',type=float)
    options.add_argument('--account-id')
    options.add_argument('--commit',action='store_true')
    options.add_argument('--expected-sequence',type=int)
    options.add_argument('--expected-hash')
    options.add_argument('--engine-root', type=Path)
    options.add_argument('--dotnet', type=Path)
    options.add_argument('--file', type=Path)
    options.add_argument('--contracts', type=Path)
    options.add_argument('--contract-evidence-file',type=Path)
    options.add_argument('--metadata', type=Path)
    options.add_argument('--snapshot-id')
    options.add_argument('--destination', type=Path)
    options.add_argument('--as-of')
    options.add_argument('--max-age-seconds', type=int, default=900)
    options.add_argument('--max-underlying-skew-seconds', type=int, default=60)
    options.add_argument('--max-spread-fraction', type=float, default=.25)
    alerts = sub.add_parser("notices")
    alerts.add_argument("--sync", action="store_true")
    alerts.add_argument("--acknowledge")
    package = sub.add_parser("research-package")
    package.add_argument("--action", choices=["export","verify","restore","replay"], required=True)
    package.add_argument("--run-id")
    package.add_argument("--source", type=Path)
    package.add_argument("--source-archive", type=Path)
    package.add_argument("--destination", type=Path)
    validate = sub.add_parser("research-validate")
    validate.add_argument("--file", type=Path)
    validate.add_argument("--suite-id")
    validate.add_argument("--protocol-id")
    validate.add_argument("--retry", action="store_true")
    validate.add_argument("--background", action="store_true")
    validate.add_argument("--recover", action="store_true")
    protocol = sub.add_parser("research-protocol")
    protocol.add_argument("--file", type=Path)
    worker18 = sub.add_parser("validation-worker")
    worker18.add_argument("--suite-id", required=True)
    worker18.add_argument("--retry", action="store_true")
    review = sub.add_parser("execution-review")
    review.add_argument("--plan-id", required=True)
    review.add_argument("--as-of")
    review.add_argument("--output", type=Path)
    sub.add_parser("v18-init", help="完整备份后升级v1.8，原数据用途保持未分配")
    sub.add_parser('v19-init', help='完整备份后升级v1.9；旧账务不改变')
    qualification = sub.add_parser('qualify-source',help='登记明确核验结论及本地证据；标签不能替代来源资格')
    qualification.add_argument('--file',type=Path,required=True)
    qualification.add_argument('--evidence-directory',type=Path,required=True)
    mapping = sub.add_parser('mapped-import', help='声明式券商CSV映射、预检及原子导入')
    mapping.add_argument('--account-id', required=True)
    mapping.add_argument('--file', required=True, type=Path)
    mapping.add_argument('--mapping', required=True, type=Path)
    mapping.add_argument('--as-of')
    mapping.add_argument('--commit', action='store_true')
    mapping.add_argument('--expected-sequence', type=int)
    mapping.add_argument('--expected-hash')
    sub.add_parser("data-series", help="核验并登记已有价格系列")
    sub.add_parser("data-status")
    role = sub.add_parser("data-bind")
    role.add_argument("--role", choices=["signal","execution","valuation","factor"], required=True)
    role.add_argument("--identity", required=True, help="系列或快照哈希")
    role.add_argument("--expected-revision", type=int, required=True)
    sub.add_parser("research-status")
    sub.add_parser("research-recover")
    worker = sub.add_parser("research-worker")
    worker.add_argument("--attempt-id", required=True)
    library = sub.add_parser("strategies")
    library.add_argument("--file", type=Path, help="校验并冻结策略规格JSON/TOML")
    factors = sub.add_parser("import-factors")
    factors.add_argument("--file", type=Path, required=True)
    factors.add_argument("--metadata", type=Path, required=True)
    bind = sub.add_parser("strategy-bind")
    bind.add_argument("--account-id", required=True)
    bind.add_argument("--strategy-id", required=True)
    bind.add_argument("--revision", type=int, required=True)
    bind.add_argument("--effective-session")
    bind.add_argument("--as-of", help="仅demo允许固定历史时钟")
    bind.add_argument("--expected-binding-seq", type=int)
    bind.add_argument("--expected-account-seq", type=int)
    decide = sub.add_parser("monthly-decision")
    decide.add_argument("--account-id", required=True)
    decide.add_argument("--session", required=True)
    decide.add_argument("--bundle", type=Path, required=True)
    decide.add_argument("--as-of")
    compare = sub.add_parser("compare")
    compare.add_argument("--runs", nargs="+", required=True)
    signals = sub.add_parser("signals")
    signals.add_argument("--session", help="指定月末交易日；demo 默认历史区间，前向默认最近完整交易日")
    signals.add_argument("--as-of", help="仅 demo 可使用固定历史时钟")
    archived = sub.add_parser("list-signals")
    archived.add_argument("--mode", choices=["forward", "historical_reconstruction"])
    archived.add_argument("--limit", type=int, default=20)
    daily = sub.add_parser("daily", help="可恢复的日常数据/账户/信号/计划/报告任务；无券商下单")
    daily.add_argument("--account-id", required=True)
    daily.add_argument("--as-of", help="仅 demo 可使用历史时钟")
    daily.add_argument("--fetch-start")
    daily.add_argument("--fetch-end", help="结束日期不包含；在线系列需事先显式初始化")
    daily.add_argument("--events", type=Path, help="标准事件CSV，需先独立预检")
    daily.add_argument("--expected-sequence", type=int)
    daily.add_argument("--expected-hash")
    daily.add_argument("--coverage-through")
    daily.add_argument("--coverage-source")
    daily.add_argument("--actions", type=Path, help="仅模拟环境公司行动CSV")
    daily.add_argument("--reconciliation", type=Path, help="独立账户快照CSV/JSON")
    daily.add_argument('--hedge-stage-checks',type=Path,help='组内股票模拟的plan_id到当前阶段检查请求映射JSON')
    daily.add_argument('--option-valuation',type=Path,help='显式期权估值snapshot_id和limits JSON')
    daily.add_argument('--option-tasks',type=Path,help='仅demo；已冻结OPEN/CLOSE模拟任务数组JSON')
    daily.add_argument('--option-receipts',type=Path,help='显式期权事实批次JSON；含预检哈希/账户序号')
    daily.add_argument('--option-resolutions',type=Path,help='待核实期权凭据解决请求数组JSON')
    ingest = sub.add_parser("import-prices")
    ingest.add_argument("--file", type=Path, required=True)
    ingest.add_argument("--calendar", type=Path)
    ingest.add_argument("--calendar-kind", choices=["synthetic_test_sessions", "verified_market_sessions"], default="verified_market_sessions")
    ingest.add_argument("--incremental", action="store_true")
    fetch = sub.add_parser("fetch")
    fetch.add_argument("--start", required=True)
    fetch.add_argument("--end", required=True, help="结束日期不包含，遵循数据源约定")
    fetch.add_argument("--new-series", action="store_true", help="显式开始真实行情系列，保留旧快照，不改变账本")
    fetch.add_argument("--full-refresh", action="store_true", help="重新下载完整历史，核验旧区间的修订")
    account = sub.add_parser("account")
    account.add_argument("--account-id", required=True)
    sub.add_parser('hedge-catalog',help='只读对冲方法、支持等级、风险及数据/权限前提；不建账户或计划')
    hedge = sub.add_parser('hedge-exposure',help='只读Beta/Delta账户风险，不生成交易计划')
    hedge.add_argument('--account-id',required=True)
    hedge.add_argument('--file',type=Path,required=True)
    hedge.add_argument('--archive',action='store_true',help='只发布不可变风险归档，不写账/占款')
    hedge_preview=sub.add_parser('hedge-preview',help='只读对冲候选，尚不生成可执行计划')
    hedge_preview.add_argument('--account-id',required=True)
    hedge_preview.add_argument('--file',type=Path,required=True)
    hedge_stress=sub.add_parser('hedge-stress',help='只读账户与候选统一理论情景，不生成交易')
    hedge_stress.add_argument('--account-id',required=True)
    hedge_stress.add_argument('--file',type=Path,required=True)
    hedge_coverage=sub.add_parser('hedge-coverage',help='只读指定账本前缀的实际/在途保护覆盖')
    hedge_coverage.add_argument('--account-id',required=True)
    hedge_coverage.add_argument('--file',type=Path,required=True)
    identity=sub.add_parser('security-register',help='预检或显式登记不可变证券身份，不授予执行资格')
    identity.add_argument('--file',type=Path,required=True)
    identity.add_argument('--commit',action='store_true')
    allocation=sub.add_parser('hedge-allocation',help='预检或原子登记保护引用；不新增财务预留')
    allocation.add_argument('--account-id',required=True)
    security_check=sub.add_parser('security-assess',help='只读关联证券身份、已归档来源和账本行动，不授予交易权限')
    security_check.add_argument('--account-id',required=True)
    security_check.add_argument('--file',type=Path,required=True)
    allocation.add_argument('--file',type=Path,required=True)
    allocation.add_argument('--commit',action='store_true')
    allocation_basis=sub.add_parser('hedge-allocation-basis',help='只读保护引用当前版本与资源依据')
    allocation_basis.add_argument('--account-id',required=True)
    intent=sub.add_parser('hedge-intent',help='预检或冻结父研究决定，不授予执行资格')
    intent.add_argument('--account-id',required=True)
    intent.add_argument('--file',type=Path,required=True)
    intent.add_argument('--commit',action='store_true')
    intent_list=sub.add_parser('hedge-intents',help='只读父研究决定的当前修订，不授予实时执行资格')
    intent_list.add_argument('--account-id',required=True)
    intent_close=sub.add_parser('hedge-intent-close',help='预检或登记父研究意图关闭，不撤券商单或释放资源')
    intent_close.add_argument('--account-id',required=True)
    intent_close.add_argument('--file',type=Path,required=True)
    intent_close.add_argument('--commit',action='store_true')
    stock_hedge=sub.add_parser('hedge-stock-draft',help='从冻结对冲父数量生成独立股票草案，不造月度信号或预留')
    stock_hedge.add_argument('--account-id',required=True)
    stock_hedge.add_argument('--file',type=Path,required=True)
    stock_hedge.add_argument('--commit',action='store_true')
    stock_reprice=sub.add_parser('hedge-stock-reprice',help='以当前合格原价修订确切未成交股票数量，不撤单或预留')
    stock_reprice.add_argument('--account-id',required=True)
    stock_reprice.add_argument('--file',type=Path,required=True)
    stock_reprice.add_argument('--commit',action='store_true')
    stock_units=sub.add_parser('hedge-stock-unit-rebase',help='以明确拆股凭据生成当前单位剩余草案，须修订整个股票组后激活')
    stock_units.add_argument('--account-id',required=True)
    stock_units.add_argument('--file',type=Path,required=True)
    stock_units.add_argument('--commit',action='store_true')
    stock_activation=sub.add_parser('hedge-stock-activate',help='显式预检或激活独立股票对冲草案，复用原预留/账本，不下单')
    stock_activation.add_argument('--account-id',required=True)
    stock_activation.add_argument('--file',type=Path,required=True)
    stock_activation.add_argument('--commit',action='store_true')
    native_hedge=sub.add_parser('hedge-native-plans',help='预检/生成原期权草案并绑定明确股票计划，不执行或重复预留')
    native_hedge.add_argument('--account-id',required=True)
    native_hedge.add_argument('--file',type=Path,required=True)
    native_hedge.add_argument('--commit',action='store_true')
    group=sub.add_parser('hedge-group',help='预检或绑定原计划执行组，不重复预留')
    group.add_argument('--account-id',required=True)
    group.add_argument('--file',type=Path,required=True)
    group.add_argument('--commit',action='store_true')
    stage_check=sub.add_parser('hedge-stage-check',help='只读当前执行阶段所有部分成交端点的情景/现金/覆盖，不授权交易')
    stage_check.add_argument('--account-id',required=True)
    stage_check.add_argument('--file',type=Path,required=True)
    group_list=sub.add_parser('hedge-groups',help='只读执行组原定义和实际前缀进度')
    group_list.add_argument('--account-id',required=True)
    group_list.add_argument('--as-of',required=True)
    group_list.add_argument('--ledger-seq',type=int)
    hedge_status=sub.add_parser('hedge-status',help='只读当前父/执行组/保护与阻断状态')
    group_revision=sub.add_parser('hedge-group-revise',help='保留原成交、明确替换未成交计划引用；不重复预留')
    group_revision.add_argument('--account-id',required=True)
    group_revision.add_argument('--file',type=Path,required=True)
    group_revision.add_argument('--commit',action='store_true')
    incident=sub.add_parser('option-incident-review',help='显式核实中间凭据异常；保留历史，不授权交易')
    incident.add_argument('--account-id',required=True)
    incident.add_argument('--file',type=Path,required=True)
    incident.add_argument('--evidence-directory',type=Path,required=True)
    incident.add_argument('--commit',action='store_true')
    hedge_status.add_argument('--account-id',required=True)
    hedge_status.add_argument('--as-of',required=True)
    events = sub.add_parser("import-events")
    events.add_argument("--account-id", required=True)
    events.add_argument("--file", type=Path, required=True)
    events.add_argument("--as-of")
    events.add_argument("--commit", action="store_true")
    events.add_argument("--expected-sequence", type=int)
    events.add_argument("--expected-hash")
    events.add_argument("--coverage-through", help="显式声明账单完整覆盖至此时点；不从事件日期推断")
    events.add_argument("--coverage-source")
    actions = sub.add_parser("simulate-actions")
    actions.add_argument("--account-id", required=True)
    actions.add_argument("--file", required=True, type=Path)
    actions.add_argument("--as-of", required=True)
    revision = sub.add_parser("revise-plan")
    revision.add_argument("--plan-id", required=True)
    revision.add_argument("--as-of")
    revision.add_argument('--option-valuation',type=Path,help='本次显式期权估值snapshot_id和limits JSON')
    reconciliation = sub.add_parser("reconcile")
    reconciliation.add_argument("--account-id", required=True)
    reconciliation.add_argument("--file", type=Path, required=True, help="标准快照 CSV/JSON，含现金口径及完整持仓")
    plan = sub.add_parser("plan")
    plan.add_argument("--account-id", required=True)
    plan.add_argument("--session", required=True)
    plan.add_argument("--as-of")
    plan.add_argument("--revise", action="store_true")
    plan.add_argument('--option-valuation',type=Path,help='本次显式期权估值snapshot_id和limits JSON')
    simulation = sub.add_parser("simulate")
    simulation.add_argument("--plan-id", required=True)
    simulation.add_argument("--state-as-of",help="迟到重放的冻结成交状态时点，仅允许原计划成交收盘")
    simulation.add_argument("--as-of", help="仅 demo 可使用固定历史时钟；前向默认实际系统时钟")
    simulation.add_argument('--hedge-stage-check',type=Path,help='组内股票模拟本次阶段检查请求JSON')
    simulation.add_argument('--option-valuation',type=Path,help='成交状态时点显式期权估值snapshot_id和limits JSON')
    manage = sub.add_parser("manage-plan")
    manage.add_argument("--plan-id", required=True)
    manage.add_argument("--action", choices=["submitted", "confirmed-no-pending", "cancel", "refresh"], required=True)
    manage.add_argument("--as-of")
    report = sub.add_parser("report")
    report.add_argument("--account-id", required=True)
    report.add_argument("--as-of")
    backup = sub.add_parser("backup")
    backup.add_argument("--destination", required=True, type=Path)
    bundle = sub.add_parser("backup-bundle", help="一致数据库及行情/报告/配置完整备份；目标不可覆盖")
    bundle.add_argument("--destination", required=True, type=Path)
    maintenance = sub.add_parser('backup-maintenance', help='备份清单/轮换预览/先验证新备份再轮换')
    maintenance.add_argument('--directory', required=True, type=Path)
    maintenance.add_argument('--environment', required=True, choices=['demo','paper','real'])
    maintenance.add_argument('--action', choices=['list','preview','create'], default='preview')
    maintenance.add_argument('--keep', type=int, default=3)
    maintenance.add_argument('--protect', nargs='*', default=[])
    maintenance.add_argument('--min-free-bytes', type=int, default=0)
    for name in ("verify-backup", "restore"):
        recovery = sub.add_parser(name, help="校验完整备份；恢复仅写入新的空目录")
        recovery.add_argument("--source", required=True, type=Path)
        recovery.add_argument("--environment", required=True, choices=["demo", "paper", "real"])
        if name == "restore":
            recovery.add_argument("--destination", required=True, type=Path)
    return command


def execute(args, config):
    if args.command=='hedge-catalog':
        from .hedging.catalog import catalog
        return catalog()
    if args.command=='paper-summary':
        from .portfolio.aggregate import aggregate
        return aggregate(json.loads(args.file.read_text()),args.as_of)
    if args.command == 'options':
        from .options.service import command
        return command(args,config)
    if args.command == 'doctor':
        from .diagnostics import doctor
        return doctor(config, args.as_of, verify_reports=args.verify_reports)
    if args.command == 'research-package' and args.action in {'verify','restore','replay'}:
        from .research.artifacts import verify_package, restore_package, replay_package
        if args.source is None: raise QuantError('MISSING_ARGUMENT','需要--source')
        if args.action == 'verify': return {'status':'SUCCESS',**verify_package(args.source)}
        if args.destination is None: raise QuantError('MISSING_ARGUMENT','需要新的--destination')
        return restore_package(args.source,args.destination) if args.action=='restore' else replay_package(args.source,args.destination)
    root = Path(config.runtime_dir)
    root.mkdir(parents=True, exist_ok=True)
    store = DataStore(root / "data")
    if args.command == "fixture":
        if config.environment != "demo":
            raise QuantError("DEMO_ISOLATION", "合成行情只允许写入 demo，不能污染前向或真实环境")
        price_file, calendar_file = create_fixture(root / "fixtures")
        calendar = Calendar.csv(calendar_file, "synthetic_test_sessions")
        return store.save(pd.read_csv(price_file), calendar)
    if args.command == "import-prices":
        frame = pd.read_csv(args.file)
        calendar = Calendar.csv(args.calendar, args.calendar_kind) if args.calendar else Calendar.market(str(frame.session_date.min()), str(pd.Timestamp(frame.session_date.max()) + pd.Timedelta(days=45)))
        if config.environment == "real" and set(frame.data_type) != {"real_market"}:
            raise QuantError("ENVIRONMENT_MISMATCH", "真实目录不能保存合成行情")
        return store.save(frame, calendar, incremental=args.incremental)
    if args.command == "fetch":
        selected_series = None
        if not args.new_series and (root / 'account.sqlite').exists():
            selected_series = store.series_identity(store.load_role('signal')[1]) if store.heads() else None
        return update_online(store, config, args.start, args.end, new_series=args.new_series,
                             full_refresh=args.full_refresh, series_id=selected_series)
    if args.command == "research":
        if not args.experiment:
            if args.rerun or args.background:
                raise QuantError("INVALID_EXPERIMENT", "重跑/后台运行需要明确实验请求")
            if config.strategy_spec:
                raise QuantError("INVALID_EXPERIMENT", "冻结新策略研究必须提供多成员实验请求")
            return run_research(store, config, root / "reports" / "research")
    if args.command == "signals":
        frame, metadata, calendar = store.load_role("signal")
        if args.as_of and not args.session:
            raise QuantError("INVALID_SIGNAL_QUERY", "--as-of 需要同时指定 --session，不能覆盖默认历史区间")
        if config.environment != "demo" and args.as_of:
            raise QuantError("HISTORICAL_TIME_FORBIDDEN", "前向信号不能使用手工历史时钟")
        book = Ledger(root / "account.sqlite", config.environment)
        try:
            archive = SignalArchive(book)
            result, archive_ids = {}, []
            strategies = ["fixed", "trend"] if config.environment == "demo" and not config.strategy_spec else [config.active_strategy]
            for strategy in strategies:
                if args.session:
                    requests = [(args.session, args.as_of)]
                elif config.environment == "demo":
                    if config.strategy_spec:
                        requests = [(day, None) for day in calendar.month_ends() if config.evaluation_start <= str(day.date()) <= config.evaluation_end]
                    else:
                        requests = [(x.decision_session, x.decision_time) for x in history(frame, calendar, config, strategy, metadata["snapshot_id"])]
                else:
                    if config.publication_delay_minutes is None:
                        raise QuantError("MISSING_EXECUTION_CONFIG", "前向信号需明确发布延迟")
                    requests = [(calendar.latest_completed(now_utc(), config.publication_delay_minutes), None)]
                records = [archive.generate(frame, metadata, calendar, config, session, strategy=strategy,
                                            decision_time=clock) for session, clock in requests]
                result[strategy] = [record["signal"] for record in records]
                archive_ids.extend(record["archive_id"] for record in records)
            write_json(root / "signals.json", result)  # Convenience export, never the authoritative archive.
            return {"signals_file": str(root / "signals.json"), "archive_ids": archive_ids,
                    "mode": "historical_reconstruction" if config.environment == "demo" else "forward",
                    "counts": {k: len(v) for k, v in result.items()}}
        finally:
            book.close()
    if args.command in {"demo-account", "demo"}:
        result = demo_account(config)
        if args.command == "demo":
            result["research"] = run_research(store, config, root / "reports" / "research")
        return result
    if args.command == "demo-lifecycle":
        return lifecycle(config)
    if args.command == "ui":
        if importlib.util.find_spec("streamlit") is None:
            raise QuantError("MISSING_UI_DEPENDENCY", "Streamlit 尚未安装，四页 UI 尚未运行验证")
        return subprocess.run([sys.executable, "-m", "streamlit", "run", str(Path(__file__).parent / "ui/app.py"), "--", "--config", args.config]).returncode
    ledger = Ledger(root / "account.sqlite", config.environment)
    try:
        if args.command == 'research-package':
            from .research.artifacts import export_package
            from .research.service import ResearchService
            if not args.run_id or args.destination is None: raise QuantError('MISSING_ARGUMENT','导出需要--run-id/--destination')
            return export_package(ResearchService(ledger),args.run_id,args.destination,source_archive=args.source_archive)
        if args.command in {'research-validate','research-protocol','validation-worker'}:
            from .research.validation import ValidationService
            validation=ValidationService(ledger,config)
            if args.command=='research-protocol':
                return validation.protocol(json.loads(args.file.read_text())) if args.file else {'protocols':[dict(r) for r in ledger.connection.execute('SELECT * FROM validation_protocols')]}
            if args.command=='validation-worker':return validation.run(args.suite_id,retry=args.retry)
            if args.recover:
                if not args.suite_id:raise QuantError('MISSING_ARGUMENT','恢复需要--suite-id')
                return validation.recover(args.suite_id)
            suite=validation.create(json.loads(args.file.read_text()),protocol_id=args.protocol_id) if args.file else validation.get(args.suite_id) if args.suite_id else None
            if suite is None:return {'suites':validation.list()}
            if suite.get('status')=='WAITING_FOR_DATA':return suite
            return validation.launch(suite['suite_id'],retry=args.retry) if args.background else validation.run(suite['suite_id'],retry=args.retry)
        if args.command=='execution-review':
            from .execution.review import execution_review, review_csv
            result=execution_review(ledger,config,args.plan_id,args.as_of or now_utc())
            if args.output:
                if args.output.exists():raise QuantError('NONEMPTY_DESTINATION','导出不覆盖已有文件')
                args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(review_csv(result),encoding='utf-8-sig')
            return result
        if args.command=='notices':
            from .diagnostics import doctor, notices, sync_notices, acknowledge
            if args.sync:return {'notices':sync_notices(ledger,doctor(config))}
            if args.acknowledge:return {'notices':acknowledge(ledger,args.acknowledge)}
            return {'notices':notices(ledger)}
        if args.command=='qualify-source':
            from .data.qualification import register
            return register(ledger,json.loads(args.file.read_text()),args.evidence_directory)
        if args.command == 'v19-init':
            from .portfolio.upgrade import enable_v19
            return enable_v19(ledger,args.config)
        if args.command == 'mapped-import':
            from .portfolio.mapping import mapped_import
            return mapped_import(ledger,args.account_id,args.file.read_bytes(),json.loads(args.mapping.read_text()),args.as_of or now_utc(),
                commit=args.commit,expected_sequence=args.expected_sequence,expected_hash=args.expected_hash)
        if args.command == "v18-init":
            from .strategies.store import enable_v18
            return enable_v18(ledger, args.config)
        if args.command in {"data-series", "data-bind", "data-status"}:
            from .data.catalog import DataCatalog
            catalog = DataCatalog(ledger)
            if args.command == "data-bind":
                return catalog.bind(args.role, args.identity, expected_revision=args.expected_revision)
            return catalog.refresh() if args.command == "data-series" else catalog.list()
        if args.command == "workbench-init":
            from .strategies.store import enable_workbench
            return enable_workbench(ledger, args.config)
        if args.command == "strategies":
            from .strategies.store import StrategyStore
            from .strategies.spec import StrategySpec
            from .strategies.registry import definitions
            library = StrategyStore(ledger)
            if args.file:
                return {"status": "SUCCESS", "spec": library.publish(StrategySpec.load(args.file)).export()}
            return {"templates": [item.content() for item in definitions().values()], "versions": library.list()}
        if args.command == "import-factors":
            from .data.factors import FactorStore
            if config.environment == "real" and set(pd.read_csv(args.file).data_type) != {"real_factors"}:
                raise QuantError("ENVIRONMENT_MISMATCH", "真实目录不能导入合成因子")
            return FactorStore(root / "factors").save(pd.read_csv(args.file), json.loads(args.metadata.read_text()))
        if args.command == "strategy-bind":
            from .strategies.bindings import BindingService
            _, _, calendar = store.load_role("signal")
            return BindingService(ledger, config).request(args.account_id, args.strategy_id, args.revision, calendar,
                as_of=args.as_of, effective_session=args.effective_session,
                expected_binding_seq=args.expected_binding_seq, expected_account_seq=args.expected_account_seq)
        if args.command == "monthly-decision":
            from .strategies.bindings import BindingService
            from .strategies.spec import DataBundle
            return BindingService(ledger, config).decide(args.account_id, DataBundle(**json.loads(args.bundle.read_text())),
                args.session, as_of=args.as_of)
        if args.command == "compare":
            from .research.compare import compare_runs
            return compare_runs(root / "reports/research", args.runs, ledger=ledger)[0]
        if args.command in {"research", "research-worker", "research-status", "research-recover"}:
            from .research.service import ResearchService
            from .research.experiments import ResearchSpec
            from .strategies.store import StrategyStore
            research = ResearchService(ledger)
            if args.command == "research-status":
                return {"attempts": research.list()}
            if args.command == "research-recover":
                return research.recover()
            if args.command == "research-worker":
                return research.run(args.attempt_id)
            spec = ResearchSpec.load_request(args.experiment, config, StrategyStore(ledger))
            attempt = research.submit(spec, rerun=args.rerun)
            if args.background:
                return research.launch(attempt["attempt_id"])
            if attempt["status"] == "CREATED":
                return research.run(attempt["attempt_id"])
            return attempt
        service = PlanService(ledger, config)
        if args.command=='hedge-exposure':
            from .hedging.service import exposure
            if args.archive:
                from .hedging.archive import publish
                return publish(ledger,config,store,args.account_id,json.loads(args.file.read_text()))
            return exposure(ledger,config,store,args.account_id,json.loads(args.file.read_text()))
        if args.command=='hedge-preview':
            from .hedging.preview import preview
            return preview(ledger,args.account_id,json.loads(args.file.read_text()))
        if args.command=='hedge-stress':
            from .hedging.stress import analyze
            return analyze(ledger,args.account_id,json.loads(args.file.read_text()))
        if args.command=='hedge-coverage':
            from .hedging.coverage_service import account_coverage
            return account_coverage(ledger,args.account_id,json.loads(args.file.read_text()))
        if args.command=='security-register':
            from .hedging.securities import normalize,register
            body=normalize(json.loads(args.file.read_text()))
            if not args.commit:return {'status':'DRAFT','version_hash':digest(body),'identity':body,'executable':False}
            return {'status':'REGISTERED',**register(ledger.path.parent,ledger.environment,body),'executable':False}
        if args.command=='security-assess':
            from .hedging.securities import assess
            return assess(ledger,args.account_id,json.loads(args.file.read_text()))
        if args.command=='hedge-allocation':
            from .hedging.allocation_store import update
            return update(ledger,args.account_id,json.loads(args.file.read_text()),commit=args.commit)
        if args.command=='hedge-allocation-basis':
            from .hedging.allocation_store import current_basis
            return current_basis(ledger,args.account_id)
        if args.command=='hedge-intent':
            from .hedging.intents import save
            return save(ledger,args.account_id,json.loads(args.file.read_text()),commit=args.commit)
        if args.command=='hedge-intents':
            from .hedging.intents import records
            from .hedging.intent_actions import history as intent_history
            heads={}
            for row in records(ledger,args.account_id):
                if row['hedge_id'] not in heads or row['revision']>heads[row['hedge_id']]['revision']:heads[row['hedge_id']]=row
            return {'status':'ARCHIVED','intents':[heads[k] for k in sorted(heads)],'closures':intent_history(ledger,args.account_id),'executable':False,
                    'meaning':'原父研究决定最新修订；不宣称现时账户/报价或执行资格'}
        if args.command=='hedge-intent-close':
            from .hedging.intent_actions import save
            return save(ledger,args.account_id,json.loads(args.file.read_text()),commit=args.commit)
        if args.command=='hedge-stock-draft':
            from .hedging.stock_plans import save
            return save(ledger,config,args.account_id,json.loads(args.file.read_text()),commit=args.commit)
        if args.command=='hedge-stock-activate':
            from .hedging.stock_activation import save
            return save(ledger,args.account_id,json.loads(args.file.read_text()),commit=args.commit)
        if args.command=='hedge-stock-reprice':
            from .hedging.stock_repricing import save
            return save(ledger,config,args.account_id,json.loads(args.file.read_text()),commit=args.commit)
        if args.command=='hedge-stock-unit-rebase':
            from .hedging.stock_repricing import save
            return save(ledger,config,args.account_id,json.loads(args.file.read_text()),commit=args.commit,unit_mode=True)
        if args.command=='hedge-native-plans':
            from .hedging.native_plans import save
            return save(ledger,args.account_id,json.loads(args.file.read_text()),commit=args.commit)
        if args.command=='hedge-group':
            from .hedging.groups import save
            return save(ledger,args.account_id,json.loads(args.file.read_text()),commit=args.commit)
        if args.command=='hedge-stage-check':
            from .hedging.stage_assessment import analyze
            return analyze(ledger,args.account_id,json.loads(args.file.read_text()))
        if args.command=='hedge-groups':
            from .hedging.groups import history as group_history,progress
            from .hedging.group_revisions import heads
            groups=group_history(ledger,args.account_id)
            return {'status':'ARCHIVED','groups':groups,'progress':[
                progress(ledger,args.account_id,g,args.as_of,ledger_seq=args.ledger_seq) for g in heads(groups,args.as_of,args.ledger_seq)],
                'executable':False}
        if args.command=='hedge-group-revise':
            from .hedging.group_revisions import save
            return save(ledger,args.account_id,json.loads(args.file.read_text()),commit=args.commit)
        if args.command=='hedge-status':
            from .hedging.monitor import monitor
            return monitor(ledger,args.account_id,args.as_of)
        if args.command=='option-incident-review':
            from .options.incidents import save
            return save(ledger,args.account_id,json.loads(args.file.read_text()),args.evidence_directory,commit=args.commit)
        if args.command == "daily":
            if bool(args.fetch_start) != bool(args.fetch_end):
                raise QuantError("INVALID_INTERVAL", "daily 下载必须同时提供 --fetch-start 和 --fetch-end")
            return DailyRunner(ledger, config, store).run(args.account_id, as_of=args.as_of,
                fetch_range=(args.fetch_start, args.fetch_end) if args.fetch_start else None,
                events=read_events(args.events) if args.events else None,
                expected_sequence=args.expected_sequence, expected_hash=args.expected_hash,
                coverage_through=args.coverage_through, coverage_source=args.coverage_source,
                actions=action_csv(args.actions.read_bytes()) if args.actions else None,
                reconciliation=read_snapshot(args.reconciliation) if args.reconciliation else None,
                option_valuation=json.loads(args.option_valuation.read_text()) if args.option_valuation else None,
                option_tasks=json.loads(args.option_tasks.read_text()) if args.option_tasks else None,
                option_receipts=json.loads(args.option_receipts.read_text()) if args.option_receipts else None,
                option_resolutions=json.loads(args.option_resolutions.read_text()) if args.option_resolutions else None,
                hedge_stage_checks=json.loads(args.hedge_stage_checks.read_text()) if args.hedge_stage_checks else None)
        if args.command == "list-signals":
            return {"environment": config.environment, "signals": SignalArchive(ledger).list(mode=args.mode, limit=args.limit)}
        if args.command == "account":
            ledger.account(args.account_id)
            return ledger.snapshot(args.account_id, now_utc())
        if args.command == "status":
            data = json.loads((root / "data/latest.json").read_text()) if (root / "data/latest.json").exists() else None
            return {"environment": config.environment, "data": data,
                    "tasks": [dict(row) for row in ledger.connection.execute("""
                        SELECT task_id,status,updated_at,json_extract(details,'$.command') AS command,
                          COALESCE(json_extract(details,'$.code'),json_extract(details,'$.result.code')) AS code,
                          COALESCE(json_extract(details,'$.message'),json_extract(details,'$.result.message')) AS message
                        FROM tasks ORDER BY updated_at DESC LIMIT 20
                    """)],
                    "plans": [dict(row) for row in ledger.connection.execute("SELECT plan_id,execution_status,check_status FROM plans")],
                    "imports": [dict(row) for row in ledger.connection.execute("SELECT status,details,recorded_at FROM imports ORDER BY id DESC LIMIT 10")],
                    "reconciliations": [dict(row) for row in ledger.connection.execute("SELECT status,as_of,details FROM reconciliations ORDER BY id DESC LIMIT 5")],
                    "database_schema": ledger.schema_info,
                    "daily_attempts": [dict(row) for row in ledger.connection.execute("SELECT * FROM daily_attempts ORDER BY started_at DESC LIMIT 10")]}
        if args.command == "backup":
            ledger.backup(args.destination)
            return {"backup": str(args.destination)}
        if args.command == "manage-plan":
            if args.action == "submitted":
                service.manual_pending(args.plan_id, True, args.as_of if config.environment == "demo" else None)
            elif args.action == "confirmed-no-pending":
                service.manual_pending(args.plan_id, False, args.as_of if config.environment == "demo" else None)
            elif args.action == "cancel":
                service.cancel(args.plan_id)
            else:
                return service.refresh(args.plan_id, args.as_of or now_utc())
            return service.get(args.plan_id)
        if args.command == "import-events":
            rows = read_events(args.file)
            as_of = args.as_of or now_utc()
            prices = references(store.load_role("valuation")[0], as_of) if (root / "data/latest.json").exists() else {}
            if not args.commit:
                return ledger.preview(args.account_id, rows, as_of, prices)
            if args.expected_sequence is None or args.expected_hash != digest(rows):
                raise QuantError("PREVIEW_REQUIRED", "提交必须提供预检返回的 --expected-sequence 和 --expected-hash")
            from .options.receipts import import_statement
            result = import_statement(ledger,args.account_id,rows,args.expected_sequence,as_of,
                                      coverage_through=args.coverage_through,coverage_source=args.coverage_source)
            return result
        as_of = getattr(args, "as_of", None) or now_utc()
        if args.command == "reconcile":
            expected = read_snapshot(args.file)
            prices = references(store.load_role("valuation")[0], expected["as_of"]) if (root / "data/latest.json").exists() else {}
            return ledger.reconcile(args.account_id, expected, prices, rules=ReconciliationRules.from_config(config))
        if args.command == "simulate-actions":
            return apply_actions(ledger, args.account_id, action_csv(args.file.read_bytes()), args.as_of)
        if args.command == "report":
            return report_from_store(ledger, args.account_id, as_of, store, config, root / "reports/account-latest")
        frame, metadata, calendar = store.load_role("execution")
        option_valuation=json.loads(args.option_valuation.read_text()) if getattr(args,'option_valuation',None) else None
        if args.command == "revise-plan":
            if config.environment != "demo" and args.as_of:
                raise QuantError("HISTORICAL_TIME_FORBIDDEN", "真实/前向计划修订不能使用手工历史时钟")
            return service.revise(args.plan_id, frame, metadata, calendar, as_of,option_valuation=option_valuation)
        if args.command == "plan":
            if config.environment != "demo" and args.as_of:
                raise QuantError("HISTORICAL_TIME_FORBIDDEN", "真实/前向账户不能使用手工历史时钟")
            if args.revise:
                previous = ledger.connection.execute("SELECT plan_id FROM plans WHERE account_id=? AND json_extract(payload,'$.signal.decision_session')=? ORDER BY rowid DESC LIMIT 1",
                                                       (args.account_id, args.session)).fetchone()
                if not previous:
                    raise QuantError("UNKNOWN_PLAN", "修订需要同一账户已存在的月度意图")
                return service.revise(previous[0], frame, metadata, calendar, as_of,option_valuation=option_valuation)
            if ledger.connection.execute("SELECT version FROM schema_version").fetchone()[0] >= 3 and ledger.connection.execute(
                    "SELECT 1 FROM strategy_bindings WHERE account_id=?", (args.account_id,)).fetchone():
                from .strategies.bindings import BindingService
                from .strategies.spec import DataBundle
                factor_latest = root / "factors/latest.json"
                factor_id = json.loads(factor_latest.read_text())["snapshot_id"] if factor_latest.exists() else None
                from .data.selection import bundle_for
                bundle = bundle_for(store)
                return BindingService(ledger, config).decide(args.account_id, bundle, args.session,
                    as_of=as_of if config.environment == "demo" else None,option_valuation=option_valuation)
            signal_frame, signal_meta, signal_calendar = store.load_role("signal")
            record = SignalArchive(ledger).generate(signal_frame, signal_meta, signal_calendar, config, args.session,
                                                    decision_time=as_of if config.environment == "demo" else None,
                                                    account_state=ledger.snapshot(args.account_id, as_of))
            value = decode_signal(record["signal"])
            return service.create(args.account_id, value, frame, metadata, calendar, as_of, revise=args.revise,option_valuation=option_valuation)
        if args.command == "simulate":
            if config.environment != "demo" and args.as_of:
                raise QuantError("HISTORICAL_TIME_FORBIDDEN", "前向模拟不能手工指定处理时钟")
            return simulate(service, args.plan_id, frame, calendar, as_of,state_as_of=args.state_as_of,option_valuation=option_valuation,hedge_stage_check=json.loads(args.hedge_stage_check.read_text()) if args.hedge_stage_check else None)
        raise QuantError("UNKNOWN_COMMAND", "未知命令")
    finally:
        ledger.close()


def main(argv=None):
    args = parser().parse_args(argv)
    config = None
    try:
        if args.command=='input-package':
            from .workspace import packages,scenarios
            if args.action=='verify':
                if not args.source:raise QuantError('SOURCE_REQUIRED','需要--source输入包')
                result={'status':'VERIFIED','manifest':packages.verify(args.source),'executable':False}
            else:
                if not args.file or not args.destination:raise QuantError('REQUEST_REQUIRED','需要--file参数和新的--destination')
                spec=json.loads(args.file.read_text())
                result=scenarios.generate(spec,args.destination) if args.action=='scenario' else packages.assemble(spec,args.destination) if args.action=='assemble' else packages.import_prices(spec,args.destination)
            print(canonical(result));return 0
        if args.command=='experiment':
            from .workspace import experiments,service
            from .workspace import experiment_index
            if args.action=='compare':
                if not args.file:raise QuantError('FILE_REQUIRED','比较需要实验清单JSON')
                result=experiments.compare(json.loads(args.file.read_text()))
            elif args.action in {'compare-export','compare-verify','compare-restore'}:
                from .workspace import comparison_package
                if args.action=='compare-export':
                    if not args.file or not args.destination:raise QuantError('EXPORT_REQUIRED','比较导出需要清单JSON及新destination')
                    result=comparison_package.export(json.loads(args.file.read_text()),args.destination)
                elif args.action=='compare-verify':
                    if not args.source:raise QuantError('SOURCE_REQUIRED','比较校验需要source目录')
                    checked=comparison_package.verify(args.source)
                    result={'status':checked['status'],'package_id':checked['manifest']['package_id'],'read_only':True}
                else:
                    if not args.source or not args.destination:raise QuantError('RESTORE_REQUIRED','比较恢复需要source及新destination')
                    result=comparison_package.restore(args.source,args.destination)
            elif args.action=='list' and args.file:
                result=experiment_index.index(json.loads(args.file.read_text()))
            else:
                if not args.workspace:raise QuantError('WORKSPACE_REQUIRED','需要明确工作区')
                if args.action=='clone':
                    if not args.destination:raise QuantError('DESTINATION_REQUIRED','复制需要新目录')
                    result=experiments.clone(args.workspace,args.destination)
                elif args.action=='annotate':
                    if not args.file:raise QuantError('FILE_REQUIRED','批注需要run_id、request_id、note的JSON')
                    result=experiment_index.annotate(args.workspace,json.loads(args.file.read_text()))
                elif args.action=='export':
                    if not args.destination or not args.run_id:raise QuantError('EXPORT_REQUIRED','导出需要run-id及新destination')
                    result=experiment_index.export(args.workspace,args.run_id,args.destination)
                else:result=service.status(args.workspace)
            print(canonical(result));return 0
        if args.command in {'workspace','simulation'} or (args.command=='ui' and args.workspace):
            from .workspace import service
            if args.command=='workspace':
                if args.action=='init':
                    if not args.spec:raise QuantError('SPEC_REQUIRED','初始化需要明确模拟规格--spec')
                    result=service.create(args.workspace,json.loads(args.spec.read_text()),Config.load(args.config))
                elif args.action=='task-index':
                    from .workspace.job_index import rebuild
                    result=rebuild(args.workspace)
                elif args.action=='task-files':
                    from .workspace.jobs import inventory
                    result=inventory(args.workspace)
                elif args.action=='task-retry':
                    if not args.file or not args.job_id or not args.request_id:raise QuantError('REQUEST_REQUIRED','重试需要--job-id、--file文件指纹和稳定--request-id')
                    from .workspace.jobs import retry
                    result=retry(args.workspace,args.job_id,files_hash=json.loads(args.file.read_text())['files_hash'],request_id=args.request_id)
                elif args.action=='schedule-preview':
                    if not args.file:raise QuantError('REQUEST_REQUIRED','调度预检需--file明确预算/运行')
                    from .workspace.schedule import preview
                    result=preview(args.workspace,json.loads(args.file.read_text()))
                elif args.action=='operation':
                    if not args.file or not args.request_id:raise QuantError('REQUEST_REQUIRED','维护任务需要--file和稳定--request-id')
                    from .workspace.operations import submit
                    result=submit(args.workspace,json.loads(args.file.read_text()),request_id=args.request_id,max_seconds=args.max_seconds)
                elif args.action=='allocation-preview':
                    if not args.file:raise QuantError('REQUEST_REQUIRED','需要--file显式预算预演请求')
                    from .workspace.capital import preview
                    result=preview(args.workspace,json.loads(args.file.read_text()))
                elif args.action=='tasks':
                    from .workspace.jobs import list_jobs
                    result={'tasks':list_jobs(args.workspace,limit=args.limit,offset=args.offset),'read_only':True}
                elif args.action=='task-review':
                    if not args.file or not args.job_id:raise QuantError('REQUEST_REQUIRED','需要--job-id及--file核对请求')
                    from .workspace.jobs import review
                    result=review(args.workspace,args.job_id,json.loads(args.file.read_text()))
                elif args.action=='inputs':
                    if not args.run_id:raise QuantError('RUN_REQUIRED','需要明确run-id')
                    root,identity,config,_=service.read_workspace(args.workspace)
                    if identity['kind']=='etf':
                        from .workspace.inputs import require
                        book=Ledger.read_only(root/config.runtime_dir/'account.sqlite','demo')
                        try:result=require(book,DataStore(root/config.runtime_dir/'data'),args.run_id)
                        finally:book.close()
                    else:
                        path=root/config.runtime_dir/'simulation/options'/args.run_id/'settings.json'
                        if len(args.run_id)!=64 or any(c not in '0123456789abcdef' for c in args.run_id):raise QuantError('RUN_REQUIRED','无效run-id')
                        result=json.loads(path.read_text())
                elif args.action=='diagnostic':
                    if not args.destination:raise QuantError('DESTINATION_REQUIRED','诊断导出需要新的--destination')
                    from .workspace.diagnostic import export
                    result=export(args.workspace,args.destination)
                elif args.action in {'backup-review','recovery-drill'}:
                    if not args.source or (args.action=='recovery-drill' and not args.destination):
                        raise QuantError('BACKUP_ARGUMENT_REQUIRED','需要--source；恢复演练还需要新的--destination')
                    if args.action=='backup-review' and args.destination:
                        raise QuantError('UNUSED_DESTINATION','仅核验不接受恢复目标，请使用recovery-drill')
                    from .workspace.maintenance import verify
                    result=verify(args.workspace,args.source,destination=args.destination)
                else:result=service.status(args.workspace)
            elif args.command=='simulation':
                kwargs=dict(input_file=args.file,engine_root=args.engine_root,dotnet=args.dotnet,fee_per_contract=args.fee_per_contract,
                    max_sessions=args.max_sessions,max_seconds=args.max_seconds,min_free_bytes=args.min_free_bytes)
                if args.background:
                    from .workspace.jobs import launch
                    result=launch(args.workspace,args.action,args.run_id,args.through,request_id=args.request_id,**kwargs)
                else:
                    if args.request_id:raise QuantError('BACKGROUND_REQUIRED','稳定任务请求ID用于--background')
                    result=service.worker(args.workspace,args.action,args.run_id,args.through,**kwargs)
            else:return service.launch_ui(args.workspace,args.port)
            print(canonical(result));return 0
        # Recovery must not create, migrate or log into the source account.
        if args.command in {"backup-bundle", "verify-backup", "restore", 'backup-maintenance'}:
            if args.command == 'backup-maintenance':
                from .portfolio.maintenance import inventory, retention_preview, managed_backup
                if args.action == 'list': result = {'inventory': inventory(args.directory,args.environment), 'read_only': True}
                elif args.action == 'preview': result = retention_preview(args.directory,args.environment,args.keep,args.protect)
                else:
                    settings = Config.load(args.config)
                    if settings.environment != args.environment: raise QuantError('ENVIRONMENT_MISMATCH','备份环境与配置不同')
                    result = managed_backup(Path(settings.runtime_dir),args.config,args.directory,
                        keep=args.keep,protected_ids=args.protect,min_free_bytes=args.min_free_bytes)
            elif args.command == "backup-bundle":
                settings = Config.load(args.config)
                result = create_bundle(Path(settings.runtime_dir), Path(args.config), args.destination)
            elif args.command == "restore":
                result = restore_bundle(args.source, args.destination, args.environment)
            else:
                manifest = verify_bundle(args.source, args.environment)
                result = {"status": "SUCCESS", "backup_id": manifest["backup_id"],
                          "environment": args.environment, "files": len(manifest["files"])}
            print(canonical(result))
            return 0
        config = Config.load(args.config)
        managed=Path(config.runtime_dir)/'simulation/workspace.json'
        if managed.exists() and args.command in {'signals','plan','revise-plan','monthly-decision','daily'}:
            if json.loads(managed.read_text()).get('kind')=='options':
                raise QuantError('WORKSPACE_MODE_CONFLICT','期权工作区通过simulation推进；ETF日常/计划参数未在此工作区启用')
        result = execute(args, config)
        if isinstance(result, int):
            return result
        if args.command=='hedge-catalog':
            print(canonical(result))
            return 0
        if args.command in {"status","doctor","research-package","execution-review",'options','paper-summary','hedge-exposure','hedge-preview','hedge-stress','hedge-coverage','hedge-allocation','hedge-allocation-basis','hedge-intent','hedge-intents','hedge-intent-close','hedge-group','hedge-groups','hedge-status','hedge-group-revise','hedge-stage-check','hedge-native-plans','hedge-stock-draft','hedge-stock-activate','hedge-stock-reprice','hedge-stock-unit-rebase','security-assess','option-incident-review'}:
            # Diagnostic reads must not recursively persist their own task list.
            print(canonical(result))
            return 0
        blocked = result.get("check_status") == "BLOCKED" or result.get("status") in {"DIFFERENCES", "BLOCKED"}
        status = "BLOCKED" if blocked else result.get("status", "SUCCESS")
        if status == "PASSED":
            status = "SUCCESS"
        book = Ledger(Path(config.runtime_dir) / "account.sqlite", config.environment)
        try:
            key = digest({"command": args.command, "config": config.hash, "arguments": vars(args)})
            book.record_task(key, status, {"command": args.command, "result": result})
        finally:
            book.close()
        print(canonical(result))
        if blocked:
            return 3
        if status == "FAILED":
            return 2
        return 0
    except (QuantError, OSError, ValueError, sqlite3.Error) as exc:
        code = getattr(exc, "code", "IO_OR_CONFIG_ERROR")
        waiting = code == "NO_COMPLETED_DATA"
        error = {"status": "WAITING" if waiting else "FAILED", "code": code, "message": str(exc)}
        if config and args.command not in {'hedge-exposure','hedge-preview','hedge-stress','hedge-coverage','hedge-allocation','hedge-allocation-basis','hedge-intent','hedge-intents','hedge-intent-close','hedge-group','hedge-groups','hedge-status','hedge-group-revise','hedge-stage-check','hedge-native-plans','hedge-stock-draft','hedge-stock-activate','hedge-stock-reprice','hedge-stock-unit-rebase','security-assess','option-incident-review'}:
            try:
                book = Ledger(Path(config.runtime_dir) / "account.sqlite", config.environment)
                try:
                    book.record_task(digest({"command": args.command, "config": config.hash, "arguments": vars(args)}), error["status"], {"command": args.command, **error})
                finally:
                    book.close()
            except (QuantError, OSError, sqlite3.Error) as log_error:
                error["task_log_error"] = {"code": getattr(log_error, "code", "DATABASE_LOG_FAILED"), "message": str(log_error)}
        if waiting and "task_log_error" not in error:
            print(canonical(error))
            return 0
        print(canonical(error), file=sys.stderr)
        return 3 if code.startswith("MISSING_") or code in {"DOWNLOAD_FAILED", "CORRUPT_SNAPSHOT"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
