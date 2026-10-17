"""Rebuildable task ordering projection; financial decisions read original receipts."""
import hashlib
import json
from pathlib import Path
from ..common import QuantError,digest,now_utc,utc,write_json
from ..execution.daily import daily_lock
from .service import read_workspace


def _paths(runtime):
    return sorted((runtime/'simulation/jobs').glob('*/job.json'))


def write_index(root,runtime,workspace_id):
    rows=[]
    for file in _paths(runtime):
        started=None;fingerprint=None
        try:
            if file.is_symlink():raise ValueError('linked header')
            raw=file.read_bytes();body=json.loads(raw);fingerprint=hashlib.sha256(raw).hexdigest()
            if not isinstance(body,dict) or body['job_id']!=file.parent.name:raise ValueError('identity')
            if body.get('started_at'):started=utc(body['started_at']).isoformat()
        except (OSError,ValueError,KeyError,TypeError,QuantError):pass
        rows.append({'job_id':file.parent.name,'started_at':started,'header_sha256':fingerprint})
    # Invalid headers remain visible first; normal tasks show newest first.
    rows.sort(key=lambda r:(r['started_at'] is None,r['started_at'] or '',r['job_id']),reverse=True)
    body={'schema_version':1,'workspace_id':workspace_id,'built_at':now_utc(),'entries':rows,
          'meaning':'派生排序索引；展示仍读取原始任务/回执，不作为资金或在途状态依据'}
    body['index_hash']=digest(body);write_json(runtime/'simulation/job-index.json',body)
    return {'status':'REBUILT','tasks':len(rows),'index_hash':body['index_hash'],'financial_events_added':0}


def rebuild(directory):
    root,identity,config,_=read_workspace(directory);runtime=root/config.runtime_dir
    from .jobs import submission_lock
    with submission_lock(runtime):return write_index(root,runtime,identity['workspace_id'])


def paths(root,runtime,workspace_id):
    actual=_paths(runtime);index=runtime/'simulation/job-index.json'
    try:
        if index.is_symlink():raise ValueError('linked index')
        body=json.loads(index.read_text())
        if (body['schema_version']!=1 or body['workspace_id']!=workspace_id
                or digest({k:v for k,v in body.items() if k!='index_hash'})!=body['index_hash']
                or {r['job_id'] for r in body['entries']}!={p.parent.name for p in actual}
                or len(body['entries'])!=len(actual)):
            raise ValueError('index identity or membership')
        files={p.parent.name:p for p in actual}
        return [files[row['job_id']] for row in body['entries']],{'status':'INDEX_SNAPSHOT','built_at':body['built_at']}
    except (OSError,ValueError,KeyError,TypeError):
        return actual,{'status':'REBUILD_REQUIRED','built_at':None}
