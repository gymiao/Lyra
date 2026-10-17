"""Verified local recovery bundles. No account facts are inferred or overwritten."""
from __future__ import annotations

from contextlib import closing, contextmanager, nullcontext
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import sys
from uuid import uuid4

from ..common import QuantError, digest, now_utc, write_json
from ..locks import publication_lock
from ..config import Config
from ..data.store import DataStore
from ..execution.daily import daily_lock
from ..strategies.archive import SignalArchive, source_fingerprint
from .ledger import Ledger
from .report import load_account_report
from .schema import CURRENT_VERSION, _version

FORMAT = 1
CONFIG_FILE = "configs/recovered.toml"


def _hash(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _relative(value):
    if not isinstance(value, str) or not value or "\\" in value:
        raise QuantError("INVALID_BACKUP_PATH", "备份路径必须是安全的相对路径")
    path = PurePosixPath(value)
    if path.is_absolute() or str(path) != value or any(part in {".", ".."} for part in path.parts):
        raise QuantError("INVALID_BACKUP_PATH", "备份路径不能跨出恢复目录")
    return Path(*path.parts)


def _files(root):
    """Only inspect a known bundle/runtime tree; never follow symbolic links."""
    result = {}
    for parent, directories, names in os.walk(root, followlinks=False):
        directories[:] = sorted(directories)
        for name in directories + names:
            item = Path(parent) / name
            if item.is_symlink():
                raise QuantError("UNSAFE_BACKUP_FILE", "备份及恢复不接受符号链接")
        for name in sorted(names):
            item = Path(parent) / name
            if not item.is_file():
                raise QuantError("UNSAFE_BACKUP_FILE", "备份只接受普通文件")
            result[item.relative_to(root).as_posix()] = {"sha256": _hash(item), "bytes": item.stat().st_size}
    return result


def _runtime_files(root):
    result = {}
    registered = None
    database = root / "account.sqlite"
    if database.exists():
        with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
            if connection.execute("SELECT 1 FROM sqlite_master WHERE name='research_attempts'").fetchone():
                registered = {row[0] for row in connection.execute("SELECT run_id FROM research_attempts WHERE status='SUCCESS'")}
    for name in ("data", "factors", "drafts", "reports", "fixtures", "source-archives", 'options','qualifications','hedging','simulation'):
        directory = root / name
        if directory.is_symlink():
            raise QuantError("UNSAFE_BACKUP_FILE", "运行目录不能通过符号链接引用外部数据")
        if not directory.exists():
            continue
        for relative, value in _files(directory).items():
            # Unpublished crash leftovers are diagnostics, never successful inputs.
            if any(part.startswith(".pending-") or ".tmp-" in part or part.startswith(".account-")
                   for part in Path(relative).parts):
                continue
            parts = Path(relative).parts
            if name == "data" and parts[0] == "provider-cache":
                continue  # Discardable supplier caches are not versioned research inputs.
            if name == "reports" and len(parts) >= 3 and parts[0] == "research" and registered is not None:
                manifest_file = directory / parts[0] / parts[1] / "manifest.json"
                if manifest_file.exists() and json.loads(manifest_file.read_text()).get("schema_version") == 2 and parts[1] not in registered:
                    continue
            result[f"{name}/{relative}"] = value
    signals = root / "signals.json"
    if signals.is_symlink():
        raise QuantError("UNSAFE_BACKUP_FILE", "信号导出不能是符号链接")
    if signals.exists():
        result["signals.json"] = {"sha256": _hash(signals), "bytes": signals.stat().st_size}
    return result


@contextmanager
def _book(path, environment):
    if path.is_symlink() or not path.is_file():
        raise QuantError("INVALID_BACKUP_DATABASE", "备份需要已有的普通账户数据库文件")
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, isolation_level=None)
    connection.row_factory = sqlite3.Row
    try:
        version = _version(connection)
        if version not in {2, 3, 4, CURRENT_VERSION}:
            raise QuantError("BACKUP_SCHEMA_MISMATCH", "请先完成并验证数据库升级，再创建完整备份")
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or connection.execute("PRAGMA foreign_key_check").fetchone():
            raise QuantError("INVALID_BACKUP_DATABASE", "账户数据库完整性或外键检查失败")
        if {row[0] for row in connection.execute("SELECT DISTINCT environment FROM accounts")} - {environment}:
            raise QuantError("ENVIRONMENT_MISMATCH", "备份账户属于另一运行环境")
        # Reuse read-only domain methods without running schema migrations.
        ledger = Ledger.__new__(Ledger)
        ledger.path, ledger.environment, ledger.connection = path, environment, connection
        ledger._savepoint_sequence = 0
        yield ledger
    finally:
        connection.close()


def _database_info(book, as_of):
    tables = sorted(row[0] for row in book.connection.execute("SELECT name FROM sqlite_master WHERE type='table'"))
    rows = {name: sorted((dict(row) for row in book.connection.execute('SELECT * FROM "' + name.replace('"', '""') + '"')),
                         key=digest) for name in tables}
    return {"version": _version(book.connection), "logical_hash": digest(rows),
            "table_counts": {name: len(values) for name, values in rows.items()},
            "accounts": {row["id"]: book.snapshot(row["id"], as_of) for row in rows["accounts"]}}


def _snapshot_refs(value):
    if isinstance(value, dict):
        if "factors.parquet" in value.get("files", {}):
            return
        if 'monthly_signal_id' in value and 'selection' in value and 'input' in value:
            return  # Frozen option-monthly chain references are validated separately.
        if value.get('mark_basis')=='bid_ask_mid_per_quote_unit':
            return  # Option account valuations are checked against option snapshots.
        if value.get('artifact_type') in {'option_simulation_audit','option_simulation_failure',
                                         'option_receipt_batch','option_receipt_progress'}:
            return  # Native option audits own their exact quote/engine references.
        for key, item in value.items():
            if key=='option_valuation_request':
                continue  # Explicit option input, never a stock-price snapshot reference.
            if key=='snapshot_id' and ('selection' in value or ('template_id' in value and 'decision_hash' in value)
                    or ('selection_request' in value and 'coverage_request' in value)):
                continue  # Option-chain identities have their own validator below.
            if key in {"snapshot_id", "reference_snapshot_id", "signal_snapshot_id", "execution_snapshot_id"} and item is not None:
                yield item
            else:
                yield from _snapshot_refs(item)
    elif isinstance(value, list):
        for item in value:
            yield from _snapshot_refs(item)


def _factor_refs(value):
    if isinstance(value, dict):
        if "factors.parquet" in value.get("files", {}) and value.get("snapshot_id"):
            yield value["snapshot_id"]
        for key, item in value.items():
            if key == "factor_snapshot_id" and item:
                yield item
            else:
                yield from _factor_refs(item)
    elif isinstance(value, list):
        for item in value:
            yield from _factor_refs(item)


def _validate_references(root, book):
    from ..hedging.archive import validate_references as validate_exposures
    validate_exposures(root,book)
    from ..hedging.securities import catalog
    catalog(root,book.environment)
    from ..hedging.allocation_store import validate_references as validate_allocations
    validate_allocations(root,book)
    from ..hedging.intents import validate_references as validate_intents
    validate_intents(root,book)
    from ..hedging.native_plans import validate_references as validate_native_plans
    validate_native_plans(book)
    from ..hedging.stock_plans import validate_references as validate_hedge_stock
    validate_hedge_stock(book)
    from ..hedging.stock_activation import validate_references as validate_hedge_stock_activation
    validate_hedge_stock_activation(book)
    from ..hedging.stock_simulation_audit import validate_references as validate_hedge_stock_simulation
    validate_hedge_stock_simulation(book)
    data_root = root / "data"
    snapshots = set()
    if data_root.exists():
        store = DataStore(data_root)
        for directory in data_root.iterdir():
            if directory.is_dir():
                if directory.name == "provider-cache" or directory.name.startswith(".pending-"):
                    continue
                store.load(directory.name)
                snapshots.add(directory.name)
        if (data_root / "latest.json").exists():
            store.load()
    needed = set()
    for table, columns in (("strategy_signals", ["payload"]), ("plans", ["payload"]),
                           ("tasks", ["details"]), ("daily_steps", ["output"]), ("daily_attempts", ["details"])):
        query=f"SELECT {','.join(columns)} FROM {table}"
        if table=='tasks':query+=" WHERE task_id NOT LIKE 'option-simulation:%' AND task_id NOT LIKE 'option-exit-%'"
        for row in book.connection.execute(query):
            needed.update(_snapshot_refs(json.loads(row[0])))
    factors, needed_factors = set(), set()
    if _version(book.connection) >= 3:
        from ..data.factors import FactorStore
        from ..research.experiments import ResearchSpec
        from ..research.service import ResearchService
        from ..strategies.store import StrategyStore
        StrategyStore(book).list()
        from ..strategies.drafts import DraftStore
        DraftStore(root / "drafts").list()
        for row in book.connection.execute("SELECT attempt_id FROM research_attempts WHERE status='SUCCESS'"):
            ResearchService(book)._report(row[0])
        factor_root = root / "factors"
        if factor_root.exists():
            factor_store = FactorStore(factor_root)
            for item in factor_root.iterdir():
                if item.is_dir():
                    if item.name.startswith(".pending-"):
                        continue
                    factor_store.load(item.name)
                    factors.add(item.name)
            if (factor_root / "latest.json").exists():
                factor_store.load()
        for row in book.connection.execute("SELECT experiment_hash,payload FROM research_experiments"):
            spec = ResearchSpec.from_dict(json.loads(row["payload"]))
            if spec.experiment_hash != row["experiment_hash"]:
                raise QuantError("CORRUPT_EXPERIMENT", "备份实验身份不一致")
            body = spec.content()
            needed.update(_snapshot_refs(body))
            if body["data_bundle"]["factor_snapshot_id"]:
                needed_factors.add(body["data_bundle"]["factor_snapshot_id"])
        for row in book.connection.execute("SELECT payload FROM strategy_signals"):
            body = json.loads(row[0])
            factor_id = body.get("signal", {}).get("data_bundle", {}).get("factor_snapshot_id")
            if factor_id:
                needed_factors.add(factor_id)
        for table, column in (("tasks", "details"), ("monthly_decisions", "payload"), ("plans", "payload")):
            for row in book.connection.execute(f"SELECT {column} FROM {table}"):
                needed_factors.update(_factor_refs(json.loads(row[0])))
        for row in book.connection.execute("SELECT * FROM strategy_bindings"):
            if StrategyStore(book).get(row["strategy_id"], row["revision"]).spec_hash != row["spec_hash"]:
                raise QuantError("CORRUPT_BINDING", "备份绑定规格不匹配")
    if _version(book.connection) >= 4:
        for row in book.connection.execute('SELECT snapshot_id,metadata FROM data_publications'):
            (needed_factors if 'metadata' in json.loads(row[1]) else needed).add(row[0])
        for row in book.connection.execute('SELECT head_snapshot_id,metadata FROM data_series'):
            (needed_factors if 'metadata' in json.loads(row[1]) else needed).add(row[0])
        # Verify bound roles resolve in this copied environment, never another cwd.
        from ..data.selection import selected
        for row in book.connection.execute('SELECT role FROM data_roles'):
            if row[0]=='factor':
                from ..data.selection import factor_snapshot
                factor_snapshot(DataStore(root/'data'))
            else:selected(DataStore(root / 'data'), row[0],check_qualification=False)
        for table in ('validation_protocols','validation_suites','validation_items'):
            for row in book.connection.execute(f'SELECT payload FROM {table}'):
                body=json.loads(row[0]);needed.update(_snapshot_refs(body));needed_factors.update(_factor_refs(body))
        from ..research.artifacts import verify_source
        source_root=root/'source-archives'
        if source_root.exists():
            for item in source_root.iterdir():
                if item.is_dir() and not item.name.startswith('.pending-'):verify_source(item,item.name)
        for row in book.connection.execute("SELECT task_id,details FROM tasks WHERE task_id LIKE 'simulation-source:%'"):
            body=json.loads(row['details'])
            if row['task_id']!='simulation-source:'+body['run_id']:
                raise QuantError('CORRUPT_SOURCE','模拟源码审计身份不一致')
            run=book.connection.execute('SELECT source_hash FROM simulation_runs WHERE run_id=?',(body['run_id'],)).fetchone()
            if run is None or run['source_hash']!=body['source_hash']:
                raise QuantError('CORRUPT_SOURCE','模拟源码审计缺少原运行')
            from ..workspace.source_archive import require
            require(book,root,body['run_id'],body['source_hash'],check_environment=False)
        for row in book.connection.execute("SELECT task_id,details FROM tasks WHERE task_id LIKE 'simulation-tools:%'"):
            body=json.loads(row['details']);identity=body['run_id']
            if row['task_id']!='simulation-tools:'+identity:
                raise QuantError('CORRUPT_SIMULATION_TOOLS','外部工具绑定任务身份不一致')
            directory=root/'simulation/options'/identity
            from ..workspace.portable_tools import archived
            _,manifest=archived(book,directory,identity)
            settings=json.loads((directory/'settings.json').read_text())
            if settings.get('tool_identity_hash')!=manifest['content_hash']:
                raise QuantError('CORRUPT_SIMULATION_TOOLS','外部工具绑定缺少原始设置依据')
        from ..workspace.option_setup import load as load_option_setup
        for file in (root/'simulation/setups').glob('*/setup-manifest.json'):
            setup=load_option_setup(file.parent)
            if setup['setup_id']!=file.parent.name:raise QuantError('CORRUPT_OPTION_SETUP','备份配置目录与身份不一致')
    archive = SignalArchive(book)
    for row in book.connection.execute("SELECT archive_id FROM strategy_signals"):
        archive.get(row[0])
    for row in book.connection.execute("SELECT payload FROM plans"):
        body = json.loads(row[0])
        if body.get("signal_archive_id"):
            archive.get(body["signal_archive_id"])
    reports = root / "reports"
    for manifest_path in reports.rglob("manifest.json") if reports.exists() else []:
        manifest = json.loads(manifest_path.read_text())
        if manifest.get("schema_version") == 2:
            row = book.connection.execute("SELECT status FROM research_attempts WHERE run_id=?", (manifest["run_id"],)).fetchone()
            if not row or row[0] != "SUCCESS":
                raise QuantError("UNPUBLISHED_RESEARCH", "备份不能包含尚未成功注册的研究报告")
        needed.update(_snapshot_refs(manifest))
        for name, expected in manifest["files"].items():
            file = manifest_path.parent / _relative(name)
            if not file.is_file() or _hash(file) != expected:
                raise QuantError("CORRUPT_REPORT", "备份报告清单与文件不一致")
    for latest in reports.rglob("latest.json") if reports.exists() else []:
        pointer = json.loads(latest.read_text())
        if "report_id" in pointer:
            load_account_report(latest.parent)
        elif "run_id" in pointer:
            directory = latest.parent / _relative(pointer["run_id"])
            if not (directory / "manifest.json").is_file():
                raise QuantError("CORRUPT_REPORT", "研究报告引用的运行不存在")
    for report in reports.rglob("account.json") if reports.exists() else []:
        needed.update(_snapshot_refs(json.loads(report.read_text())))
    if needed - snapshots:
        raise QuantError("MISSING_BACKUP_REFERENCE", f"备份缺少引用的行情快照：{sorted(needed - snapshots)}")
    if needed_factors - factors:
        raise QuantError("MISSING_BACKUP_REFERENCE", "备份缺少引用的因子快照")
    result = {"snapshots": sorted(snapshots), "referenced_snapshots": sorted(needed)}
    chains=root/'options/chains';option_snapshots=set()
    chain_roots=[chains] if chains.exists() else []
    for candidate in sorted(root.glob('simulation/options/*/plan-chains')):
        run=candidate.parent
        if len(run.name)!=64 or any(c not in '0123456789abcdef' for c in run.name):continue
        policy=json.loads((run/'plan-policy.json').read_text());settings=json.loads((run/'settings.json').read_text())
        if digest(policy)!=settings.get('plan_policy_hash'):
            raise QuantError('CORRUPT_OPTION_AUDIT','模拟运行的冻结计划政策改变')
        chain_roots.append(candidate)
    for chain_root in chain_roots:
        from ..options.data import OptionDataStore
        store=OptionDataStore(chain_root)
        for item in chain_root.iterdir():
            if item.is_dir() and not item.name.startswith('.'):
                store.load(item.name);option_snapshots.add(item.name)
        result['option_snapshots']=sorted(option_snapshots)
    monthly=root/'options/monthly';monthly_refs=set()
    if monthly.exists():
        from ..options.monthly import validate_frozen
        for file in monthly.glob('*.json'):
            body=validate_frozen(json.loads(file.read_text()),file.stem)
            monthly_refs.add(body['input']['snapshot_id'])
        if monthly_refs-option_snapshots:
            raise QuantError('MISSING_BACKUP_REFERENCE','备份缺少冻结月度信号引用的合约/报价快照')
        result['monthly_option_signals']=sorted(file.stem for file in monthly.glob('*.json'))
        result['monthly_option_snapshot_refs']=sorted(monthly_refs)
    forward_monthly=root/'options/monthly-forward';forward_refs=set()
    if forward_monthly.exists():
        from ..options.forward import validate_forward,verify_snapshot
        from ..options.source import assess_source
        from ..options.data import OptionDataStore
        chain_store=OptionDataStore(chains)
        for file in forward_monthly.glob('*.json'):
            signal=validate_forward(json.loads(file.read_text()),file.stem)
            if signal['environment']!=book.environment:
                raise QuantError('CORRUPT_FORWARD_SIGNAL','前向信号账户环境与备份不同')
            metadata=verify_snapshot(chain_store,signal)
            contracts,_,_,_=chain_store.load(signal['input']['snapshot_id'])
            selected=[contracts[leg['contract']['contract_id']] for leg in signal['selection']['legs']]
            if assess_source(book,metadata,selected,signal['decision_at'])!=signal['source_assessment']:
                raise QuantError('CORRUPT_FORWARD_SIGNAL','前向信号来源资格与已登记凭据不一致')
            forward_refs.add(signal['input']['snapshot_id'])
        if forward_refs-option_snapshots:
            raise QuantError('MISSING_BACKUP_REFERENCE','备份缺少前向信号引用的期权链')
        result['forward_option_signals']=sorted(file.stem for file in forward_monthly.glob('*.json'))
        result['forward_option_snapshot_refs']=sorted(forward_refs)
    monthly_reports=root/'options/monthly-research';research_refs=set()
    if monthly_reports.exists():
        from ..options.monthly_report import load_monthly_report
        for file in monthly_reports.glob('*/report.json'):
            body=load_monthly_report(file.parent);research_refs.update(body['snapshot_ids'])
        if research_refs-option_snapshots:
            raise QuantError('MISSING_BACKUP_REFERENCE','备份缺少月度期权研究引用的合约/报价链')
        result['monthly_option_research_refs']=sorted(research_refs)
    if _version(book.connection)>=5:
        from ..options.contracts import OptionContract
        registry={}
        for row in book.connection.execute('SELECT * FROM option_contracts'):
            contract=OptionContract.from_dict(json.loads(row['payload']))
            if contract.version_hash!=row['version_hash'] or contract.contract_id!=row['contract_id']:
                raise QuantError('CORRUPT_OPTION_CONTRACT','备份合约身份或单位版本不一致')
            if book.environment=='real':
                from ..options.ledger import verify_contract_evidence
                verify_contract_evidence(root,contract)
            registry[contract.version_hash]=contract
        for row in book.connection.execute('SELECT payload,content_hash FROM events'):
            event=json.loads(row['payload'])
            if event['kind'].startswith('OPTION_'):
                version=event['contract_version']
                if digest(event)!=row['content_hash'] or version not in registry or OptionContract.from_dict(event['contract']).version_hash!=version:
                    raise QuantError('MISSING_BACKUP_REFERENCE','期权事实缺少确切的合约单位凭据或哈希不一致')
        needed_options=set()
        from ..options.incidents import reviews as incident_reviews
        for account in book.connection.execute('SELECT id FROM accounts'):
            incident_reviews(book,account['id'])
        def option_marks(value):
            if isinstance(value,dict):
                if value.get('mark_basis')=='bid_ask_mid_per_quote_unit' and value.get('snapshot_id'):
                    yield value['snapshot_id']
                for item in value.values():yield from option_marks(item)
            elif isinstance(value,list):
                for item in value:yield from option_marks(item)
        for file in reports.rglob('account.json') if reports.exists() else []:
            needed_options.update(option_marks(json.loads(file.read_text())))
        for table,column in (('daily_steps','output'),('tasks','details'),('plans','payload')):
            for row in book.connection.execute(f'SELECT {column} FROM {table}'):
                needed_options.update(option_marks(json.loads(row[0])))
        for row in book.connection.execute('SELECT output FROM daily_steps'):
            output=json.loads(row[0])
            if output.get('artifact_type')=='option_receipt_progress':
                for audit in output['audits']:
                    native=book.connection.execute('SELECT details FROM tasks WHERE task_id=?',(audit['audit_task_id'],)).fetchone()
                    if not native or digest(json.loads(native[0]))!=digest(audit):
                        raise QuantError('CORRUPT_OPTION_AUDIT','日常凭据步骤与原子导入审计不一致')
            if output.get('artifact_type')=='option_simulation_audit':
                native=book.connection.execute('SELECT details FROM tasks WHERE task_id=?',(output['audit_task_id'],)).fetchone()
                if not native or digest(json.loads(native[0]))!=digest(output['audit']):
                    raise QuantError('CORRUPT_OPTION_AUDIT','日常成交步骤与原子期权成交审计不一致')
        for row in book.connection.execute("SELECT task_id,details FROM tasks WHERE task_id LIKE 'option-receipt-batch:%'"):
            audit=json.loads(row['details']);request=audit['request']
            identity='option-receipt-batch:'+digest({'account_id':audit['account_id'],'request_id':request['request_id']})
            if (row['task_id']!=identity or audit['audit_task_id']!=identity or audit['request_hash']!=digest(request)
                    or request['expected_hash']!=digest(request['rows'])):
                raise QuantError('CORRUPT_OPTION_AUDIT','凭据批次身份或原始预检哈希不一致')
            if 'risk_history' in audit:
                from ..options.receipt_risk import validate
                validate(book,audit['account_id'],audit['risk_history'])
        for row in book.connection.execute("SELECT task_id,details FROM tasks WHERE task_id LIKE 'option-resolution:%'"):
            audit=json.loads(row['details'])
            identity='option-resolution:'+digest({'account_id':audit['account_id'],'event_id':audit['event_id'],
                                                  'receipt_hash':audit['receipt_hash']})
            if row['task_id']!=identity or digest(audit['receipt'])!=audit['receipt_hash']:
                raise QuantError('CORRUPT_OPTION_AUDIT','期权解决凭据身份或哈希改变')
            if 'risk_history' in audit:
                from ..options.receipt_risk import validate
                validate(book,audit['account_id'],audit['risk_history'])
        for row in book.connection.execute("SELECT task_id,details FROM tasks WHERE task_id LIKE 'option-exit-freeze:%'"):
            audit=json.loads(row['details']);request=audit['request'];proposal=audit['proposal']
            if proposal.get('hedge_stage_check'):
                from ..hedging.stage_gate import validate_record
                validate_record(book,proposal['account_id'],proposal['plan_id'],'CLOSE',request.get('hedge_stage_check'),proposal['hedge_stage_check'])
            identity=digest({'plan_id':request['review']['plan_id'],'request_id':request['request_id']})
            if (audit['request_hash']!=digest(request) or proposal['request_hash']!=digest(request)
                or row['task_id']!='option-exit-freeze:'+identity or proposal['exit_id']!=identity
                or proposal['preview_hash']!=digest({k:v for k,v in proposal.items() if k!='preview_hash'})):
                raise QuantError('CORRUPT_OPTION_AUDIT','退出冻结身份、请求或预检哈希改变')
            needed_options.add(request['review']['snapshot_id'])
        for row in book.connection.execute("SELECT task_id,details FROM tasks WHERE task_id LIKE 'option-exit-prefix-progress:%'"):
            identity=row['task_id'].removeprefix('option-exit-prefix-progress:')
            frozen=book.connection.execute('SELECT details FROM tasks WHERE task_id=?',('option-exit-freeze:'+identity,)).fetchone()
            if not frozen:raise QuantError('CORRUPT_OPTION_AUDIT','部分退出缺少冻结依据')
            from ..workspace.exit_backup import validate_progress
            validate_progress(root,book,json.loads(row['details']),json.loads(frozen[0])['proposal'])
        for row in book.connection.execute("SELECT task_id,details FROM tasks WHERE task_id LIKE 'option-exit-simulation:%'"):
            audit=json.loads(row['details']);request=audit['request']
            if audit.get('hedge_stage_check'):
                from ..hedging.stage_gate import validate_record
                native_id=audit['result']['plan_id']
                owner=book.connection.execute('SELECT account_id FROM option_plans WHERE plan_id=?',(native_id,)).fetchone()
                if owner is None:raise QuantError('CORRUPT_HEDGE_STAGE_AUDIT','原期权计划丢失')
                validate_record(book,owner[0],native_id,'CLOSE',request.get('hedge_stage_check'),audit['hedge_stage_check'])
            if audit['request_hash']!=digest(request) or row['task_id']!='option-exit-simulation:'+request['exit_id']:
                raise QuantError('CORRUPT_OPTION_AUDIT','退出模拟任务身份或请求哈希改变')
            frozen=book.connection.execute('SELECT details FROM tasks WHERE task_id=?',('option-exit-freeze:'+request['exit_id'],)).fetchone()
            if not frozen or digest(json.loads(frozen[0])['proposal'])!=audit['proposal_hash']:
                raise QuantError('CORRUPT_OPTION_AUDIT','退出缺少原始冻结依据')
            if request.get('adapter')=='verified_native_prefix':
                from ..workspace.exit_backup import validate
                validate(root,book,audit,json.loads(frozen[0])['proposal'])
                continue
            needed_options.add(request['execution_snapshot_id'])
            from ..options.monthly_report import load_monthly_report
            report=load_monthly_report(root/_relative('options/monthly-research/'+request['report_id']))
            if digest(report)!=audit['report_hash']:raise QuantError('CORRUPT_OPTION_AUDIT','退出引用的引擎报告改变')
            for event in audit['rows']:
                stored=book.connection.execute('SELECT payload FROM events WHERE account_id=? AND event_id=?',(audit['account_id'],event['event_id'])).fetchone()
                if not stored or any(json.loads(stored[0]).get(key)!=value for key,value in event.items()):
                    raise QuantError('CORRUPT_OPTION_AUDIT','退出审计与实际账本不一致')
        for row in book.connection.execute("SELECT task_id,details FROM tasks WHERE task_id LIKE 'option-exit-cancel:%'"):
            audit=json.loads(row['details']);request=audit['request']
            if (audit['request_hash']!=digest(request) or row['task_id']!='option-exit-cancel:'+request['exit_id']
                or not book.connection.execute('SELECT 1 FROM tasks WHERE task_id=?',('option-exit-freeze:'+request['exit_id'],)).fetchone()):
                raise QuantError('CORRUPT_OPTION_AUDIT','退出取消任务身份或冻结引用改变')
        for row in book.connection.execute("SELECT task_id,details FROM tasks WHERE task_id LIKE 'option-simulation:%'"):
            audit=json.loads(row['details']);request=audit['request']
            if audit.get('hedge_stage_check'):
                from ..hedging.stage_gate import validate_record
                native_id=request['plan_id']
                owner=book.connection.execute('SELECT account_id FROM option_plans WHERE plan_id=?',(native_id,)).fetchone()
                if owner is None:raise QuantError('CORRUPT_HEDGE_STAGE_AUDIT','原期权计划丢失')
                validate_record(book,owner[0],native_id,'OPEN',request.get('hedge_stage_check'),audit['hedge_stage_check'])
            if audit['request_hash']!=digest(request) or row['task_id']!='option-simulation:'+digest({'plan_id':request['plan_id']}):
                raise QuantError('CORRUPT_OPTION_AUDIT','模拟任务身份或请求哈希改变')
            needed_options.add(request['execution_snapshot_id'])
            from ..options.monthly_report import load_monthly_report
            report=load_monthly_report(root/_relative('options/monthly-research/'+request['report_id']))
            if digest(report)!=audit['report_hash']:raise QuantError('CORRUPT_OPTION_AUDIT','模拟任务引用的月度报告改变')
            for event in audit['rows']:
                stored=book.connection.execute('SELECT payload FROM events WHERE account_id=? AND event_id=?',(audit['result']['account_id'],event['event_id'])).fetchone()
                if not stored or any(json.loads(stored[0]).get(key)!=value for key,value in event.items()):
                    raise QuantError('CORRUPT_OPTION_AUDIT','模拟成交审计与实际账本不一致')
        for row in book.connection.execute("SELECT task_id,details FROM tasks WHERE task_id LIKE 'option-activation:%'"):
            audit=json.loads(row['details']);request=audit['request']
            if audit.get('hedge_stage_check'):
                from ..hedging.stage_gate import validate_record
                native_id=request['plan_id']
                owner=book.connection.execute('SELECT account_id FROM option_plans WHERE plan_id=?',(native_id,)).fetchone()
                if owner is None:raise QuantError('CORRUPT_HEDGE_STAGE_AUDIT','原期权计划丢失')
                validate_record(book,owner[0],native_id,'OPEN',request.get('hedge_stage_check'),audit['hedge_stage_check'])
            if audit['request_hash']!=digest(request) or row['task_id']!='option-activation:'+digest({'plan_id':request['plan_id'],'request_id':request['request_id']}):
                raise QuantError('CORRUPT_OPTION_AUDIT','期权激活审计身份或请求哈希不一致')
            if book.environment=='demo':
                from ..options.monthly import validate_frozen
                validate_frozen(request['monthly_signal'])
            else:
                from ..options.forward import validate_forward
                try:
                    signal=validate_forward(request['monthly_signal'])
                except QuantError:
                    from ..options.monthly import validate_frozen
                    validate_frozen(request['monthly_signal'])
                    if audit['status']=='ACTIVATED':
                        raise QuantError('CORRUPT_OPTION_AUDIT','非demo激活不能引用历史重建信号')
                else:
                    if audit['status']=='ACTIVATED':
                        path=root/'options/monthly-forward'/(signal['monthly_signal_id']+'.json')
                        if validate_forward(json.loads(path.read_text()),signal['monthly_signal_id'])!=signal:
                            raise QuantError('CORRUPT_OPTION_AUDIT','已激活前向信号与冻结归档不同')
                        owner=book.connection.execute('SELECT account_id,payload FROM option_plans WHERE plan_id=?',
                            (request['plan_id'],)).fetchone()
                        if owner is None or signal['account_id']!=owner['account_id'] or signal['environment']!=book.environment:
                            raise QuantError('CORRUPT_OPTION_AUDIT','已激活前向信号与账户/计划不同')
                        if audit['result']['activation']['data_type'] not in {'forward_paper','real_account_manual_plan'}:
                            raise QuantError('CORRUPT_OPTION_AUDIT','前向计划不能标记为历史合成演示')
            needed_options.update([request['quote_snapshot_id'],request['monthly_signal']['input']['snapshot_id']])
            if audit['status']=='ACTIVATED':
                identity=audit['result']['activation']['engine_evidence_id']
                directory=root/_relative('options/engine-evidence/'+identity)
                proof=json.loads((directory/'verification.json').read_text())
                if digest(proof)!=identity or identity!=audit['engine_assessment']['evidence_hash']:
                    raise QuantError('CORRUPT_OPTION_AUDIT','激活引擎证据身份不一致')
                if _hash(directory/'adapter-bin/LyraX.Options.dll')!=proof['adapter_dll_sha256']:
                    raise QuantError('CORRUPT_OPTION_AUDIT','归档引擎程序集改变')
                for name,expected in proof['adapter_source'].items():
                    if _hash(directory/'adapter-source'/_relative(name))!=expected:raise QuantError('CORRUPT_OPTION_AUDIT','归档适配源码改变')
                for name,case in proof['cases'].items():
                    case_dir=directory/_relative(name);manifest=json.loads((case_dir/'data-files.json').read_text())
                    if digest(manifest)!=case['data_manifest_hash']:raise QuantError('CORRUPT_OPTION_AUDIT','执行数据清单改变')
                    data=case_dir/'data' if (case_dir/'data').is_dir() else directory/'data'
                    for relative,expected in manifest.items():
                        if _hash(data/_relative(relative))!=expected:raise QuantError('CORRUPT_OPTION_AUDIT','激活执行数据改变')
        for row in book.connection.execute("SELECT task_id,details FROM tasks WHERE task_id LIKE 'option-manual:%'"):
            audit=json.loads(row['details']);request=audit['request'];plan=audit['result']
            if audit['request_hash']!=digest(request) or row['task_id']!='option-manual:'+digest({'plan_id':request['plan_id'],'request_id':request['request_id']}):
                raise QuantError('CORRUPT_OPTION_AUDIT','人工期权审计身份或请求哈希不一致')
            needed_options.add(plan['snapshot_id'])
        for row in book.connection.execute('SELECT payload FROM option_plans'):
            body=json.loads(row[0]);needed_options.add(body['snapshot_id'])
            if body['selection']['snapshot_id']!=body['snapshot_id']:
                raise QuantError('MISSING_BACKUP_REFERENCE','期权草案与冻结选约快照不一致')
        if needed_options-option_snapshots:
            raise QuantError('MISSING_BACKUP_REFERENCE','备份缺少期权草案引用的合约/报价快照')
        if needed_options:result['referenced_option_snapshots']=sorted(needed_options)
        for row in book.connection.execute('SELECT qualification_id,payload FROM source_qualifications'):
            body=json.loads(row['payload']);identity=row['qualification_id']
            if digest(body)!=identity:raise QuantError('CORRUPT_SOURCE_EVIDENCE','来源资格记录哈希改变')
            directory=root/'qualifications'/identity
            if not (directory/'qualification.json').is_file() or json.loads((directory/'qualification.json').read_text())!=body:
                raise QuantError('MISSING_BACKUP_REFERENCE','备份缺少来源资格归档')
            for name,expected in body['evidence_files'].items():
                file=directory/_relative(name)
                if not file.is_file() or _hash(file)!=expected:
                    raise QuantError('CORRUPT_SOURCE_EVIDENCE','备份来源核验凭据缺失或哈希改变')
    if _version(book.connection) >= 3:
        result.update(factor_snapshots=sorted(factors), referenced_factor_snapshots=sorted(needed_factors))
    return result


def verify_bundle(source: Path, environment: str):
    source = Path(source)
    if source.is_symlink() or not source.is_dir():
        raise QuantError("INVALID_BACKUP", "完整备份必须是普通目录")
    try:
        manifest = json.loads((source / "manifest.json").read_text())
        if manifest["format_version"] != FORMAT or manifest["status"] != "COMPLETE":
            raise QuantError("UNSUPPORTED_BACKUP", "未知或未完成的备份格式，不恢复")
        if manifest["environment"] != environment:
            raise QuantError("ENVIRONMENT_MISMATCH", "必须显式使用与备份相同的环境")
        if manifest["manifest_hash"] != digest({k: v for k, v in manifest.items() if k != "manifest_hash"}):
            raise QuantError("CORRUPT_BACKUP", "备份清单哈希不匹配")
        expected = manifest["files"]
        for name in expected:
            _relative(name)
        actual = _files(source)
        actual.pop("manifest.json", None)
        if actual != expected:
            raise QuantError("CORRUPT_BACKUP", "备份文件缺失、出现额外文件或内容哈希不匹配")
        if manifest["runtime_path"] != f"runtime/{environment}" or manifest["config_path"] != CONFIG_FILE:
            raise QuantError("INVALID_BACKUP_PATH", "备份运行路径与环境不匹配")
        config = Config.load(source / CONFIG_FILE)
        if config.environment != environment or config.hash != manifest["config_hash"]:
            raise QuantError("ENVIRONMENT_MISMATCH", "备份配置与清单不匹配")
        root = source / manifest["runtime_path"]
        with _book(root / "account.sqlite", environment) as book:
            info = _database_info(book, manifest["as_of"])
            if info != manifest["database"]:
                raise QuantError("CORRUPT_BACKUP", "备份数据库事实与独立清单不一致")
            if _validate_references(root, book) != manifest["references"]:
                raise QuantError("MISSING_BACKUP_REFERENCE", "备份引用闭合检查不一致")
        return manifest
    except (OSError, sqlite3.Error, KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, QuantError):
            raise
        raise QuantError("CORRUPT_BACKUP", "备份不完整或结构无效，未恢复任何账户") from exc


def _empty_destination(destination):
    if destination.is_symlink() or (destination.exists() and (not destination.is_dir() or any(destination.iterdir()))):
        raise QuantError("NONEMPTY_DESTINATION", "目标必须不存在或为空目录，不覆盖已有文件")


def create_bundle(runtime: Path, config_path: Path, destination: Path, *, _already_locked=False):
    runtime, config_path, destination = Path(runtime), Path(config_path), Path(destination)
    config = Config.load(config_path)
    if runtime.resolve() != Path(config.runtime_dir).resolve():
        raise QuantError("ENVIRONMENT_MISMATCH", "备份路径不是配置指定的账户运行目录")
    if runtime.resolve().is_relative_to(destination.resolve()) or destination.resolve().is_relative_to(runtime.resolve()):
        raise QuantError("INVALID_BACKUP", "备份目录必须位于账户运行目录之外且不包含该目录")
    _empty_destination(destination)
    original_config = config_path.read_bytes()
    destination.parent.mkdir(parents=True, exist_ok=True)
    pending = destination.with_name(".pending-backup-" + uuid4().hex)
    pending.mkdir()
    try:
        with (nullcontext() if _already_locked else daily_lock(runtime / ".daily.lock")), publication_lock(runtime), _book(runtime / "account.sqlite", config.environment) as observer:
            # The observer detects all other connections' commits, including CLI/UI.
            before_version = observer.connection.execute("PRAGMA data_version").fetchone()[0]
            before = _runtime_files(runtime)
            copied_root = pending / config.runtime_dir
            copied_root.mkdir(parents=True)
            # sqlite3's transaction context does not close the handle. WSL's
            # Windows-mounted directories cannot publish with this handle open.
            with closing(sqlite3.connect(copied_root / "account.sqlite")) as output:
                observer.connection.backup(output)
            for name in before:
                target = copied_root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(runtime / name, target)
            target_config = pending / CONFIG_FILE
            target_config.parent.mkdir(parents=True)
            target_config.write_bytes(original_config)
            if (_runtime_files(runtime) != before or config_path.read_bytes() != original_config or
                    observer.connection.execute("PRAGMA data_version").fetchone()[0] != before_version or
                    _runtime_files(copied_root) != before):
                raise QuantError("BACKUP_SOURCE_CHANGED", "备份期间账户/行情/报告/配置改变，未发布备份，请稍后重试")
        as_of = now_utc()
        with _book(copied_root / "account.sqlite", config.environment) as book:
            database = _database_info(book, as_of)
            references = _validate_references(copied_root, book)
        dependencies = {}
        for name in ("bt", "ffn", "pandas", "numpy", "pyarrow", "streamlit", "yfinance", "exchange-calendars", "pyxirr"):
            try:
                dependencies[name] = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                dependencies[name] = None
        manifest = {"format_version": FORMAT, "status": "COMPLETE", "backup_id": uuid4().hex,
                    "environment": config.environment, "as_of": as_of, "created_at": now_utc(),
                    "runtime_path": config.runtime_dir, "config_path": CONFIG_FILE, "config_hash": config.hash,
                    "source_hash": source_fingerprint(), "python": sys.version.split()[0], "dependencies": dependencies,
                    "database": database, "references": references, "files": _files(pending),
                    "scope": "runtime published data/reports/fixtures, event facts and config; external receipts and secrets excluded"}
        manifest["manifest_hash"] = digest(manifest)
        write_json(pending / "manifest.json", manifest)
        verify_bundle(pending, config.environment)
        _empty_destination(destination)
        os.rename(pending, destination)
        return {"status": "SUCCESS", "backup": str(destination), "backup_id": manifest["backup_id"],
                "environment": config.environment, "files": len(manifest["files"]), "database": database}
    finally:
        if pending.exists():
            shutil.rmtree(pending)


def restore_bundle(source: Path, destination: Path, environment: str):
    source, destination = Path(source), Path(destination)
    _empty_destination(destination)
    if source.resolve().is_relative_to(destination.resolve()) or destination.resolve().is_relative_to(source.resolve()):
        raise QuantError("INVALID_BACKUP", "恢复目录必须位于备份目录之外且不包含它")
    manifest = verify_bundle(source, environment)
    destination.parent.mkdir(parents=True, exist_ok=True)
    pending = destination.with_name(".pending-restore-" + uuid4().hex)
    pending.mkdir()
    try:
        for name in manifest["files"]:
            target = pending / _relative(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / _relative(name), target)
        write_json(pending / "manifest.json", manifest)
        verified = verify_bundle(pending, environment)  # Detect source changes during copying too.
        _empty_destination(destination)
        os.rename(pending, destination)
        return {"status": "SUCCESS", "restored": str(destination), "backup_id": verified["backup_id"],
                "environment": environment, "config": str(destination / CONFIG_FILE), "database": verified["database"]}
    finally:
        if pending.exists():
            shutil.rmtree(pending)
