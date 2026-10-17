import json,time
from pathlib import Path
from test_task_recovery_v20 import workspace,terminal
from personal_quant.workspace.jobs import launch,list_jobs
from personal_quant.workspace.job_index import rebuild
from personal_quant.workspace.service import status


def test_nonbatch_total_deadline_expires_before_business_and_leaves_durable_receipt(tmp_path):
    root,file=workspace(tmp_path)
    # A valid prepare spec would create a setup; importing Python alone uses
    # more than this deliberately tiny queue+startup budget.
    file.write_bytes((Path(__file__).resolve().parents[1]/'configs/v195-option-setup.json').read_bytes())
    job=launch(root,'prepare',input_file=file,max_seconds=.001,request_id='deadline-before-work')
    row=terminal(root,job['job_id'])
    assert row['result']['code']=='TASK_DEADLINE_LIMIT' and row['job_status']=='FAILED'
    assert job['deadline_at'] and status(root)['events']==1
    assert not list((root/'runtime/demo/simulation/setups').glob('*/setup-manifest.json'))


def test_task_index_rebuild_order_pagination_and_corruption_fallback_are_readonly(tmp_path):
    root,_=workspace(tmp_path);runtime=root/'runtime/demo'
    for identity,clock in [('old','2024-01-01T00:00:00Z'),('new','2024-02-01T00:00:00Z')]:
        folder=runtime/'simulation/jobs'/identity;folder.mkdir(parents=True)
        (folder/'job.json').write_text(json.dumps({'job_id':identity,'owner':None,'started_at':clock}))
        (folder/'result.json').write_text(json.dumps({'status':'CREATED'}))
    result=rebuild(root);assert result['tasks']==2 and result['financial_events_added']==0
    assert list_jobs(root,limit=1)[0]['job_id']=='new'
    assert list_jobs(root,limit=1,offset=1)[0]['job_id']=='old'
    index=runtime/'simulation/job-index.json';index.write_text('{')
    assert len(list_jobs(root))==2 and all(r['task_index']['status']=='REBUILD_REQUIRED' for r in list_jobs(root))
    rebuild(root);assert list_jobs(root)[0]['job_id']=='new'
    assert status(root)['events']==1


def test_successful_worker_transport_can_return_blocked_business_without_claiming_completion(tmp_path):
    root,_=workspace(tmp_path);folder=root/'runtime/demo/simulation/jobs/blocked';folder.mkdir(parents=True)
    (folder/'job.json').write_text(json.dumps({'job_id':'blocked','owner':None}))
    (folder/'result.json').write_text(json.dumps({'status':'BLOCKED','transport_status':'SUCCEEDED','code':'INSUFFICIENT_CASH'}))
    row=list_jobs(root)[0]
    assert row['job_status']=='SUCCEEDED' and row['run_status']=='BLOCKED'
    assert status(root)['events']==1


def test_synchronous_deadline_cleans_a_separate_owned_descendant_group(tmp_path):
    import subprocess,sys
    import pytest
    from personal_quant.processes import run_owned
    from personal_quant.research.service import process_identity
    from personal_quant.common import QuantError
    file=tmp_path/'child.pid'
    child_code='import time;time.sleep(60)'
    parent_code="import subprocess,sys,time;from pathlib import Path;p=subprocess.Popen([sys.executable,'-c',%r],start_new_session=True);Path(%r).write_text(str(p.pid));time.sleep(60)"%(child_code,str(file))
    with pytest.raises(QuantError) as error:run_owned([sys.executable,'-c',parent_code],cwd=tmp_path,timeout_seconds=.1)
    assert error.value.code=='TASK_DEADLINE_LIMIT' and file.exists()
    end=time.monotonic()+2
    while process_identity(int(file.read_text())) and time.monotonic()<end:time.sleep(.05)
    assert process_identity(int(file.read_text())) is None


def test_dead_parent_review_cannot_hide_a_still_running_registered_batch_child(tmp_path):
    import subprocess,sys,pytest
    from personal_quant.research.service import process_identity
    from personal_quant.workspace.jobs import review
    from personal_quant.workspace.batch import _stop
    from personal_quant.common import QuantError
    root,_=workspace(tmp_path);runtime=root/'runtime/demo';folder=runtime/'simulation/jobs/dead-parent';folder.mkdir(parents=True)
    old={'pid':99999999,'start_ticks':'old','boot_id':'old'}
    (folder/'job.json').write_text(json.dumps({'job_id':'dead-parent','owner':old,'started_at':'2024-01-01T00:00:00Z'}))
    (folder/'result.json').write_text(json.dumps({'status':'FAILED'}))
    child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],start_new_session=True)
    try:
        ownerfile=runtime/'simulation/jobs/batch-child-known/owner.json';ownerfile.parent.mkdir()
        ownerfile.write_text(json.dumps({'parent_owner':old,'owner':process_identity(child.pid)}))
        row=list_jobs(root)[0];assert row['status']=='INTERRUPTED' and row['active_descendants']
        with pytest.raises(QuantError) as error:review(root,'dead-parent',{'files_hash':row['files_hash'],'reason':'parent stopped','confirm_no_inflight':True})
        assert error.value.code=='JOB_CHILD_RUNNING' and not (folder/'review.json').exists()
    finally:_stop(child)
    row=list_jobs(root)[0]
    review(root,'dead-parent',{'files_hash':row['files_hash'],'reason':'owned child now stopped','confirm_no_inflight':True})
    assert (folder/'result.json').exists() and status(root)['events']==1


def test_failed_resume_receipt_retains_exact_last_committed_checkpoint(tmp_path):
    from personal_quant.config import Config
    from personal_quant.workspace.service import create,worker
    root=tmp_path/'etf';create(root,{'schema_version':1,'kind':'etf','account_id':'demo-account','initial_cash':100000},Config.load(Path(__file__).resolve().parents[1]/'configs/demo.toml'))
    run=worker(root,'start');worker(root,'step',run['run_id'],'2024-07-01')
    job=launch(root,'resume',run['run_id'],'2024-06-30',request_id='invalid-earlier-date')
    row=terminal(root,job['job_id'])
    checkpoint=row['result']['last_committed_checkpoint']
    assert checkpoint['run_id']==run['run_id'] and checkpoint['session']=='2024-07-01' and checkpoint['ledger_seq']==1
    assert status(root)['events']==1


def test_unexpected_worker_exception_has_failure_receipt_and_retained_traceback(tmp_path):
    import subprocess,sys
    from personal_quant.processes import python_environment
    root,_=workspace(tmp_path);folder=root/'runtime/demo/simulation/jobs/injected-exception';folder.mkdir(parents=True)
    target=folder/'result.json'
    code="import sys;from personal_quant.workspace import worker;sys.argv=['worker','prepare','--result-file',%r];worker.run=lambda *a,**k:(_ for _ in ()).throw(TypeError('independent injected coding error'));worker.main()"%str(target)
    child=subprocess.run([sys.executable,'-P','-c',code],cwd=root,env=python_environment(),capture_output=True,text=True,start_new_session=True,timeout=45)
    assert child.returncode==1
    result=json.loads(target.read_text());assert result['status']=='FAILED' and result['code']=='UNEXPECTED_WORKER_ERROR'
    assert json.loads(child.stderr)['code']=='UNEXPECTED_WORKER_ERROR'
    assert 'TypeError' in (folder/'worker-traceback.log').read_text() and status(root)['events']==1
