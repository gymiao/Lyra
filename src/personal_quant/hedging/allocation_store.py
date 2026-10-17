"""Transactional coverage-reference revisions, without financial reservations."""
import json

from ..common import QuantError,canonical,digest,now_utc
from ..locks import publication_lock
from .coverage_service import account_coverage

FIELDS={'schema_version','request_id','expected_version','expected_resource_hash','coverage_request','changes','retire_ids','reason'}
PREFIX='hedge-allocation:'


def resources(book,account_id):
    """Fingerprint more than the event sequence: plans, bindings and qualifications."""
    tables={r[0] for r in book.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    basis={'account_id':account_id,'sequence':book.sequence(account_id)}
    for name in ('plans','option_plans','strategy_bindings','source_qualifications','data_roles'):
        if name in tables:
            columns={r[1] for r in book.connection.execute('PRAGMA table_info('+name+')')}
            rows=book.connection.execute('SELECT * FROM '+name+(' WHERE account_id=?' if 'account_id' in columns else ''),
                                         (account_id,) if 'account_id' in columns else ())
            basis[name]=sorted([dict(r) for r in rows],key=canonical)
    basis['option_audits']=sorted([dict(r) for r in book.connection.execute(
        "SELECT task_id,status,details FROM tasks WHERE task_id LIKE 'option-%' OR task_id LIKE 'hedge-%'")],key=canonical)
    return digest(basis)


def history(book,account_id):
    book._require_account(account_id);records=[]
    for row in book.connection.execute('SELECT details FROM tasks WHERE task_id LIKE ?', (PREFIX+'%',)):
        try:
            item=json.loads(row[0])
            if item['account_id']!=account_id:continue
            if (item['environment']!=book.environment or item['record_hash']!=digest({k:v for k,v in item.items() if k!='record_hash'})
                    or item['version_hash']!=digest(item['version_basis'])):
                raise ValueError('identity')
            records.append(item)
        except (KeyError,TypeError,ValueError) as exc:
            raise QuantError('CORRUPT_ALLOCATION_HISTORY','保护分配记录缺失或哈希改变') from exc
    records.sort(key=lambda r:r['revision'])
    previous=None
    for index,item in enumerate(records,1):
        if item['revision']!=index or item['previous_version']!=previous:
            raise QuantError('CORRUPT_ALLOCATION_HISTORY','保护分配版本链中断或重复')
        previous=item['version_hash']
        from .parent_bindings import validate
        validate(book,account_id,item)
    return records


def latest(book,account_id):
    records=history(book,account_id)
    return records[-1] if records else None


def current_basis(book,account_id):
    with publication_lock(book.path.parent),book.transaction():
        old=latest(book,account_id)
        return {'status':'CURRENT','account_id':account_id,'ledger_seq':book.sequence(account_id),
                'version_hash':old['version_hash'] if old else None,'resource_hash':resources(book,account_id),
                'revision':old['revision'] if old else 0,'executable':False}


def prepare(book,account_id,request):
    if (not isinstance(request,dict) or type(request.get('schema_version')) is not int
            or (request['schema_version'],set(request)) not in ((1,FIELDS),(2,FIELDS|{'parent_versions'}))
            or any(not isinstance(request[k],str) or not request[k].strip() for k in ('request_id','reason'))
            or not isinstance(request['changes'],list) or any(not isinstance(r,dict) for r in request['changes'])
            or not isinstance(request['retire_ids'],list) or any(not isinstance(x,str) or not x for x in request['retire_ids'])
            or len(set(request['retire_ids']))!=len(request['retire_ids'])
            or not isinstance(request['coverage_request'],dict)):
        raise QuantError('INVALID_ALLOCATION_UPDATE','保护分配更新需明确版本/资源依据、变化、退出ID及原因')
    old=latest(book,account_id);version=old['version_hash'] if old else None
    if old and old['schema_version']==2 and request['schema_version']!=2:
        raise QuantError('HEDGE_PARENT_BINDINGS_REQUIRED','已严格绑定的保护集合不能降级为无父版本引用')
    if request['expected_version']!=version:
        raise QuantError('STALE_ALLOCATION_VERSION','保护分配已被其他任务修改，请重新预检')
    current_resources=resources(book,account_id)
    if request['expected_resource_hash']!=current_resources:
        raise QuantError('STALE_HEDGE_RESOURCES','账户/计划/策略绑定或来源资格已变化，请重新预检')
    query=dict(request['coverage_request'])
    if 'security_versions' not in query:
        raise QuantError('REGISTERED_SECURITY_REQUIRED','持久分配必须绑定明确登记的证券版本')
    if query.get('ledger_seq')!=book.sequence(account_id):
        raise QuantError('STALE_LEDGER_SEQUENCE','持久分配不能使用已经落后的账户前缀')
    if query.get('allocations')!=[]:
        raise QuantError('INVALID_ALLOCATION_UPDATE','coverage_request.allocations应为空，由完整持久分配集生成')
    rows={r['allocation_id']:r for r in old['allocations']} if old else {}
    for identity in request['retire_ids']:
        if identity not in rows:raise QuantError('UNKNOWN_ALLOCATION','退出分配ID不存在')
        del rows[identity]
    changed=set()
    for item in request['changes']:
        identity=item.get('allocation_id')
        if not isinstance(identity,str) or not identity or identity in changed:
            raise QuantError('DUPLICATE_ALLOCATION','变化列表需不重复分配ID')
        changed.add(identity)
        if identity in request['retire_ids']:
            raise QuantError('INVALID_ALLOCATION_UPDATE','同一ID不能同时退出和修改')
        if identity in rows and any(item.get(k)!=rows[identity][k] for k in ('parent_id','security_id','contract_id','contract_version','role')):
            raise QuantError('ALLOCATION_IDENTITY_CONFLICT','不能借修改分配ID变更父意图/资产/合约或角色')
        rows[identity]=item
    query['allocations']=[rows[k] for k in sorted(rows)]
    coverage=account_coverage(book,account_id,query)
    parent_basis=None
    if request['schema_version']==2:
        from .parent_bindings import resolve
        parent_basis=resolve(book,account_id,query['allocations'],request['parent_versions'],changed=changed,old=old)
    # References do not cancel manual orders: all outstanding resources still
    # reside in native plans. Retiring a reference never releases those funds.
    revision=old['revision']+1 if old else 1
    basis={'account_id':account_id,'environment':book.environment,'revision':revision,
           'previous_version':version,'coverage_id':coverage['coverage_id'],'allocations':query['allocations']}
    extra={}
    if parent_basis is not None:
        extra={'parent_versions':request['parent_versions'],'parent_basis':parent_basis}
        basis.update(extra)
    return {'revision':revision,'previous_version':version,'version_hash':digest(basis),'version_basis':basis,
            'allocations':query['allocations'],'coverage':coverage,'coverage_request':query,**extra,
            'parent_binding_status':'BOUND' if parent_basis is not None else 'LEGACY_UNBOUND',
            'resource_hash':current_resources,'executable':False,'creates_reservations':False}


def update(book,account_id,request,*,commit=False):
    with publication_lock(book.path.parent),book.transaction():
        key=PREFIX+digest({'account_id':account_id,'request_id':request.get('request_id') if isinstance(request,dict) else None})
        previous=book.connection.execute('SELECT details FROM tasks WHERE task_id=?',(key,)).fetchone()
        if previous:
            record=json.loads(previous[0]);history(book,account_id)
            if record['request_hash']!=digest(request):
                raise QuantError('ALLOCATION_REQUEST_CONFLICT','相同请求ID对应不同更新内容')
            return record
        prepared=prepare(book,account_id,request)
        if not commit:return {'status':'PREVIEW',**prepared}
        record={'schema_version':request['schema_version'],'status':'COMMITTED','account_id':account_id,'environment':book.environment,
                'request_id':request['request_id'],'request_hash':digest(request),'request':request,
                'recorded_at':now_utc(),**prepared}
        record['record_hash']=digest(record)
        book.connection.execute('INSERT INTO tasks VALUES(?,?,?,?)',(key,'COMMITTED',canonical(record),record['recorded_at']))
        return record


def validate_references(root,book):
    from .securities import load
    for row in book.connection.execute('SELECT id FROM accounts'):
        for record in history(book,row[0]):
            from .parent_bindings import validate
            validate(book,row[0],record)
            coverage=record['coverage']
            basis=digest([dict(r) for r in book.connection.execute(
                'SELECT seq,event_id,content_hash,effective_at,recorded_at,payload FROM events WHERE account_id=? AND seq<=? ORDER BY seq',
                (row[0],coverage['ledger_seq']))])
            if basis!=coverage['ledger_basis_hash']:
                raise QuantError('CORRUPT_ALLOCATION_HISTORY','分配引用的原账本前缀改变')
            for item in coverage['security_identity_basis'].values():
                if load(root,item['version_hash'])['record']['record_hash']!=item['record_hash']:
                    raise QuantError('CORRUPT_ALLOCATION_HISTORY','分配引用的证券登记改变')
