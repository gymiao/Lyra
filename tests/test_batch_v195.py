import math
from pathlib import Path
from types import SimpleNamespace
import pytest
from personal_quant.common import QuantError
from personal_quant.config import Config
from personal_quant.portfolio import Ledger
from personal_quant.workspace.service import create,worker
from personal_quant.workspace.batch import run,limits

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture
def account(tmp_path):
    root=tmp_path/'workspace'
    create(root,{'schema_version':1,'kind':'etf','account_id':'demo-account','initial_cash':'100000'},Config.load(ROOT/'configs/demo.toml'))
    started=worker(root,'start')
    return root,started['run_id']


def test_batch_limits_are_finite_and_typed():
    for kwargs in ({'max_sessions':0},{'max_sessions':True},{'max_sessions':10001},
                   {'max_seconds':math.nan},{'max_seconds':math.inf},{'max_seconds':0},
                   {'min_free_bytes':-1},{'min_free_bytes':True}):
        with pytest.raises(QuantError):limits(**kwargs)


def test_session_budget_stops_at_checkpoint_repeat_does_not_deposit(account):
    root,run_id=account
    first=worker(root,'batch',run_id,'2024-07-03',max_sessions=1,max_seconds=120,min_free_bytes=0)
    assert first['status']=='PAUSED' and first['through_session']=='2024-07-01'
    assert first['batch']['reason']=='BATCH_SESSION_LIMIT'
    repeated=run(root,run_id,'2024-07-01',max_sessions=1,max_seconds=120,min_free_bytes=0)
    assert repeated['events']==first['events']
    next_day=run(root,run_id,'2024-07-03',max_sessions=1,max_seconds=120,min_free_bytes=0)
    assert next_day['through_session']=='2024-07-02'
    book=Ledger.read_only(root/'runtime/demo/account.sqlite','demo')
    assert book.connection.execute("SELECT count(*) FROM events WHERE json_extract(payload,'$.kind')='DEPOSIT'").fetchone()[0]==1
    assert book.snapshot('demo-account','2024-07-03T21:30:00Z')['net_contributions']=='100000'
    book.close()


def test_disk_preflight_does_not_start_worker_or_touch_cash(account,monkeypatch):
    from personal_quant.workspace import batch
    root,run_id=account
    monkeypatch.setattr(batch.shutil,'disk_usage',lambda path:SimpleNamespace(free=0))
    def forbidden(*args,**kwargs):raise AssertionError('insufficient disk must not launch a worker')
    monkeypatch.setattr(batch.subprocess,'Popen',forbidden)
    result=run(root,run_id,'2024-07-01',min_free_bytes=1)
    assert result['events']==1 and result['through_session'] is None
    assert result['status']=='PAUSED' and result['batch']['reason']=='BATCH_DISK_LIMIT'


def test_owned_worker_timeout_preserves_facts_and_can_resume(account):
    root,run_id=account
    stopped=run(root,run_id,'2024-07-01',max_seconds=.001,min_free_bytes=0)
    assert stopped['batch']['reason']=='BATCH_TIME_LIMIT' and stopped['status']=='PAUSED'
    resumed=run(root,run_id,'2024-07-01',max_seconds=120,min_free_bytes=0)
    assert resumed['through_session']=='2024-07-01' and resumed['status']=='PAUSED'
    book=Ledger.read_only(root/'runtime/demo/account.sqlite','demo')
    assert book.connection.execute("SELECT count(*) FROM events WHERE json_extract(payload,'$.kind')='DEPOSIT'").fetchone()[0]==1
    book.close()


def test_pause_after_submission_before_child_start_is_honored(account,monkeypatch):
    from personal_quant.workspace import batch
    from personal_quant.workspace.worker import run as worker_run
    from personal_quant.common import now_utc,write_json
    root,run_id=account;original=batch.subprocess.Popen
    def delayed_launch(*args,**kwargs):
        write_json(root/'runtime/demo/simulation/pauses'/(run_id+'.json'),{'requested_at':now_utc()})
        return original(*args,**kwargs)
    monkeypatch.chdir(root)
    with monkeypatch.context() as patch:
        patch.setattr(batch.subprocess,'Popen',delayed_launch)
        paused=worker_run('batch',run_id,'2024-07-01',requested_at='2000-01-01T00:00:00Z',max_seconds=120,min_free_bytes=0)
    assert paused['through_session'] is None and paused['events']==1 and paused['status']=='PAUSED'
    # An explicit later resume starts a new request and can pass the old pause.
    resumed=run(root,run_id,'2024-07-01',max_seconds=120,min_free_bytes=0)
    assert resumed['through_session']=='2024-07-01' and resumed['events']==1
