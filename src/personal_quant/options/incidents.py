"""Explicit fact-backed review of frozen receipt anomalies; never waive live risk."""
import hashlib
import json
from pathlib import Path
import shutil
from uuid import uuid4
from ..common import QuantError,digest,now_utc,utc,decimal as D
from ..locks import publication_lock,publish_directory
from .receipt_risk import history

PREFIX='option-incident-review:'
FIELDS={'schema_version','request_id','incident_id','expected_hash','expected_sequence','as_of',
        'recovery_event_ids','reconciliation_id','reviewer','reason','evidence_type','evidence_files'}


def _financial_issues(state):
    """Actual obligations, without mixing mutable plan reservations into facts."""
    issues=[]
    if D(state['settled_cash'])-D(state['payables'])<D(state.get('option_cash_collateral',0)):
        issues.append('实际现金不足以履行支付/期权担保义务')
    if any(D(q)<0 for q in state['positions'].values()):issues.append('实际股票交割形成负持仓')
    for symbol,q in state.get('option_covered_shares',{}).items():
        if D(state['positions'].get(symbol,0))<D(q):issues.append('实际备兑股份不足：'+symbol)
    return issues


def _facts(book,account_id,as_of,sequence=None):
    """Evidence includes original and reversal rows; balances use active_events."""
    sequence=book.sequence(account_id) if sequence is None else sequence
    return [dict(json.loads(row['payload']),seq=row['seq']) for row in book.connection.execute(
        'SELECT seq,payload FROM events WHERE account_id=? AND effective_at<=? AND seq<=? ORDER BY seq',
        (account_id,utc(as_of).isoformat(),sequence))]


def _incidents(book,account_id,as_of):
    result=[]
    for audit in history(book,account_id):
        if audit['risk_history'] is None:continue
        for view in audit['risk_history']['prefixes']:
            issues=_financial_issues(view['snapshot'])
            if not issues or utc(view['effective_at'])>utc(as_of):continue
            basis={'account_id':account_id,'audit_task_id':audit['audit_task_id'],
                   'event_id':view['event_id'],'prefix_hash':view['ledger_prefix_hash']}
            result.append({'incident_id':digest(basis),'basis':basis,'view_hash':digest(view),
                           'view':view,'financial_issues':issues,'status':'OPEN'})
    return result


def _files(directory,files):
    if not isinstance(files,dict) or not files:raise QuantError('INCIDENT_EVIDENCE_REQUIRED','核实需提供非空凭据文件及SHA256')
    if Path(directory).is_symlink():raise QuantError('UNSAFE_INCIDENT_EVIDENCE','凭据目录不能是符号链接')
    root=Path(directory).resolve();result={}
    for name,expected in files.items():
        if not isinstance(name,str) or not name or Path(name).name!=name or '\\' in name or name in {'.','..'}:
            raise QuantError('UNSAFE_INCIDENT_EVIDENCE','凭据仅接受目录内普通文件名')
        path=root/name
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
            raise QuantError('UNSAFE_INCIDENT_EVIDENCE','凭据必须为目录内普通文件')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
            raise QuantError('CORRUPT_INCIDENT_REVIEW','核实凭据文件缺失或哈希改变')
        result[name]=path
    return result


def reviews(book,account_id):
    result=[]
    for row in book.connection.execute("SELECT task_id,details FROM tasks WHERE task_id LIKE ? ORDER BY rowid",(PREFIX+'%',)):
        value=json.loads(row['details'])
        required={'artifact_type','audit_task_id','account_id','request','request_hash','reconciliation_hash',
                  'recovery_events','snapshot','status','recorded_at','executable','meaning','review_hash'}
        if not isinstance(value,dict) or set(value)!=required or not isinstance(value.get('request'),dict) or set(value['request'])!=FIELDS:
            raise QuantError('CORRUPT_INCIDENT_REVIEW','核实凭据字段缺失或未知')
        if value['account_id']!=account_id:continue
        request=value['request']
        key=PREFIX+digest({'account_id':account_id,'request_id':request['request_id']})
        if (row['task_id']!=key or value['audit_task_id']!=key or value['review_hash']!=digest({k:v for k,v in value.items() if k!='review_hash'})
                or value['request_hash']!=digest(request)):
            raise QuantError('CORRUPT_INCIDENT_REVIEW','核实凭据身份或内容哈希改变')
        found=[i for i in _incidents(book,account_id,request['as_of']) if i['incident_id']==request['incident_id']]
        if len(found)!=1 or found[0]['view_hash']!=request['expected_hash']:
            raise QuantError('CORRUPT_INCIDENT_REVIEW','核实凭据缺少原始异常前缀')
        recon=book.connection.execute('SELECT * FROM reconciliations WHERE id=?',(request['reconciliation_id'],)).fetchone()
        if not recon or digest(dict(recon))!=value['reconciliation_hash']:
            raise QuantError('CORRUPT_INCIDENT_REVIEW','原核实对账依据缺失或改变')
        if (set(request)!=FIELDS or value['status']!='REVIEWED' or recon['account_id']!=account_id
                or recon['status']!='PASSED' or recon['ledger_seq']!=request['expected_sequence']
                or utc(recon['as_of'])!=utc(request['as_of'])
                or set(value['recovery_events'])!=set(request['recovery_event_ids'])):
            raise QuantError('CORRUPT_INCIDENT_REVIEW','核实记录状态、恢复范围或对账时点不一致')
        facts={e['event_id']:e for e in _facts(book,account_id,request['as_of'],request['expected_sequence'])}
        events={k:digest(e) for k,e in facts.items()}
        if any(events.get(k)!=v for k,v in value['recovery_events'].items()):
            raise QuantError('CORRUPT_INCIDENT_REVIEW','核实引用的恢复事实缺失或改变')
        selected=[facts[k] for k in request['recovery_event_ids']]
        if (not selected or any(e['seq']<=found[0]['view']['ledger_seq']
                               or utc(e['effective_at'])<utc(found[0]['view']['effective_at']) for e in selected)):
            raise QuantError('CORRUPT_INCIDENT_REVIEW','恢复事实不在原异常之后')
        if book.environment!='demo' and (request['evidence_type']!='actual' or any(e.get('evidence_type')!='actual' for e in selected)):
            raise QuantError('CORRUPT_INCIDENT_REVIEW','真实/前向核实缺少实际凭据')
        end=max(e['seq'] for e in selected)
        if set(request['recovery_event_ids'])!={e['event_id'] for e in facts.values() if found[0]['view']['ledger_seq']<e['seq']<=end}:
            raise QuantError('CORRUPT_INCIDENT_REVIEW','核实记录遗漏恢复前缀事实')
        final=book.snapshot(account_id,request['as_of'],ledger_seq=request['expected_sequence'])
        restored=book.snapshot(account_id,request['as_of'],ledger_seq=end)
        if _financial_issues(final) or _financial_issues(restored):
            raise QuantError('CORRUPT_INCIDENT_REVIEW','原核实前缀仍存在真实财务异常')
        if any(value['snapshot'].get(k)!=final.get(k) for k in ('settled_cash','receivables','payables','positions','option_positions')):
            raise QuantError('CORRUPT_INCIDENT_REVIEW','核实财务快照与原账本前缀不一致')
        _files(book.path.parent/'options/incident-evidence'/value['request_hash'],request['evidence_files'])
        result.append(value)
    if len({v['request']['incident_id'] for v in result})!=len(result):
        raise QuantError('CORRUPT_INCIDENT_REVIEW','同一异常存在多份冲突核实')
    return result


def status(book,account_id,as_of):
    with publication_lock(book.path.parent),book.transaction():
        book._require_account(account_id)
        items=_incidents(book,account_id,as_of)
        resolved={v['request']['incident_id']:v for v in reviews(book,account_id) if utc(v['request']['as_of'])<=utc(as_of)}
        for item in items:
            if item['incident_id'] in resolved:
                item.update(status='REVIEWED',review=resolved[item['incident_id']])
        return {'status':'BLOCKED' if any(i['status']=='OPEN' for i in items) else 'REVIEWED' if items else 'NO_ACTION',
                'incidents':items,'executable':False,'meaning':'核实保留原中间异常；不授予当前报价/压力/账户权限或自动交易资格'}


def save(book,account_id,request,evidence_directory,*,commit=False):
    with publication_lock(book.path.parent),book.transaction():
        if (not isinstance(request,dict) or set(request)!=FIELDS or request['schema_version']!=1
                or any(not isinstance(request[k],str) or not request[k].strip() for k in
                       ('request_id','incident_id','expected_hash','reviewer','reason','as_of'))
                or type(request['expected_sequence']) is not int or request['expected_sequence']<0
                or type(request['reconciliation_id']) is not int or request['reconciliation_id']<1
                or not isinstance(request['recovery_event_ids'],list) or not request['recovery_event_ids']
                or any(not isinstance(k,str) or not k for k in request['recovery_event_ids'])
                or len(set(request['recovery_event_ids']))!=len(request['recovery_event_ids'])
                or request['evidence_type'] not in {'test','actual'}):
            raise QuantError('INVALID_INCIDENT_REVIEW','核实需原异常、账户序号、明确恢复事实、对账、核实人及凭据')
        book._require_account(account_id)
        if book.environment!='demo' and request['evidence_type']!='actual':
            raise QuantError('TEST_EVIDENCE_FORBIDDEN','测试凭据不能核实真实或前向异常')
        if utc(request['as_of'])>utc(now_utc()):raise QuantError('FUTURE_ACCOUNT_EVENT','不能核实尚未发生的恢复事实')
        old=reviews(book,account_id)
        key=PREFIX+digest({'account_id':account_id,'request_id':request['request_id']})
        same=[v for v in old if v['audit_task_id']==key]
        if same:
            if same[0]['request_hash']!=digest(request):raise QuantError('EVENT_CONFLICT','同核实请求不能更换内容')
            return same[0]
        if any(v['request']['incident_id']==request['incident_id'] for v in old):
            raise QuantError('INCIDENT_ALREADY_REVIEWED','原异常已经核实；不能覆盖历史核实依据')
        if book.sequence(account_id)!=request['expected_sequence']:raise QuantError('STALE_PREVIEW','核实账户依据已变化')
        found=[i for i in _incidents(book,account_id,request['as_of']) if i['incident_id']==request['incident_id']]
        if len(found)!=1 or found[0]['view_hash']!=request['expected_hash']:
            raise QuantError('STALE_INCIDENT','原异常不存在或内容改变')
        incident=found[0]
        events={e['event_id']:e for e in _facts(book,account_id,request['as_of'])}
        selected=[]
        for identity in request['recovery_event_ids']:
            e=events.get(identity)
            if not e or e['seq']<=incident['view']['ledger_seq'] or utc(e['effective_at'])<utc(incident['view']['effective_at']):
                raise QuantError('INVALID_RECOVERY_FACT','恢复事实必须属于同一账户、在异常前缀之后且已生效')
            if book.environment!='demo' and e.get('evidence_type')!='actual':raise QuantError('TEST_EVIDENCE_FORBIDDEN','恢复事实须为实际凭据')
            selected.append(e)
        end=max(e['seq'] for e in selected)
        required={e['event_id'] for e in events.values() if incident['view']['ledger_seq']<e['seq']<=end}
        if set(request['recovery_event_ids'])!=required:
            raise QuantError('INCOMPLETE_RECOVERY_FACTS','须明确列出异常后到恢复前缀的全部已生效事实，不能遗漏抵销凭据')
        restored=book.snapshot(account_id,request['as_of'],ledger_seq=end)
        if restored['anomalies']:raise QuantError('UNRESOLVED_RECOVERY_PREFIX','所引用恢复前缀仍异常，后续事实不能替代其核实')
        state=book.snapshot(account_id,request['as_of'])
        if state['anomalies']:raise QuantError('UNRESOLVED_ACCOUNT_ANOMALY','当前资金/持仓仍异常，不能以核实理由放行')
        recon=book.connection.execute('SELECT * FROM reconciliations WHERE id=?',(request['reconciliation_id'],)).fetchone()
        if (not recon or recon['account_id']!=account_id or recon['ledger_seq']!=request['expected_sequence']
                or recon['status']!='PASSED' or utc(recon['as_of'])!=utc(request['as_of'])):
            raise QuantError('INCIDENT_RECONCILIATION_REQUIRED','需相同账户/序号/时点的通过对账')
        files=_files(evidence_directory,request['evidence_files'])
        value={'artifact_type':'option_incident_review','audit_task_id':key,'account_id':account_id,
               'request':request,'request_hash':digest(request),'reconciliation_hash':digest(dict(recon)),
               'recovery_events':{e['event_id']:digest(e) for e in selected},'snapshot':state,
               'status':'REVIEWED','recorded_at':now_utc(),'executable':False,
               'meaning':'人工核实引用恢复事实及对账；保留原异常，无财务修改/预留释放/交易授权'}
        value['review_hash']=digest(value)
        if not commit:return {**value,'status':'PREVIEW','review_hash':None}
        root=book.path.parent/'options/incident-evidence';root.mkdir(parents=True,exist_ok=True)
        target=root/value['request_hash']
        if not target.exists():
            stage=root/('.pending-'+uuid4().hex);stage.mkdir()
            try:
                for name,path in files.items():shutil.copyfile(path,stage/name)
                _files(stage,request['evidence_files']);publish_directory(stage,target)
            finally:
                if stage.exists():shutil.rmtree(stage)
        _files(target,request['evidence_files'])
        book.record_task(key,'SUCCESS',value)
        return value
