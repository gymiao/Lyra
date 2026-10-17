import time
from pathlib import Path
from personal_quant.config import Config
from personal_quant.workspace.service import create,worker
from personal_quant.workspace.jobs import launch,list_jobs

ROOT=Path(__file__).resolve().parents[1]


def test_background_job_has_durable_receipt_and_no_duplicate_initial_funds(tmp_path):
    root=tmp_path/'workspace'
    create(root,{'schema_version':1,'account_id':'demo-account','initial_cash':'100000','kind':'etf'},Config.load(ROOT/'configs/demo.toml'))
    started=worker(root,'start')
    job=launch(root,'resume',started['run_id'],'2024-07-02')
    deadline=time.monotonic()+45
    while time.monotonic()<deadline:
        current=next(row for row in list_jobs(root) if row['job_id']==job['job_id'])
        if current['status']!='RUNNING':break
        time.sleep(.1)
    assert current['status']=='SUCCESS',current
    assert current['result']['through_session']=='2024-07-02'
    assert current['result']['events']==1


def test_background_option_job_passes_both_explicit_tool_paths_without_shell(tmp_path,monkeypatch):
    import json
    from types import SimpleNamespace
    from personal_quant.workspace import jobs
    root=tmp_path/'options'
    create(root,{'schema_version':1,'account_id':'demo-account','initial_cash':'100000','kind':'options'},Config.load(ROOT/'configs/demo.toml'))
    calls=[]
    def child(command,**kwargs):calls.append((command,kwargs));return SimpleNamespace(pid=123456)
    monkeypatch.setattr(jobs.subprocess,'Popen',child)
    monkeypatch.setattr(jobs,'process_identity',lambda pid:{'pid':pid})
    monkeypatch.setattr(jobs,'worker_alive',lambda owner:False)
    result=launch(root,'resume','a'*64,'2024-11-04',engine_root=tmp_path/'LEAN with spaces',dotnet=tmp_path/'SDK with spaces/dotnet')
    command,kwargs=calls[0]
    assert command[command.index('--engine-root')+1]==str(tmp_path/'LEAN with spaces')
    assert command[command.index('--dotnet')+1]==str(tmp_path/'SDK with spaces/dotnet')
    assert 'shell' not in kwargs and kwargs['cwd']==root
    record=json.loads((root/'runtime/demo/simulation/jobs'/result['job_id']/'job.json').read_text())
    assert record['tool_paths']==result['tool_paths'] and record['tool_paths']['engine_root']==str(tmp_path/'LEAN with spaces')
    from personal_quant.common import QuantError
    import pytest
    with pytest.raises(QuantError) as caught:launch(root,'resume','a'*64,engine_root=tmp_path/'LEAN')
    assert caught.value.code=='SIMULATION_TOOL_PATHS_REQUIRED'
