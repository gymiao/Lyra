import json
from pathlib import Path
import time
from personal_quant.config import Config
from personal_quant.workspace.service import create
from personal_quant.workspace import jobs
ROOT=Path(__file__).resolve().parents[1]


def test_background_prepare_reads_submitted_bytes_after_original_file_changes(tmp_path,monkeypatch):
    root=tmp_path/'options';create(root,{'schema_version':1,'kind':'options','account_id':'demo-account','initial_cash':'100000'},Config.load(ROOT/'configs/demo.toml'))
    file=tmp_path/'setup.json';file.write_bytes((ROOT/'configs/v195-option-setup.json').read_bytes())
    original=jobs.subprocess.Popen
    def spawn(*args,**kwargs):
        child=original(*args,**kwargs)
        file.write_text('{invalid original changed before owner handshake')
        return child
    monkeypatch.setattr(jobs.subprocess,'Popen',spawn)
    job=jobs.launch(root,'prepare',input_file=file,request_id='frozen-submission')
    end=time.monotonic()+45
    while time.monotonic()<end:
        row=next(r for r in jobs.list_jobs(root) if r['job_id']==job['job_id'])
        if row.get('result'):break
        time.sleep(.1)
    assert row['status']=='SUCCESS',row
    assert row['result']['status']=='PREPARED'
    assert Path(row['worker_input_file']).read_bytes()==(ROOT/'configs/v195-option-setup.json').read_bytes()
