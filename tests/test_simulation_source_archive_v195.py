from pathlib import Path
import pytest
from personal_quant.common import QuantError
from personal_quant.config import Config
from personal_quant.research.artifacts import LOCK_FILES,verify_source
from personal_quant.workspace.service import create,worker,status

ROOT=Path(__file__).resolve().parents[1]


def test_start_captures_code_and_locks_and_tampered_archive_blocks_before_facts(tmp_path):
    root=tmp_path/'workspace'
    create(root,{'schema_version':1,'account_id':'demo-account','initial_cash':'100000','kind':'etf'},Config.load(ROOT/'configs/demo.toml'))
    run=worker(root,'start')
    archive=root/'runtime/demo/source-archives'/run['source_hash']
    verify_source(archive,run['source_hash'])
    assert all((archive/name).is_file() for name in LOCK_FILES)
    assert worker(root,'start')['run_id']==run['run_id']
    target=archive/'src/personal_quant/__init__.py'
    target.write_bytes(target.read_bytes()+b'\n# deliberate archived-code corruption\n')
    with pytest.raises(QuantError) as caught:worker(root,'resume',run['run_id'],'2024-07-03')
    assert '归档源码与原运行指纹不符' in str(caught.value)
    assert status(root)['events']==1


def test_environment_drift_blocks_execution_but_historical_archive_can_be_read(tmp_path,monkeypatch):
    from personal_quant.portfolio import Ledger
    from personal_quant.workspace import source_archive
    root=tmp_path/'workspace'
    create(root,{'schema_version':1,'account_id':'demo-account','initial_cash':'100000','kind':'etf'},Config.load(ROOT/'configs/demo.toml'))
    run=worker(root,'start');runtime=root/'runtime/demo'
    book=Ledger(runtime/'account.sqlite','demo')
    changed=source_archive.environment();changed['packages']['numpy']='unverified-version'
    monkeypatch.setattr(source_archive,'environment',lambda:changed)
    with pytest.raises(QuantError) as caught:source_archive.require(book,runtime,run['run_id'],run['source_hash'])
    assert caught.value.code=='SIMULATION_ENVIRONMENT_CHANGED'
    source_archive.require(book,runtime,run['run_id'],run['source_hash'],check_environment=False)
    assert book.sequence('demo-account')==1
    book.close()


def test_source_binding_and_run_registration_roll_back_together(tmp_path,monkeypatch):
    from personal_quant.portfolio import Ledger
    from personal_quant.workspace import source_archive
    from personal_quant.workspace.worker import run
    root=tmp_path/'workspace'
    create(root,{'schema_version':1,'account_id':'demo-account','initial_cash':'100000','kind':'etf'},Config.load(ROOT/'configs/demo.toml'))
    monkeypatch.chdir(root);original=source_archive.bind
    def fail_after_binding(*args,**kwargs):
        original(*args,**kwargs)
        raise QuantError('SOURCE_REGISTRATION_FAILURE','注入源码绑定后注册失败')
    monkeypatch.setattr(source_archive,'bind',fail_after_binding)
    with pytest.raises(QuantError) as caught:run('start')
    assert caught.value.code=='SOURCE_REGISTRATION_FAILURE'
    book=Ledger(root/'runtime/demo/account.sqlite','demo')
    assert book.connection.execute('SELECT count(*) FROM simulation_runs').fetchone()[0]==0
    assert book.connection.execute("SELECT count(*) FROM tasks WHERE task_id LIKE 'simulation-source:%'").fetchone()[0]==0
    assert book.sequence('demo-account')==1
    book.close()


def test_backup_requires_bound_source_and_restores_it(tmp_path,monkeypatch):
    import shutil
    from personal_quant.portfolio import Ledger
    from personal_quant.portfolio.backup import create_bundle,restore_bundle
    from personal_quant.workspace.source_archive import require
    root=tmp_path/'workspace'
    create(root,{'schema_version':1,'account_id':'demo-account','initial_cash':'100000','kind':'etf'},Config.load(ROOT/'configs/demo.toml'))
    run=worker(root,'start');monkeypatch.chdir(root)
    runtime=root/'runtime/demo'
    create_bundle(runtime,root/'config.json',tmp_path/'bundle')
    restored=tmp_path/'restored';result=restore_bundle(tmp_path/'bundle',restored,'demo')
    recovered=restored/Config.load(result['config']).runtime_dir
    book=Ledger(recovered/'account.sqlite','demo')
    require(book,recovered,run['run_id'],run['source_hash'],check_environment=False)
    assert book.sequence('demo-account')==1
    book.close()
    shutil.rmtree(runtime/'source-archives'/run['source_hash'])
    with pytest.raises(QuantError) as caught:create_bundle(runtime,root/'config.json',tmp_path/'missing-source-bundle')
    assert caught.value.code=='SOURCE_UNAVAILABLE'
