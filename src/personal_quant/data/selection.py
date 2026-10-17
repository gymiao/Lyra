"""One purpose-aware price selection boundary for CLI, daily workflow and UI."""
import json
from pathlib import Path
import sqlite3
from ..common import QuantError


def selected(store, role='signal', *, check_qualification=True):
    if role not in {'signal', 'execution', 'valuation'}:
        raise QuantError('INVALID_DATA_ROLE', '未知价格用途')
    database = store.root.parent / 'account.sqlite'
    if database.exists():
        connection = sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)
        try:
            version = connection.execute('SELECT version FROM schema_version').fetchone()[0]
            if version >= 4:
                frozen = getattr(store, 'frozen_inputs', None)
                if frozen is not None:
                    environments = {r[0] for r in connection.execute('SELECT DISTINCT environment FROM accounts')}
                    if environments != {'demo'} or frozen.get('run_mode') != 'frozen_replay':
                        raise QuantError('DEMO_ONLY', '冻结历史输入仅用于明确的demo回放')
                    ref = frozen['roles'][role]
                    frame, metadata, calendar = store.load(ref['snapshot_id'])
                    if calendar.hash != ref['calendar_hash']:
                        raise QuantError('CALENDAR_CONFLICT', '冻结用途日历已变化')
                    if role != 'signal' and set(metadata['price_basis']) != {'unadjusted'}:
                        raise QuantError('UNQUALIFIED_EXECUTION_PRICE', '执行/估值用途必须是核验原价')
                    return frame, metadata, calendar
                row = connection.execute('SELECT series_id FROM data_roles WHERE role=?', (role,)).fetchone()
                if row is None:
                    raise QuantError('UNASSIGNED_DATA_ROLE', f'尚未明确绑定{role}数据系列')
                head = connection.execute('SELECT head_snapshot_id FROM data_series WHERE series_id=?', (row[0],)).fetchone()
                # The immutable filesystem heads can advance before catalog refresh.
                snapshot = store.heads().get(row[0], {}).get('snapshot_id') or (head[0] if head else None)
                if not snapshot:
                    raise QuantError('MISSING_DATA_HEAD', '用途系列缺少已发布快照')
                frame, metadata, calendar = store.load(snapshot)
                if store.series_identity(metadata) != row[0]:
                    raise QuantError('CORRUPT_DATA_SERIES', '用途引用与快照身份不符')
                if role != 'signal' and set(metadata['price_basis']) != {'unadjusted'}:
                    raise QuantError('UNQUALIFIED_EXECUTION_PRICE', '执行/估值用途必须是核验原价')
                if check_qualification and version>=5 and role!='signal':
                    environments={r[0] for r in connection.execute('SELECT DISTINCT environment FROM accounts')}
                    # Without an account, real-market series still require evidence.
                    if environments!={'demo'} and metadata['data_type']=='real_market':
                        from .qualification import require_qualification
                        from ..common import now_utc
                        require_qualification(connection,store.root.parent,metadata,row[0],now_utc())
                return frame, metadata, calendar
        finally:
            connection.close()
    return store.load()  # Explicit legacy compatibility; v4 never falls back.


def bundle_for(store):
    from ..strategies.spec import DataBundle
    _, signal, calendar = selected(store, 'signal')
    _, execution, raw_calendar = selected(store, 'execution')
    if calendar.kind != raw_calendar.kind:
        raise QuantError('CALENDAR_CONFLICT', '研究/执行日历资格不同')
    factor = store.root.parent / 'factors/latest.json'
    return DataBundle(signal['snapshot_id'], calendar.hash, execution_snapshot_id=execution['snapshot_id'],
        factor_snapshot_id=factor_snapshot(store))


def factor_snapshot(store):
    if getattr(store, 'frozen_inputs', None) is not None:
        identity = store.frozen_inputs.get('factor_snapshot_id')
        if identity:
            from .factors import FactorStore
            FactorStore(store.root.parent/'factors').load(identity)
        return identity
    pointer=store.root.parent/'factors/latest.json'
    database=store.root.parent/'account.sqlite'
    if database.exists():
        connection=sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True)
        try:
            if connection.execute('SELECT version FROM schema_version').fetchone()[0]>=4:
                row=connection.execute("SELECT s.head_snapshot_id,s.metadata FROM data_roles r JOIN data_series s ON r.series_id=s.series_id WHERE r.role='factor'").fetchone()
                if row is None:return None
                from .factors import FactorStore
                snapshot=row[0]
                if pointer.exists():
                    latest=json.loads(pointer.read_text())['snapshot_id'];_,meta=FactorStore(store.root.parent/'factors').load(latest)
                    if meta['metadata']==json.loads(row[1])['metadata']:snapshot=latest
                FactorStore(store.root.parent/'factors').load(snapshot)
                return snapshot
        finally:connection.close()
    return json.loads(pointer.read_text())['snapshot_id'] if pointer.exists() else None
