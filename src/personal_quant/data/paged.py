"""Provider-neutral recorded-page ingestion; adapters own authorization and schemas."""
from pathlib import Path
import json
import time
from ..common import QuantError,digest,write_json,now_utc
from ..locks import publication_lock


class TransientPageError(Exception):
    """An adapter may raise this for bounded retryable transport/rate failures."""


def ingest(adapter,directory,request,*,max_pages=100,max_attempts=3,backoff_seconds=.1,sleep=time.sleep):
    if type(max_pages) is not int or not 1<=max_pages<=10000 or type(max_attempts) is not int or not 1<=max_attempts<=5 or not 0<=backoff_seconds<=10:
        raise QuantError('INVALID_PROVIDER_BUDGET','分页/重试预算无效')
    root=Path(directory);root.mkdir(parents=True,exist_ok=True)
    identity={'provider':adapter.provider_id,'schema_version':adapter.schema_version,'request':request}
    key=digest(identity);folder=root/key
    with publication_lock(root):
        folder.mkdir(exist_ok=True);state_path=folder/'cursor.json'
        state=json.loads(state_path.read_text()) if state_path.exists() else {'identity':identity,'cursor':None,'pages':[],'complete':False}
        if state['identity']!=identity:raise QuantError('PROVIDER_REQUEST_CHANGED','增量请求身份不一致')
        if state['complete']:return {**state,'repeated':True}
        seen={p['cursor_hash'] for p in state['pages']}
        for _ in range(max_pages):
            cursor=state['cursor'];cursor_hash=digest(cursor)
            if cursor_hash in seen:raise QuantError('PROVIDER_CURSOR_LOOP','供应商游标未前进，保留已提交页')
            for attempt in range(max_attempts):
                try:page=adapter.fetch(request,cursor);break
                except TransientPageError as exc:
                    if attempt+1==max_attempts:raise QuantError('PROVIDER_RETRIES_EXHAUSTED','有限重试耗尽，已提交游标保留') from exc
                    sleep(backoff_seconds*(2**attempt))
            if not isinstance(page,dict) or set(page)!={'records','next_cursor','evidence_reference'} or not isinstance(page['records'],list) or not isinstance(page['evidence_reference'],str):
                raise QuantError('INVALID_PROVIDER_PAGE','适配器页需记录、游标及原始凭据引用')
            rows=[]
            for record in page['records']:
                normalized=adapter.normalize(record)
                if not isinstance(normalized,dict) or not isinstance(normalized.get('record_id'),str) or not normalized['record_id']:
                    raise QuantError('INVALID_PROVIDER_RECORD','适配器需稳定记录ID，重叠修订保留原版本')
                rows.append(normalized)
            body={'cursor_hash':cursor_hash,'records':rows,'next_cursor':page['next_cursor'],
                  'evidence_reference':page['evidence_reference'],'received_at':now_utc()}
            # Financial consumers still validate units and PIT qualification. A
            # recorded page never grants execution or real-source permission.
            file=f'page-{len(state["pages"]):06d}.json';write_json(folder/file,body)
            state['pages'].append({'file':file,'hash':digest(body),'cursor_hash':cursor_hash})
            state['cursor']=page['next_cursor'];state['complete']=page['next_cursor'] is None
            write_json(state_path,state);seen.add(cursor_hash)
            if state['complete']:return {**state,'repeated':False}
        return {**state,'status':'PAGE_BUDGET_PAUSED'}


def materialize(directory,key):
    import re
    if not isinstance(key,str) or not re.fullmatch(r'[0-9a-f]{64}',key):raise QuantError('INVALID_PROVIDER_ID','供应商包需确切内容请求ID')
    folder=Path(directory)/key
    if folder.is_symlink() or (folder/'cursor.json').is_symlink():raise QuantError('UNSAFE_PROVIDER_PAGE','记录页不能是链接')
    state=json.loads((folder/'cursor.json').read_text());latest={};revisions=[]
    if digest(state['identity'])!=key:raise QuantError('PROVIDER_REQUEST_CHANGED','记录身份与目录不同')
    for ref in state['pages']:
        file=folder/ref['file']
        if file.is_symlink() or not file.resolve().is_relative_to(folder.resolve()):raise QuantError('UNSAFE_PROVIDER_PAGE','记录页越界或是链接')
        body=json.loads(file.read_text())
        if digest(body)!=ref['hash']:raise QuantError('PROVIDER_PAGE_CHANGED','已登记原始页内容改变')
        for row in body['records']:
            identity=row['record_id']
            if identity in latest and latest[identity]!=row:revisions.append({'record_id':identity,'previous_hash':digest(latest[identity]),'new_hash':digest(row)})
            latest[identity]=row
    return {'records':list(latest.values()),'revisions':revisions,'complete':state['complete'],
            'source_qualification':'UNVERIFIED','executable':False}
