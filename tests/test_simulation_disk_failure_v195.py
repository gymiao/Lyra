"""Failure injection only: native execution is forbidden in these cases."""
import errno
from pathlib import Path
import sqlite3
import sys
import pytest
from personal_quant.common import digest
from personal_quant.config import Config
from personal_quant.portfolio import Ledger
from personal_quant.workspace.service import create

ROOT=Path(__file__).resolve().parents[1]


def test_primary_disk_error_survives_failed_database_and_file_diagnostics(tmp_path,monkeypatch):
    from personal_quant.workspace import options_runner,portable_tools
    root=tmp_path/'workspace'
    create(root,{'schema_version':1,'kind':'options','account_id':'demo-account','initial_cash':'100000'},Config.load(ROOT/'configs/demo.toml'))
    monkeypatch.chdir(root)
    body={'schema_version':1,'lean_commit':'unit-no-engine','sdk_version':'unit-no-sdk','lean_files':{},'sdk_files':{}}
    manifest={**body,'content_hash':digest(body)}
    monkeypatch.setattr(portable_tools,'fingerprint',lambda *args,**kwargs:manifest)
    started=options_runner.run('start',input_file=ROOT/'examples/options/monthly-variable-path.json',
        engine_root=tmp_path/'no-engine',dotnet=tmp_path/'no-sdk',fee_per_contract=2)
    primary=OSError(errno.ENOSPC,'primary-native-write-full')
    def fail_engine(*args,**kwargs):raise primary
    monkeypatch.setattr(options_runner,'monthly_replay',fail_engine)
    class Connection:
        def __init__(self,connection):self.connection=connection
        def __getattr__(self,key):return getattr(self.connection,key)
        def execute(self,sql,args=()):
            if sql.startswith('UPDATE simulation_runs SET status=') and args and args[0]=='FAILED':
                raise sqlite3.OperationalError('secondary-status-write-full')
            return self.connection.execute(sql,args)
    def book(*args,**kwargs):
        value=Ledger(*args,**kwargs);value.connection=Connection(value.connection);return value
    monkeypatch.setattr(options_runner,'Ledger',book)
    original=options_runner.write_json
    def fail_diagnostic(path,value):
        if Path(path).name=='last-failure.json':raise OSError(errno.ENOSPC,'secondary-diagnostic-write-full')
        return original(path,value)
    monkeypatch.setattr(options_runner,'write_json',fail_diagnostic)
    with pytest.raises(OSError) as caught:options_runner.run('resume',started['run_id'],'2024-11-04')
    assert caught.value is primary and caught.value.errno==errno.ENOSPC
    notes=' '.join(caught.value.__notes__)
    assert 'secondary-status-write-full' in notes and 'secondary-diagnostic-write-full' in notes
    observed=Ledger.read_only(root/'runtime/demo/account.sqlite','demo')
    assert observed.sequence('demo-account')==1;observed.close()


def test_result_receipt_failure_keeps_original_error_on_stderr(tmp_path,monkeypatch,capsys):
    from personal_quant.workspace import worker
    from personal_quant import common
    monkeypatch.chdir(tmp_path)
    target=tmp_path/'runtime/demo/simulation/jobs/test/result.json';target.parent.mkdir(parents=True)
    def run(*args,**kwargs):raise OSError(errno.ENOSPC,'original-result-source-full')
    def write(*args,**kwargs):raise OSError(errno.ENOSPC,'receipt-write-full')
    monkeypatch.setattr(worker,'run',run);monkeypatch.setattr(common,'write_json',write)
    monkeypatch.setattr(sys,'argv',['worker','resume','--run-id','a'*64,'--result-file',str(target)])
    with pytest.raises(SystemExit) as caught:worker.main()
    assert caught.value.code==1
    error=capsys.readouterr().err
    assert 'original-result-source-full' in error and 'receipt-write-full' in error
