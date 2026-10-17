"""Immutable declared security identities; registration grants no source licence."""
import json
import os
from pathlib import Path
import shutil
from uuid import uuid4

from ..common import QuantError, canonical, decimal as D, digest, now_utc, utc, write_json
from ..locks import publication_lock

FIELDS={'schema_version','security_id','instrument_type','ticker_history','exchange','calendar','timezone',
        'currency','trade_unit','valid_from','valid_until','corporate_action_refs','source_qualification_refs','source_type'}


def normalize(body):
    if (not isinstance(body,dict) or set(body)!=FIELDS or type(body['schema_version']) is not int
            or body['schema_version']!=1 or any(not isinstance(body[k],str) or not body[k].strip() for k in
                ('security_id','instrument_type','exchange','calendar','timezone','currency','source_type'))
            or body['instrument_type'] not in {'stock','etf','inverse_etf'}
            or body['source_type'] not in {'synthetic','declared'}
            or body['currency']!='USD' or body['timezone']!='America/New_York'
            or not isinstance(body['ticker_history'],list) or not body['ticker_history']):
        raise QuantError('INVALID_SECURITY_IDENTITY','证券身份需完整显式字段及支持的美国证券/USD口径')
    begin,end=utc(body['valid_from']),utc(body['valid_until'])
    if begin>=end or D(body['trade_unit'])<=0:
        raise QuantError('INVALID_SECURITY_IDENTITY','证券身份窗口和交易单位无效')
    for key in ('corporate_action_refs','source_qualification_refs'):
        refs=body[key]
        if not isinstance(refs,list) or any(not isinstance(x,str) or not x for x in refs) or len(set(refs))!=len(refs):
            raise QuantError('INVALID_SECURITY_IDENTITY','行动/来源资格引用须为显式不重复ID列表')
    intervals=[]
    for item in body['ticker_history']:
        if (not isinstance(item,dict) or set(item)!={'ticker','valid_from','valid_until'}
                or not isinstance(item['ticker'],str) or not item['ticker']):
            raise QuantError('INVALID_SECURITY_IDENTITY','证券代码历史须有代码及明确有效窗口')
        left,right=utc(item['valid_from']),utc(item['valid_until'])
        if not begin<=left<right<=end or any(max(left,a)<min(right,b) for a,b in intervals):
            raise QuantError('INVALID_SECURITY_IDENTITY','代码历史窗口不能重叠或越出身份窗口')
        intervals.append((left,right))
    return json.loads(canonical(body))


def load(runtime,version):
    if not isinstance(version,str) or len(version)!=64 or any(c not in '0123456789abcdef' for c in version):
        raise QuantError('INVALID_SECURITY_VERSION','证券版本须为内容哈希')
    root=Path(runtime)/'hedging/securities';directory=root/version
    try:
        if any(p.is_symlink() for p in (root.parent,root,directory,directory/'identity.json',directory/'record.json')):
            raise QuantError('CORRUPT_SECURITY_REGISTRY','证券登记不能引用链接')
        body=normalize(json.loads((directory/'identity.json').read_text()))
        record=json.loads((directory/'record.json').read_text())
        if (digest(body)!=version or record['version_hash']!=version or record['schema_version']!=1
                or record['security_id']!=body['security_id']
                or record['record_hash']!=digest({k:v for k,v in record.items() if k!='record_hash'})):
            raise QuantError('CORRUPT_SECURITY_REGISTRY','证券身份/登记哈希不一致')
        utc(record['registered_at'])
        return {'identity':body,'record':record}
    except (OSError,KeyError,TypeError,ValueError) as exc:
        if isinstance(exc,QuantError) and exc.code=='CORRUPT_SECURITY_REGISTRY':raise
        raise QuantError('CORRUPT_SECURITY_REGISTRY','证券登记缺失或内容改变') from exc


def catalog(runtime,environment):
    root=Path(runtime)/'hedging/securities'
    if root.is_symlink() or root.parent.is_symlink():raise QuantError('CORRUPT_SECURITY_REGISTRY','证券登记目录不能是链接')
    if not root.exists():return []
    result=[]
    for path in sorted(root.iterdir()):
        if path.name.startswith('.pending-'):continue
        item=load(runtime,path.name)
        if item['record']['environment']!=environment:
            raise QuantError('CORRUPT_SECURITY_REGISTRY','证券登记环境不匹配')
        result.append(item)
    return result


def register(runtime,environment,body):
    body=normalize(body)
    if environment not in {'demo','paper','real'} or environment!='demo' and body['source_type']=='synthetic':
        raise QuantError('ENVIRONMENT_MISMATCH','合成证券身份不能登记为实际/模拟跟踪证券')
    version=digest(body);root=Path(runtime)/'hedging/securities';destination=root/version
    with publication_lock(runtime):
        existing=catalog(runtime,environment)
        for item in existing:
            other=item['identity']
            if other['security_id']==body['security_id']:
                if any(other[k]!=body[k] for k in ('instrument_type','exchange','calendar','timezone','currency')):
                    raise QuantError('SECURITY_IDENTITY_CONFLICT','稳定证券ID不能改指另一种资产/市场')
            else:
                for a in body['ticker_history']:
                    for b in other['ticker_history']:
                        if a['ticker']==b['ticker'] and max(utc(a['valid_from']),utc(b['valid_from']))<min(utc(a['valid_until']),utc(b['valid_until'])):
                            raise QuantError('SECURITY_TICKER_CONFLICT','同一有效窗口的代码不能指向两个稳定证券ID')
        if destination.exists():return load(runtime,version)
        root.mkdir(parents=True,exist_ok=True);pending=root/('.pending-'+uuid4().hex);pending.mkdir()
        try:
            record={'schema_version':1,'version_hash':version,'security_id':body['security_id'],
                    'environment':environment,'registered_at':now_utc(),
                    'qualification':'declared_identity_only','executable':False}
            record['record_hash']=digest(record)
            write_json(pending/'identity.json',body);write_json(pending/'record.json',record)
            os.rename(pending,destination)
        finally:
            if pending.exists():shutil.rmtree(pending)
    return load(runtime,version)


def resolve(runtime,environment,versions,mapping,as_of,knowledge_cutoff):
    if not isinstance(versions,dict) or set(versions)!=set(mapping):
        raise QuantError('INVALID_SECURITY_BINDING','每个证券代码必须绑定显式身份版本')
    result={};clock,known=utc(as_of),utc(knowledge_cutoff)
    for symbol,version in versions.items():
        item=load(runtime,version);body=item['identity'];record=item['record']
        if record['environment']!=environment or body['security_id']!=mapping[symbol]:
            raise QuantError('SECURITY_BINDING_CONFLICT','身份版本与账户环境或稳定ID不匹配')
        if utc(record['registered_at'])>known:
            raise QuantError('SECURITY_NOT_KNOWN','知识截止时尚未登记该身份版本')
        if not any(x['ticker']==symbol and utc(x['valid_from'])<=clock<utc(x['valid_until']) for x in body['ticker_history']):
            raise QuantError('SECURITY_NOT_ACTIVE','覆盖时点该代码不属于所选身份版本')
        result[symbol]={'version_hash':version,'record_hash':record['record_hash'],
                        'qualification':record['qualification']}
    return result


def assess(book,account_id,request):
    """Join declared identities to immutable source evidence and active account actions."""
    fields={'security_versions','security_ids','as_of','knowledge_cutoff','valuation_snapshot_id','ledger_seq'}
    if not isinstance(request,dict) or set(request)!=fields or type(request['ledger_seq']) is not int:
        raise QuantError('INVALID_SECURITY_ASSESSMENT','需确切身份/原价快照、账户前缀和知识时点')
    book._require_account(account_id)
    if book.connection.execute('SELECT version FROM schema_version').fetchone()[0]<5:
        raise QuantError('V19_NOT_ENABLED','证券资格关联需要显式启用v1.9')
    clock,known=utc(request['as_of']),utc(request['knowledge_cutoff'])
    if known>utc(now_utc()) or clock>known or not 0<=request['ledger_seq']<=book.sequence(account_id):
        raise QuantError('INVALID_SECURITY_ASSESSMENT','资格检查时点或账户前缀无效')
    if any(utc(row[0])>known for row in book.connection.execute(
            'SELECT recorded_at FROM events WHERE account_id=? AND seq<=?',(account_id,request['ledger_seq']))):
        raise QuantError('LEDGER_NOT_KNOWN','行动凭据尚未在知识截止时收到')
    bindings=resolve(book.path.parent,book.environment,request['security_versions'],request['security_ids'],clock,known)
    from ..data.store import DataStore
    from ..data.qualification import require_qualification,load_evidence
    store=DataStore(book.path.parent/'data');frame,metadata,_=store.load(request['valuation_snapshot_id'])
    events={e['event_id']:e for e in book.active_events(account_id,clock,ledger_seq=request['ledger_seq'])}
    results={};checks=[]
    for symbol,binding in bindings.items():
        identity=load(book.path.parent,binding['version_hash'])['identity'];issues=[];source=None;actions=[]
        if metadata['price_basis']!=['unadjusted']:issues.append('RAW_SECURITY_UNITS_REQUIRED')
        if identity['calendar']!='XNYS' or identity['currency']!=metadata['currency'] or identity['timezone']!=metadata['market_timezone']:
            issues.append('SECURITY_MARKET_CONFLICT')
        if symbol not in metadata['symbols']:issues.append('MISSING_SECURITY_MARK')
        if identity['source_type']=='synthetic' or metadata['data_type']=='synthetic':issues.append('SYNTHETIC_IDENTITY_OR_SOURCE')
        try:
            source=require_qualification(book.connection,book.path.parent,metadata,store.series_identity(metadata),known,knowledge_cutoff=known)
            if source['qualification_id'] not in identity['source_qualification_refs']:
                issues.append('SECURITY_SOURCE_NOT_BOUND')
            # Every declared reference must exist; stale rejected references do not grant current qualification.
            for reference in identity['source_qualification_refs']:load_evidence(book.connection,book.path.parent,reference,known)
        except QuantError as exc:issues.append(exc.code)
        for reference in identity['corporate_action_refs']:
            event=events.get(reference)
            if (event is None or event['symbol']!=symbol or event['kind'] not in {'SPLIT','DIVIDEND_ACCRUAL','DIVIDEND_PAYMENT'}):
                issues.append('SECURITY_ACTION_NOT_BOUND');continue
            actions.append({'event_id':reference,'content_hash':digest(event),'kind':event['kind']})
        results[symbol]={'identity_basis':binding,'source_assessment':source,'actions':actions,
                         'status':'BLOCKED' if issues else 'QUALIFIED','checks':sorted(set(issues))}
        checks.extend(code+':'+symbol for code in issues)
    result={'schema_version':1,'artifact_type':'security_qualification_assessment','account_id':account_id,
            'environment':book.environment,'request':request,'securities':results,'checks':sorted(set(checks)),
            'status':'BLOCKED' if checks else 'QUALIFIED','executable':False,
            'meaning':'来源、身份及所引用行动的关联检查；不证明账户交易权限或替代计划风险检查'}
    result['assessment_id']=digest(result);return result
