"""Read-only diagnostics and explicit local notice synchronization."""
import importlib.metadata
import json
from pathlib import Path
import sqlite3
import pandas as pd
from .common import QuantError, digest, canonical, now_utc, utc
from .data.store import DataStore
from .data.quotes import quote_set


def doctor(config,as_of=None, *, verify_reports=False):
    clock=as_of or now_utc();root=Path(config.runtime_dir);checks=[];bound_specs=[]
    workspace_kind=None
    if (root/'simulation/workspace.json').exists():
        try:
            from .workspace.service import read_workspace
            directory,identity,saved,_=read_workspace(root.absolute().parents[1])
            if saved.hash!=config.hash or not (directory/saved.runtime_dir).samefile(root):
                raise QuantError('WORKSPACE_CONFIG_CHANGED','诊断配置与工作区不一致')
            workspace_kind=identity['kind']
        except (QuantError,OSError,ValueError,KeyError,TypeError) as exc:
            checks.append({'kind':'workspace','id':'identity','status':'BLOCKED','reason':str(exc)})
    for name in ['bt','ffn','pandas','numpy','pyarrow','streamlit','exchange-calendars']:
        try:checks.append({'kind':'dependency','id':name,'status':'PASSED','version':importlib.metadata.version(name)})
        except importlib.metadata.PackageNotFoundError:checks.append({'kind':'dependency','id':name,'status':'FAILED'})
    try:
        config.require_execution();checks.append({'kind':'configuration','id':'execution','status':'PASSED'})
    except QuantError as exc:checks.append({'kind':'configuration','id':'execution','status':'BLOCKED','reason':str(exc)})
    database=root/'account.sqlite';accounts=[];version=None
    if database.is_file():
        connection=sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True);connection.row_factory=sqlite3.Row
        try:
            version=connection.execute('SELECT version FROM schema_version').fetchone()[0]
            checks.append({'kind':'database','id':'schema','status':'PASSED' if version in {2,3,4,5} else 'BLOCKED','version':version})
            accounts=[dict(r) for r in connection.execute('SELECT * FROM accounts')]
            if version>=3 and verify_reports:
                from .portfolio.ledger import Ledger
                from .research.service import ResearchService
                book=Ledger.__new__(Ledger);book.path=database;book.environment=config.environment;book.connection=connection
                for result in connection.execute("SELECT attempt_id FROM research_attempts WHERE status='SUCCESS'").fetchall():
                    try:ResearchService(book)._report(result[0])
                    except (QuantError,OSError,ValueError) as exc:checks.append({'kind':'report','id':result[0],'status':'BLOCKED','reason':str(exc)})
            if version>=3:
                from .strategies.spec import StrategySpec
                # Future bindings are not evidence of the currently effective rule.
                for row in connection.execute("SELECT b.* FROM strategy_bindings b WHERE b.status IN ('PENDING','ACTIVE','RETIRED','BLOCKED') ORDER BY effective_session DESC,binding_seq DESC"):
                    bound_specs.append(dict(row))
                for binding in bound_specs:
                    row=connection.execute('SELECT payload FROM strategy_versions WHERE strategy_id=? AND revision=?',
                        (binding['strategy_id'],binding['revision'])).fetchone()
                    binding['spec']=StrategySpec.from_dict(json.loads(row[0])) if row else None
            for row in connection.execute("SELECT plan_id,check_status,manual_pending FROM plans WHERE (check_status='BLOCKED' AND execution_status IN ('DRAFT','READY','PARTIAL')) OR manual_pending=1"):
                checks.append({'kind':'plan','id':row['plan_id'],'status':'BLOCKED','reason':'检查受阻或人工订单在途'})
            for row in connection.execute("SELECT id,status,as_of FROM reconciliations ORDER BY id DESC LIMIT 1"):
                if row['status']=='DIFFERENCES':checks.append({'kind':'reconciliation','id':str(row['id']),'status':'BLOCKED','reason':'未解决对账差异'})
            for row in connection.execute("SELECT a.run_id,a.attempt_id,a.details FROM daily_attempts a WHERE a.status='FAILED' AND NOT EXISTS (SELECT 1 FROM daily_attempts newer WHERE newer.run_id=a.run_id AND newer.status IN ('FAILED','SUCCESS','NO_ACTION') AND (newer.started_at>a.started_at OR (newer.started_at=a.started_at AND newer.rowid>a.rowid))) ORDER BY a.started_at DESC"):
                checks.append({'kind':'task','id':row['run_id'],'attempt_id':row['attempt_id'],'status':'WARNING','reason':json.loads(row['details'])})
        finally:connection.close()
    else:checks.append({'kind':'database','id':'missing','status':'UNINITIALIZED','reason':'尚未建立工作区，诊断未创建数据库'})
    if workspace_kind=='options':
        checks.extend({'kind':'data','id':role,'status':'NOT_REQUIRED',
                       'reason':'当前期权模拟使用冻结请求，未使用ETF用途；期权输入/来源由执行前独立检查'}
                      for role in ['signal','execution','valuation'])
    elif (root/'data').exists():
        store=DataStore(root/'data')
        for role in ['signal','execution','valuation']:
            try:
                frame,meta,calendar=store.load_role(role)
                reference=calendar.latest_completed(clock,config.publication_delay_minutes)
                complete=all(not frame.loc[(frame.symbol==s)&(frame.session_date==reference)&(frame.available_at<=pd.Timestamp(utc(clock)))].empty for s in config.symbols)
                from .data.quality import price_quality
                quality=price_quality(frame,calendar,config,config.symbols,reference,clock,adjusted=role=='signal',require_previous=True)
                complete=complete and quality['status']=='PASSED'
                if role=='signal':
                    from .data.readiness import history_readiness
                    from .strategies.spec import StrategySpec
                    selected={}
                    for binding in bound_specs:
                        if binding['effective_session']<=str(reference.date()):
                            selected.setdefault(binding['account_id'],binding)
                    if selected:
                        for account,binding in selected.items():
                            spec=binding['spec']
                            if spec is None:
                                checks.append({'kind':'history','id':account,'status':'BLOCKED','reason':'绑定规格缺失'})
                            else:
                                checks.append({'kind':'history','id':account,'spec_hash':spec.spec_hash,
                                    **history_readiness(frame,calendar,spec.symbols,reference,clock,spec.required_prices)})
                    else:
                        spec=StrategySpec.from_dict(config.strategy_spec) if config.strategy_spec else None
                        checks.append({'kind':'history','id':'strategy_lookback',
                            **history_readiness(frame,calendar,spec.symbols if spec else config.symbols,reference,clock,spec.required_prices if spec else config.lookback)})
                checks.append({'kind':'data','id':role,'status':'PASSED' if complete else 'BLOCKED','snapshot_id':meta['snapshot_id'],
                    'source':meta['source'],'data_type':meta['data_type'],'data_as_of':meta['end'],'expected_session':str(reference.date()),'price_basis':meta['price_basis'],'quality':quality})
            except (QuantError,ValueError,OSError,KeyError) as exc:checks.append({'kind':'data','id':role,'status':'BLOCKED','reason':str(exc),'code':getattr(exc,'code','INVALID_DATA')})
    else:checks.append({'kind':'data','id':'missing','status':'UNINITIALIZED','reason':'尚无数据，诊断不下载或修复'})
    checks.append({'kind':'schedule','id':'installation','status':'UNVERIFIED','reason':'未核验调度安装及长期运行证据'})
    return {'status':'BLOCKED' if any(c['status'] in {'FAILED','BLOCKED'} for c in checks) else 'UNINITIALIZED' if any(c['status']=='UNINITIALIZED' for c in checks) else 'READY_FOR_REVIEW',
            'as_of':clock,'environment':config.environment,'workspace_kind':workspace_kind,'schema_version':version,'accounts':accounts,'checks':checks,'read_only':True,
            'report_integrity': 'CHECKED' if verify_reports else 'NOT_CHECKED'}


def display_checks(diagnostic):
    """Stable strings for Arrow tables; preserve typed values in the API response."""
    return [{key: canonical(value) if isinstance(value,(dict,list)) else '' if value is None else str(value)
             for key,value in check.items()} for check in diagnostic['checks']]


def sync_notices(ledger,diagnostic):
    if ledger.connection.execute('SELECT version FROM schema_version').fetchone()[0]<4:
        raise QuantError('V18_NOT_ENABLED','本地待办需要v1.8')
    active=set();clock=now_utc()
    with ledger.transaction():
        for check in diagnostic['checks']:
            if check['status'] not in {'FAILED','BLOCKED','WARNING'}:continue
            identity=digest({'environment':ledger.environment,'kind':check['kind'],'id':check['id']});active.add(identity)
            ledger.connection.execute("INSERT INTO local_notices VALUES(?,?,?,?,?,?,?) ON CONFLICT(notice_id) DO UPDATE SET status='OPEN',payload=excluded.payload,last_seen=excluded.last_seen,acknowledged_at=CASE WHEN local_notices.status='RESOLVED' THEN NULL ELSE local_notices.acknowledged_at END",
                (identity,check['kind'],'OPEN',canonical(check),clock,clock,None))
        for row in ledger.connection.execute("SELECT notice_id FROM local_notices WHERE status='OPEN'").fetchall():
            if row[0] not in active:ledger.connection.execute("UPDATE local_notices SET status='RESOLVED',last_seen=? WHERE notice_id=?",(clock,row[0]))
    return notices(ledger)


def notices(ledger):
    return [dict(r) for r in ledger.connection.execute('SELECT * FROM local_notices ORDER BY last_seen DESC')]


def acknowledge(ledger,identity):
    with ledger.transaction():
        if not ledger.connection.execute('SELECT 1 FROM local_notices WHERE notice_id=?',(identity,)).fetchone():raise QuantError('UNKNOWN_NOTICE','待办不存在')
        ledger.connection.execute('UPDATE local_notices SET acknowledged_at=? WHERE notice_id=?',(now_utc(),identity))
    return notices(ledger)
