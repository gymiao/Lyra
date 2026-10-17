"""Explicit v4 data roles; immutable snapshots remain in the existing Parquet store."""
import json
from ..common import QuantError, canonical, now_utc, digest
from ..locks import publication_lock
from .store import DataStore


class DataCatalog:
    def __init__(self, ledger):
        self.ledger = ledger
        self.store = DataStore(ledger.path.parent / 'data')
        if ledger.connection.execute('SELECT version FROM schema_version').fetchone()[0] < 4:
            raise QuantError('V18_NOT_ENABLED', '先显式备份并升级v1.8')

    def register(self, snapshot_id):
        factor=(self.store.root.parent/'factors'/snapshot_id/'manifest.json').exists()
        if factor:
            from .factors import FactorStore
            _,meta=FactorStore(self.store.root.parent/'factors').load(snapshot_id)
        else:
            _, meta, _ = self.store.load(snapshot_id)
        if self.ledger.environment != 'demo' and meta['data_type'] not in {'real_market','real_factors'}:
            raise QuantError('ENVIRONMENT_MISMATCH', '前向目录不能登记合成数据')
        series = digest({'kind':'factor','metadata':meta['metadata']}) if factor else self.store.series_identity(meta)
        with publication_lock(self.store.root.parent), self.ledger.transaction():
            row = self.ledger.connection.execute('SELECT head_snapshot_id,generation FROM data_series WHERE series_id=?', (series,)).fetchone()
            head = self.store.heads().get(series, {}).get('snapshot_id') or (row['head_snapshot_id'] if row else snapshot_id)
            if factor:
                pointer=self.store.root.parent/'factors/latest.json'
                if pointer.exists():
                    candidate=json.loads(pointer.read_text())['snapshot_id']
                    _,candidate_meta=FactorStore(self.store.root.parent/'factors').load(candidate)
                    if digest({'kind':'factor','metadata':candidate_meta['metadata']})==series:head=candidate
            else:
                if series not in self.store.heads():
                    _,head_meta,_=self.store.load(head)
                    if meta['acquired_at']>head_meta['acquired_at']:head=snapshot_id
                    pointer=self.store.root/'latest.json'
                    if pointer.exists():
                        latest=json.loads(pointer.read_text())['snapshot_id'];_,latest_meta,_=self.store.load(latest)
                        if self.store.series_identity(latest_meta)==series:head=latest
                _,published_meta,_=self.store.load(head)
                meta_for_series=published_meta
            generation = (row['generation'] + int(row['head_snapshot_id'] != head)) if row else 1
            self.ledger.connection.execute('INSERT INTO data_series VALUES(?,?,?,?,?) ON CONFLICT(series_id) DO UPDATE SET head_snapshot_id=excluded.head_snapshot_id,generation=excluded.generation,metadata=excluded.metadata',
                (series, head, generation, canonical(meta if factor else meta_for_series), now_utc()))
            self.ledger.connection.execute('INSERT OR IGNORE INTO data_publications VALUES(?,?,?)', (snapshot_id, series, canonical(meta)))
        return {'series_id': series, 'snapshot_id': snapshot_id, 'generation': generation}

    def refresh(self):
        for directory in sorted(self.store.root.iterdir()) if self.store.root.exists() else []:
            if directory.is_dir() and len(directory.name) == 64:
                self.register(directory.name)
        factors=self.store.root.parent/'factors'
        if factors.exists():
            for directory in sorted(factors.iterdir()):
                if directory.is_dir() and len(directory.name)==64:self.register(directory.name)
        return self.list()

    def list(self):
        return {'series': [dict(r) for r in self.ledger.connection.execute('SELECT * FROM data_series ORDER BY series_id')],
                'roles': [dict(r) for r in self.ledger.connection.execute('SELECT * FROM data_roles ORDER BY role')]}

    def bind(self, role, identity, *, expected_revision):
        if role not in {'signal','execution','valuation','factor'}:
            raise QuantError('INVALID_DATA_ROLE', '用途必须为signal/execution/valuation/factor')
        if not self.ledger.connection.execute('SELECT 1 FROM data_series WHERE series_id=?', (identity,)).fetchone():
            identity = self.register(identity)['series_id']
        with publication_lock(self.store.root.parent), self.ledger.transaction():
            previous = self.ledger.connection.execute('SELECT revision FROM data_roles WHERE role=?', (role,)).fetchone()
            revision = previous['revision'] if previous else 0
            if expected_revision != revision:
                raise QuantError('STALE_DATA_BINDING', '用途选择已改变，请重新核对')
            entry=self.ledger.connection.execute('SELECT head_snapshot_id,metadata FROM data_series WHERE series_id=?',(identity,)).fetchone()
            head=entry[0]
            is_factor='metadata' in json.loads(entry[1])
            if (role=='factor')!=is_factor:raise QuantError('INVALID_DATA_ROLE','价格和因子用途不能互换')
            if role=='factor':
                from .factors import FactorStore
                FactorStore(self.store.root.parent/'factors').load(head)
                meta=None
            else:
                _, meta, _ = self.store.load(self.store.heads().get(identity, {}).get('snapshot_id', head))
            if role not in {'signal','factor'} and set(meta['price_basis']) != {'unadjusted'}:
                raise QuantError('UNQUALIFIED_EXECUTION_PRICE', '执行/估值需要核验原价，不能绑定复权研究价')
            if role not in {'signal','factor'} and self.ledger.environment!='demo' and self.ledger.connection.execute('SELECT version FROM schema_version').fetchone()[0]>=5:
                from .qualification import require_qualification
                require_qualification(self.ledger.connection,self.ledger.path.parent,meta,identity,now_utc())
            self.ledger.connection.execute('INSERT INTO data_roles VALUES(?,?,?,?) ON CONFLICT(role) DO UPDATE SET series_id=excluded.series_id,revision=excluded.revision,updated_at=excluded.updated_at',
                (role, identity, revision + 1, now_utc()))
        return {'role': role, 'series_id': identity, 'revision': revision + 1}
