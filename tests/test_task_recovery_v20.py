import json
from pathlib import Path
import time
import subprocess
from personal_quant.config import Config
from personal_quant.workspace.service import create,status
from personal_quant.workspace.jobs import launch,list_jobs,retry
from personal_quant.processes import python_command,python_environment
ROOT=Path(__file__).resolve().parents[1]


def workspace(tmp_path):
    root=tmp_path/'workspace';create(root,{'schema_version':1,'kind':'options','account_id':'demo-account','initial_cash':100000},Config.load(ROOT/'configs/demo.toml'))
    file=tmp_path/'invalid.json';file.write_text('{}');return root,file


def terminal(root,job):
    end=time.monotonic()+45
    while time.monotonic()<end:
        row=next(r for r in list_jobs(root) if r['job_id']==job)
        if row.get('result'):return row
        time.sleep(.1)
    raise AssertionError('task did not publish a receipt')


def test_explicit_retry_is_new_stable_attempt_and_never_rebooks_deposit(tmp_path):
    root,file=workspace(tmp_path);first=launch(root,'prepare',input_file=file,request_id='original')
    failed=terminal(root,first['job_id']);assert failed['status']=='FAILED'
    second=retry(root,first['job_id'],files_hash=failed['files_hash'],request_id='retry-once')
    assert second['job_id']!=first['job_id']
    repeated=retry(root,first['job_id'],files_hash=failed['files_hash'],request_id='retry-once')
    assert repeated['job_id']==second['job_id']
    assert terminal(root,second['job_id'])['status']=='FAILED'
    assert status(root)['events']==1 and (root/'runtime/demo/simulation/jobs'/first['job_id']/'result.json').exists()


def test_two_cli_submitters_with_same_request_create_only_one_task(tmp_path):
    root,file=workspace(tmp_path)
    cmd=[*python_command('personal_quant'),'simulation','prepare','--workspace',str(root),'--file',str(file),'--background','--request-id','same-submit']
    children=[subprocess.Popen(cmd,cwd=root,env=python_environment(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(2)]
    results=[]
    for child in children:
        stdout,stderr=child.communicate(timeout=45);assert child.returncode==0,stderr;results.append(json.loads(stdout))
    assert results[0]['job_id']==results[1]['job_id']
    terminal(root,results[0]['job_id'])
    assert len(list_jobs(root))==1 and status(root)['events']==1


def test_invalid_task_time_is_isolated_in_readonly_list_and_ui_summary(tmp_path):
    root,_=workspace(tmp_path);folder=root/'runtime/demo/simulation/jobs/bad-time';folder.mkdir(parents=True)
    from personal_quant.ui.v20_workbench import job_rows
    for change in [{'started_at':'invalid-clock'},{'owner':'not-an-owner'},{'deadline_at':'invalid-clock'}]:
        (folder/'job.json').write_text(json.dumps({'job_id':'bad-time','owner':None,**change}))
        row=list_jobs(root)[0];assert row['status']=='UNVERIFIED'
        assert job_rows([row])[0]['任务状态']=='未知待核实'
