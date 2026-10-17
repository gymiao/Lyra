"""Audited imports of supplied facts, without inferring broker lifecycle notices."""
import json
from ..common import QuantError, digest, now_utc, utc
from ..locks import publication_lock
from .ledger import import_facts
from .lifecycle import resolve_pending


FIELDS={'request_id','rows','expected_sequence','expected_hash'}


def import_batch(book,account_id,request,as_of,*,_ledger_kwargs=None):
    if (not isinstance(request,dict) or set(request)!=FIELDS
            or not isinstance(request['request_id'],str) or not request['request_id'].strip()
            or not isinstance(request['rows'],list) or not request['rows']
            or any(not isinstance(row,dict) for row in request['rows'])
            or type(request['expected_sequence']) is not int or request['expected_sequence']<0
            or request['expected_hash']!=digest(request['rows'])):
        raise QuantError('INVALID_OPTION_RECEIPT_BATCH','凭据批次需稳定请求ID、非空事实数组、预检哈希及账户序号')
    book._require_account(account_id)
    clock=utc(as_of)
    if clock>utc(now_utc()):raise QuantError('FUTURE_ACCOUNT_EVENT','不能处理未来期权凭据')
    for row in request['rows']:
        if not row.get('effective_at') or utc(row['effective_at'])>clock:
            raise QuantError('FUTURE_OPTION_RECEIPT','期权事实生效时点尚未到达')
    identity='option-receipt-batch:'+digest({'account_id':account_id,'request_id':request['request_id']})
    with publication_lock(book.path.parent),book.transaction():
        old=book.connection.execute('SELECT details FROM tasks WHERE task_id=?',(identity,)).fetchone()
        if old:
            audit=json.loads(old[0])
            if audit['request_hash']!=digest(request):
                raise QuantError('EVENT_CONFLICT','同凭据批次ID不能更换内容或预检依据')
            if 'risk_history' in audit:
                from .receipt_risk import validate
                validate(book,account_id,audit['risk_history'])
            return audit
        before=book.sequence(account_id)
        result=(import_facts(book,account_id,request['rows'],expected_sequence=request['expected_sequence'])
                if _ledger_kwargs is None else book.import_events(account_id,request['rows'],request['expected_sequence'],**_ledger_kwargs))
        from .receipt_risk import capture
        audit={'artifact_type':'option_receipt_batch','account_id':account_id,
               'audit_task_id':identity,'request':request,'request_hash':digest(request),
               'result':result,'processed_at':clock.isoformat(),'recorded_at':now_utc(),
               'risk_history':capture(book,account_id,before,clock),
               'meaning':'用户提供的事实或待核实凭据；不推断到期、行权或指派，不产生订单'}
        book.record_task(identity,'SUCCESS',audit)
        return audit


def import_statement(book,account_id,rows,expected_sequence,as_of,*,coverage_through=None,coverage_source=None):
    """Shared generic CSV intake; preserve mixed stock/cash/option fact prefixes."""
    rows=list(rows)
    kwargs=dict(coverage_through=coverage_through,coverage_source=coverage_source)
    enabled=book.connection.execute('SELECT version FROM schema_version').fetchone()[0]>=5
    option_related=(any(str(r.get('kind','')).startswith('OPTION_') for r in rows) or
        (enabled and book.connection.execute("SELECT 1 FROM events WHERE account_id=? AND json_extract(payload,'$.kind') LIKE 'OPTION_%' LIMIT 1",(account_id,)).fetchone() is not None))
    if not enabled or not option_related:return book.import_events(account_id,rows,expected_sequence,**kwargs)
    if coverage_through is not None:kwargs['coverage_through']=utc(coverage_through).isoformat()
    identity=digest(dict(rows=rows,expected_sequence=expected_sequence,coverage=kwargs))
    request=dict(request_id='statement:'+identity,rows=rows,expected_sequence=expected_sequence,expected_hash=digest(rows))
    audit=import_batch(book,account_id,request,as_of,_ledger_kwargs=kwargs)
    return {**audit['result'],'receipt_audit_id':audit['audit_task_id'],
        'has_intermediate_anomaly':audit['risk_history']['has_intermediate_anomaly']}


def advance(book,account_id,as_of,*,batch=None,resolutions=None):
    """Refresh pending state on every attempt; native import audits remain immutable."""
    if book.connection.execute('SELECT version FROM schema_version').fetchone()[0]<5:
        raise QuantError('V19_NOT_ENABLED','期权凭据推进需先显式启用v1.9')
    book._require_account(account_id)
    resolutions=[] if resolutions is None else resolutions
    if not isinstance(resolutions,list) or any(
            not isinstance(item,dict) or set(item)!={'event_id','expected_sequence','expected_hash'}
            or not isinstance(item['event_id'],str) or not item['event_id']
            or type(item['expected_sequence']) is not int or item['expected_sequence']<0
            or not isinstance(item['expected_hash'],str) for item in resolutions):
        raise QuantError('INVALID_OPTION_RESOLUTIONS','解决凭据需明确事件ID、原凭据哈希及账户序号数组')
    audits=[];resolved=[];errors=[]
    try:
        if batch is not None:audits.append(import_batch(book,account_id,batch,as_of))
        for item in resolutions:
            # Do not import a future effective fact merely because terms arrived.
            row=book.connection.execute('SELECT payload FROM pending_option_events WHERE account_id=? AND event_id=?',
                (account_id,item['event_id'])).fetchone()
            if row and utc(json.loads(row[0])['effective_at'])>utc(as_of):
                raise QuantError('FUTURE_OPTION_RECEIPT','待核实事实生效时点尚未到达')
            resolved.append(resolve_pending(book,account_id,**item))
    except QuantError as exc:
        errors.append({'code':exc.code,'message':str(exc)})
    pending=[row[0] for row in book.connection.execute(
        'SELECT event_id FROM pending_option_events WHERE account_id=? ORDER BY event_id',(account_id,))]
    return {'artifact_type':'option_receipt_progress','status':'BLOCKED' if pending or errors else
            'SUCCESS' if audits or resolved else 'NO_ACTION','audits':audits,'resolutions':resolved,
            'pending_events':pending,'errors':errors,'as_of':utc(as_of).isoformat(),
            'meaning':'只推进明确提供的事实及解决请求；未核实凭据持续阻断，不根据日历虚构通知'}
