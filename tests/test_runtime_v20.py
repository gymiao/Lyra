"""Independent expectations for the five reproducible v2.0 audit failures."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from dataclasses import replace
from unittest.mock import patch
import pytest
from personal_quant.common import QuantError
from personal_quant.config import Config
from personal_quant.workspace.service import create,worker
from personal_quant.workspace import jobs
from personal_quant.workspace.batch import run as batch
from personal_quant.workspace.experiments import curve
from personal_quant.data.store import DataStore

ROOT=Path(__file__).resolve().parents[1]


def workspace(tmp_path,kind='etf',end='2024-07-05'):
    root=tmp_path/'workspace'
    create(root,{'schema_version':1,'kind':kind,'account_id':'demo-account','initial_cash':'100000'},
           replace(Config.load(ROOT/'configs/demo.toml'),evaluation_end=end))
    return root


def test_budget_counts_frozen_sessions_including_synthetic_market_holiday(tmp_path):
    root=workspace(tmp_path);start=worker(root,'start')
    result=batch(root,start['run_id'],'2024-07-05',max_sessions=4,max_seconds=120,min_free_bytes=0)
    con=sqlite3.connect(root/'runtime/demo/account.sqlite')
    days=[r[0] for r in con.execute('SELECT session FROM simulation_checkpoints ORDER BY session')];con.close()
    assert days==['2024-07-01','2024-07-02','2024-07-03','2024-07-04']
    assert result['batch']['reason']=='BATCH_SESSION_LIMIT' and result['events']==1
    end=batch(root,start['run_id'],'2024-07-05',max_sessions=4,max_seconds=120,min_free_bytes=0)
    assert end['status']=='COMPLETED' and end['events']==1


def test_mutable_head_cannot_change_frozen_run_or_comparison(tmp_path):
    root=workspace(tmp_path,end='2024-07-02');start=worker(root,'start')
    worker(root,'step',start['run_id'],'2024-07-01')
    store=DataStore(root/'runtime/demo/data');frame,old,calendar=store.load_role('signal')
    frame.loc[frame.session_date.astype(str)=='2024-07-02',['open','high','low','close','adj_close']]*=1.001
    new=store.save(frame,calendar);assert old['snapshot_id']!=new['snapshot_id']
    end=worker(root,'resume',start['run_id'],'2024-07-02')
    _,policy=curve(root,start['run_id']);assert policy['snapshot']==old['snapshot_id']
    con=sqlite3.connect(root/'runtime/demo/account.sqlite')
    rows=[json.loads(r[0]) for r in con.execute('SELECT details FROM simulation_checkpoints')]
    assert {r['data']['snapshot_id'] for r in rows}=={old['snapshot_id']}
    assert len({r['input_bundle_id'] for r in rows})==1 and end['events']==1
    row=con.execute('SELECT session,details FROM simulation_checkpoints LIMIT 1').fetchone()
    body=json.loads(row[1]);body['data']['snapshot_id']=new['snapshot_id']
    con.execute('UPDATE simulation_checkpoints SET details=? WHERE session=?',(json.dumps(body),row[0]));con.commit();con.close()
    with pytest.raises(QuantError,match='日检查点'):curve(root,start['run_id'])


def test_bad_task_is_visible_and_blocks_writes_with_explicit_code(tmp_path):
    root=workspace(tmp_path,'options');folder=root/'runtime/demo/simulation/jobs/bad';folder.mkdir(parents=True)
    (folder/'job.json').write_text('{')
    rows=jobs.list_jobs(root)
    assert len(rows)==1 and rows[0]['status']=='UNVERIFIED'
    assert rows[0]['code']=='CORRUPT_JOB_METADATA'
    with pytest.raises(QuantError) as exc:jobs.launch(root,'prepare',input_file=tmp_path/'spec.json')
    assert exc.value.code=='SIMULATION_ALREADY_RUNNING'
    assert (folder/'job.json').read_text()=='{'


def test_failed_initial_intent_never_spawns_worker(tmp_path,monkeypatch):
    root=workspace(tmp_path,'options')
    def no_spawn(*args,**kwargs):raise AssertionError('must persist before spawn')
    monkeypatch.setattr(jobs.subprocess,'Popen',no_spawn)
    monkeypatch.setattr(jobs,'write_json',lambda *a:(_ for _ in ()).throw(OSError('disk fault')))
    with pytest.raises(OSError):jobs.launch(root,'prepare',input_file=tmp_path/'spec.json')


def test_worker_does_not_import_inherited_pythonpath(tmp_path,monkeypatch):
    root=workspace(tmp_path,'options');shadow=tmp_path/'shadow';shadow.mkdir();marker=tmp_path/'unexpected-import'
    (shadow/'sitecustomize.py').write_text('from pathlib import Path\nPath('+repr(str(marker))+').touch()\n')
    monkeypatch.setenv('PYTHONPATH',str(shadow));monkeypatch.setenv('PYTHONHOME',str(tmp_path/'invalid-home'))
    with pytest.raises(QuantError):worker(root,'prepare',input_file=tmp_path/'missing.json')
    assert not marker.exists()


def test_external_native_tools_are_shared_by_preflight_and_tests(tmp_path,monkeypatch):
    from personal_quant.processes import native_tools
    engine=tmp_path/'LEAN with spaces';engine.mkdir();sdk=tmp_path/'sdk with spaces/dotnet';sdk.parent.mkdir()
    sdk.write_text('#!/bin/sh\nexit 0\n');sdk.chmod(0o755)
    monkeypatch.setenv('LYRAX_TEST_ENGINE_ROOT',str(engine));monkeypatch.setenv('LYRAX_TEST_DOTNET',str(sdk))
    assert native_tools(tmp_path/'no-local-tools')==(engine,sdk)


def test_group_cleanup_reaches_child_after_launcher_exits(tmp_path):
    from personal_quant.workspace.batch import _stop
    pidfile=tmp_path/'child-pid'
    code='import subprocess,sys; from pathlib import Path; p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"]);Path(sys.argv[1]).write_text(str(p.pid))'
    launcher=subprocess.Popen([sys.executable,'-c',code,str(pidfile)],start_new_session=True)
    launcher.wait(timeout=10);pid=int(pidfile.read_text())
    try:
        _stop(launcher)
        import time
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            stat=Path(f'/proc/{pid}/stat')
            if not stat.exists() or stat.read_text().rsplit(')',1)[1].split()[0]=='Z':break
            time.sleep(.02)
        else:raise AssertionError('descendant survived its owned process group')
    finally:
        try:os.kill(pid,9)
        except ProcessLookupError:pass


def test_ledger_read_view_stays_consistent_during_committed_import(tmp_path):
    from personal_quant.portfolio import Ledger
    root=tmp_path/'consistent.sqlite';book=Ledger(root,'demo')
    book.connection.execute('PRAGMA journal_mode=WAL');book.account('demo-account')
    first={'event_id':'first','kind':'DEPOSIT','amount':'100','effective_at':'2024-07-01T20:30:00Z','source':'test','evidence_type':'test'}
    book.import_events('demo-account',[first]);reader=Ledger.read_only(root,'demo')
    assert reader.snapshot('demo-account','2024-07-02T20:30:00Z')['equity']=='100'
    book.import_events('demo-account',[{**first,'event_id':'second','amount':'50'}])
    assert reader.snapshot('demo-account','2024-07-02T20:30:00Z')['equity']=='100'
    reader.close();reader=Ledger.read_only(root,'demo')
    assert reader.snapshot('demo-account','2024-07-02T20:30:00Z')['equity']=='150'
    reader.close();book.close()


def test_submission_failure_after_spawn_reaps_child_and_keeps_receipt(tmp_path,monkeypatch):
    root=workspace(tmp_path,'options');original=jobs.write_json;writes=[];children=[];popen=jobs.subprocess.Popen
    def persist(path,value):
        writes.append(path.name)
        if writes==['job.json','job.json']:raise OSError('owner registration disk fault')
        return original(path,value)
    def spawn(*args,**kwargs):
        child=popen(*args,**kwargs);children.append(child);return child
    monkeypatch.setattr(jobs,'write_json',persist);monkeypatch.setattr(jobs.subprocess,'Popen',spawn)
    with pytest.raises(OSError):jobs.launch(root,'prepare',input_file=tmp_path/'missing.json')
    assert len(children)==1 and children[0].poll() is not None
    rows=jobs.list_jobs(root);assert len(rows)==1 and rows[0]['status']=='FAILED'
    assert rows[0]['result']['code']=='WORKER_START_FAILED'


def test_request_identity_returns_prior_attempt_and_rejects_changed_input(tmp_path):
    import time
    root=workspace(tmp_path,'options');file=tmp_path/'bad-spec.json';file.write_text('{}')
    job=jobs.launch(root,'prepare',input_file=file,request_id='stable-click')
    assert jobs.launch(root,'prepare',input_file=file,request_id='stable-click')['job_id']==job['job_id']
    file.write_text('{"changed":true}')
    with pytest.raises(QuantError) as exc:jobs.launch(root,'prepare',input_file=file,request_id='stable-click')
    assert exc.value.code=='SIMULATION_REQUEST_CONFLICT'
    deadline=time.monotonic()+30
    while time.monotonic()<deadline:
        if jobs.list_jobs(root)[0]['status']!='RUNNING':break
        time.sleep(.05)
    else:raise AssertionError('worker failed to finish its rejected input')


def test_explicit_task_review_preserves_bad_file_and_detects_new_receipt(tmp_path):
    root=workspace(tmp_path,'options');folder=root/'runtime/demo/simulation/jobs/bad';folder.mkdir(parents=True)
    (folder/'job.json').write_text('{')
    row=jobs.list_jobs(root)[0]
    result=jobs.review(root,'bad',{'files_hash':row['files_hash'],'reason':'operator checked no local process or execution','confirm_no_inflight':True})
    assert result['financial_events_added']==0 and (folder/'job.json').read_text()=='{'
    assert jobs.list_jobs(root)[0]['status']=='REVIEWED'
    (folder/'result.json').write_text('{}')
    assert jobs.list_jobs(root)[0]['status']=='UNVERIFIED'
