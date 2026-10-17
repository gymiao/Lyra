from concurrent.futures import ThreadPoolExecutor
import threading
import time

from personal_quant.data.factors import FactorStore
from test_factors_v15 import rows, metadata


def test_concurrent_factor_imports_preserve_both_batches(tmp_path, monkeypatch):
    store = FactorStore(tmp_path / 'factors')
    store.save(rows(), metadata())
    original = FactorStore.load
    def slow_read(self, snapshot_id=None):
        result = original(self, snapshot_id)
        if snapshot_id is None:
            time.sleep(.1)  # Both unprotected writers would read the same version.
        return result
    monkeypatch.setattr(FactorStore, 'load', slow_read)
    start = threading.Barrier(2)
    def ingest(index):
        frame = rows().iloc[[index]].copy()
        frame['revision'] = 2
        frame['value'] = .8 + index / 10
        frame['published_at'] = frame['available_at'] = '2024-08-01T20:30:00Z'
        start.wait(timeout=5)
        return store.save(frame, metadata())
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(ingest, [0, 1]))
    assert len(results) == 2
    current, _ = store.load()
    assert len(current) == 6
    assert len(current.loc[current.revision == 2]) == 2


from dataclasses import replace
from pathlib import Path
import pandas as pd
import pytest
from personal_quant.common import QuantError, write_json
from personal_quant.data.store import DataStore
from personal_quant.data.catalog import DataCatalog
from personal_quant.strategies.store import enable_v18
from personal_quant.execution.daily import DailyRunner
from personal_quant.portfolio.reconciliation import ReconciliationRules
from personal_quant.cli import references
from personal_quant.portfolio.backup import create_bundle, restore_bundle
from personal_quant.portfolio import Ledger
from test_bindings_v15 import bound_workspace


@pytest.mark.parametrize('raw_last', [True, False])
def test_daily_consumes_distinct_price_roles_and_survives_restore(bound_workspace, raw_last):
    binding, _, frame, _, calendar = bound_workspace
    config, book = binding.config, binding.ledger
    store = DataStore(Path(config.runtime_dir) / 'data')
    research = frame.copy(); research['price_basis'] = 'provider_split_adjusted'
    raw = frame.loc[frame.session_date >= '2024-07-01'].copy()
    raw['source'] = 'independent_raw'
    raw[['open','high','low','close']] *= 2
    if raw_last:
        signal = store.save(research, calendar); execution = store.save(raw, calendar)
    else:
        execution = store.save(raw, calendar); signal = store.save(research, calendar)
    upgraded = enable_v18(book, Path('config.json'))
    assert upgraded['schema_version'] == 4
    catalog = DataCatalog(book); catalog.refresh()
    for role, snapshot in [('signal',signal),('execution',execution),('valuation',execution)]:
        catalog.bind(role, snapshot['snapshot_id'], expected_revision=0)
    with pytest.raises(QuantError, match='改变'):
        catalog.bind('signal', signal['snapshot_id'], expected_revision=0)
    book.import_events('sample', [{'event_id':'cash','kind':'DEPOSIT','amount':10000,'effective_at':'2024-07-01T20:00:00Z','source':'test','evidence_type':'test'}])
    clock = '2024-07-31T20:30:00Z'
    book.reconcile('sample', {'account_id':'sample','currency':'USD','as_of':clock,'cash_basis':'settled','cash':10000,'positions':{},'source':'independent_test'},
        references(raw, clock), rules=ReconciliationRules.from_config(config))
    binding.request('sample', 'momentum_rotation', 1, calendar, as_of='2024-07-01T20:30:00Z')
    result = DailyRunner(book, config, store).run('sample', as_of=clock)
    assert result['planning']['status'] == 'READY'
    from personal_quant.execution.plans import PlanService
    plan = PlanService(book, config).get(result['planning']['plan_id'])
    assert plan['payload']['signal']['snapshot_id'] == signal['snapshot_id']
    assert plan['payload']['reference_snapshot_id'] == execution['snapshot_id']
    finished = DailyRunner(book, config, store).run('sample', as_of='2024-08-02T20:30:00Z')
    assert finished['account_facts']['completed']
    seq = book.sequence('sample')
    assert DailyRunner(book, config, store).run('sample', as_of='2024-08-02T20:30:00Z')['ledger_seq'] == seq
    create_bundle(Path(config.runtime_dir), Path('config.json'), Path('v4-backup'))
    restore_bundle(Path('v4-backup'), Path('v4-restored'), 'demo')
    restored = Ledger(Path('v4-restored/runtime/demo/account.sqlite'), 'demo')
    assert restored.sequence('sample') == seq
    assert len(DataCatalog(restored).list()['roles']) == 3
    restored.close()


def test_v4_unassigned_roles_never_follow_last_import(bound_workspace):
    binding, _, _, _, _ = bound_workspace
    enable_v18(binding.ledger, Path('config.json'))
    store = DataStore(Path(binding.config.runtime_dir) / 'data')
    with pytest.raises(QuantError, match='绑定'):
        store.load_role('execution')


def _factor_process(directory,index,start):
    frame=rows().iloc[[index]].copy();frame['revision']=2;frame['value']=.9+index/10
    frame['published_at']=frame['available_at']='2024-08-01T20:30:00Z'
    start.wait(timeout=10)
    FactorStore(Path(directory)).save(frame,metadata())


def test_two_process_factor_updates_and_duplicate_receipts(tmp_path):
    import multiprocessing
    store=FactorStore(tmp_path/'factors');store.save(rows(),metadata())
    old,_=store.load();ctx=multiprocessing.get_context('fork');start=ctx.Barrier(2)
    processes=[ctx.Process(target=_factor_process,args=(store.root,i,start)) for i in [0,1]]
    for p in processes:p.start()
    for p in processes:p.join(timeout=15);assert not p.is_alive();assert p.exitcode==0
    merged,_=store.load();assert len(merged)==6
    for event in old.to_dict('records'):
        candidate=merged.loc[(merged.source_record_id==event['source_record_id'])&(merged.revision==event['revision'])]
        assert candidate.iloc[0].recorded_at==event['recorded_at']
    first=store.save(rows(),metadata())
    assert first['rows']==6


def test_factor_binding_is_explicit_and_preserved_on_update(bound_workspace):
    from personal_quant.data.selection import factor_snapshot
    binding,_,_,_,_=bound_workspace
    enable_v18(binding.ledger,Path('config.json'))
    store=FactorStore(Path(binding.config.runtime_dir)/'factors')
    first=store.save(rows(),metadata());catalog=DataCatalog(binding.ledger);catalog.refresh()
    prices=DataStore(Path(binding.config.runtime_dir)/'data')
    assert factor_snapshot(prices) is None
    catalog.bind('factor',first['snapshot_id'],expected_revision=0)
    assert factor_snapshot(prices)==first['snapshot_id']
    changed=rows().iloc[[0]].copy();changed['revision']=2;changed['value']=.8
    second=store.save(changed,metadata())
    assert factor_snapshot(prices)==second['snapshot_id']
    with pytest.raises(QuantError):catalog.bind('execution',first['snapshot_id'],expected_revision=0)


def test_concurrent_price_incremental_updates_do_not_drop_a_date(market,tmp_path):
    source,frame,_,calendar=market
    store=DataStore(tmp_path/'data');days=sorted(frame.session_date.unique())
    first=store.save(frame.loc[frame.session_date<days[-2]],calendar)
    series=store.series_identity(first);barrier=threading.Barrier(2)
    def save(day):
        barrier.wait(timeout=5)
        return store.save(frame.loc[frame.session_date==day],calendar,incremental=True,series_id=series)
    with ThreadPoolExecutor(2) as pool:list(pool.map(save,days[-2:]))
    merged,_meta,_cal=store.load_series(series)
    assert len(merged)==len(frame)
    assert set(merged.session_date)==set(frame.session_date)


def test_legacy_monthly_rule_uses_separate_signal_and_execution_roles(bound_workspace):
    from personal_quant.strategies.archive import SignalArchive
    from personal_quant.strategies import decode_signal
    from personal_quant.execution.plans import PlanService
    binding,_,frame,_,calendar=bound_workspace;book=binding.ledger;config=binding.config
    store=DataStore(Path(config.runtime_dir)/'data')
    research=frame.copy();research['price_basis']='provider_split_adjusted'
    raw=frame.loc[frame.session_date>='2024-07-01'].copy();raw['source']='verified_raw'
    signal_meta=store.save(research,calendar);raw_meta=store.save(raw,calendar)
    enable_v18(book,Path('config.json'));catalog=DataCatalog(book);catalog.refresh()
    for role,meta in [('signal',signal_meta),('execution',raw_meta),('valuation',raw_meta)]:catalog.bind(role,meta['snapshot_id'],expected_revision=0)
    book.import_events('sample',[{'event_id':'cash','kind':'DEPOSIT','amount':10000,'effective_at':'2024-07-01T20:00:00Z','source':'test','evidence_type':'test'}])
    clock='2024-07-31T20:30:00Z'
    book.reconcile('sample',{'account_id':'sample','currency':'USD','as_of':clock,'cash_basis':'settled','cash':10000,'positions':{},'source':'independent_test'},references(raw,clock),rules=ReconciliationRules.from_config(config))
    record=SignalArchive(book).generate(research,signal_meta,calendar,config,'2024-07-31',decision_time=clock,account_state=book.snapshot('sample',clock))
    plan=PlanService(book,config).create('sample',decode_signal(record['signal']),raw,raw_meta,calendar,clock)
    assert plan['check_status']=='PASSED'
    assert plan['payload']['signal']['snapshot_id']==signal_meta['snapshot_id']
    assert plan['payload']['reference_snapshot_id']==raw_meta['snapshot_id']


def test_corrupt_orphan_factor_snapshot_never_replaces_valid_head(tmp_path):
    import json
    store=FactorStore(tmp_path/'factors');first=store.save(rows(),metadata())
    changed=rows().iloc[[0]].copy();changed['revision']=2;changed['value']=.8
    newer=store.save(changed,metadata())
    path=store.root/newer['snapshot_id']/'factors.parquet';path.write_bytes(b'corrupt')
    write_json(store.root/'latest.json',{'snapshot_id':first['snapshot_id']})
    with pytest.raises(QuantError,match='不匹配'):store.save(changed,metadata())
    assert json.loads((store.root/'latest.json').read_text())['snapshot_id']==first['snapshot_id']
    assert store.load()[1]['rows']==first['rows']


def test_v4_migration_failure_rolls_back_all_new_tables(bound_workspace,monkeypatch):
    binding,_,_,_,_=bound_workspace;book=binding.ledger
    before={r[0] for r in book.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    seq=book.sequence('sample')
    def fail(connection):
        connection.execute('CREATE TABLE incomplete_v4(value TEXT)')
        raise QuantError('TEST_MIGRATION_FAILURE','injected migration failure')
    monkeypatch.setattr('personal_quant.portfolio.schema.apply_v18_schema',fail)
    with pytest.raises(QuantError,match='injected'):enable_v18(book,Path('config.json'))
    assert book.connection.execute('SELECT version FROM schema_version').fetchone()[0]==3
    assert {r[0] for r in book.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}==before
    assert book.sequence('sample')==seq
