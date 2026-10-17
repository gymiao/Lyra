import json
import time
from pathlib import Path
import pytest
from personal_quant.common import QuantError
from personal_quant.config import Config
from personal_quant.workspace.service import create,worker
from personal_quant.workspace.operations import submit,normalize
from personal_quant.workspace.jobs import list_jobs
ROOT=Path(__file__).resolve().parents[1]


def test_background_backup_repeated_request_and_restore_are_financially_readonly(tmp_path):
    root=tmp_path/'work space';create(root,{'schema_version':1,'account_id':'demo-account','initial_cash':'100000','kind':'etf'},Config.load(ROOT/'configs/demo.toml'))
    started=worker(root,'start');worker(root,'step',started['run_id'],'2024-07-01')
    backup=tmp_path/'backup'
    request={'operation':'backup','destination':str(backup)}
    job=submit(root,request,request_id='backup-once')
    assert submit(root,request,request_id='backup-once')['job_id']==job['job_id']
    end=time.monotonic()+60
    while time.monotonic()<end:
        row=next(r for r in list_jobs(root) if r['job_id']==job['job_id'])
        if row.get('result'):break
        time.sleep(.1)
    assert row['result']['status']=='SUCCEEDED',row
    assert row['result']['financial_events_added']==0
    file=tmp_path/'restore.json';file.write_text(json.dumps({'operation':'restore','source':str(backup),'destination':str(tmp_path/'restored')}))
    result=worker(root,'operation',input_file=file)
    assert result['status']=='SUCCEEDED'
    from personal_quant.workspace.service import status
    assert status(root)['events']==status(tmp_path/'restored')['events']==1


def test_operator_rejects_unknown_and_relative_inputs():
    with pytest.raises(QuantError):normalize({'operation':'shell','command':'anything'})
    with pytest.raises(QuantError):normalize({'operation':'backup','destination':'relative'})
