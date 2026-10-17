"""Immutable parent decisions binding policy, risk and candidate references."""
import json
from zoneinfo import ZoneInfo

from ..common import QuantError,canonical,digest,now_utc,utc
from ..locks import publication_lock
from .allocation_store import resources
from .archive import load
from .preview import preview
from .securities import resolve

PREFIX='hedge-intent:'
FIELDS={'schema_version','request_id','expected_version','expected_resource_hash','preview_request',
        'security_ids','security_versions','decision_at','knowledge_cutoff','valid_until','trigger',
        'base_strategy_version','timing','reason'}


def records(book,account_id):
    book._require_account(account_id);result=[]
    for row in book.connection.execute('SELECT details FROM tasks WHERE task_id LIKE ?', (PREFIX+'%',)):
        try:
            item=json.loads(row[0])
            if item['account_id']!=account_id:continue
            if (item['environment']!=book.environment or item['record_hash']!=digest({k:v for k,v in item.items() if k!='record_hash'})
                    or item['version_hash']!=digest(item['version_basis'])):raise ValueError('hash')
            result.append(item)
        except (KeyError,TypeError,ValueError) as exc:
            raise QuantError('CORRUPT_HEDGE_INTENT','父意图记录缺失或改变') from exc
    chains={}
    for item in result:chains.setdefault(item['hedge_id'],[]).append(item)
    for chain in chains.values():
        previous=None
        for index,item in enumerate(sorted(chain,key=lambda x:x['revision']),1):
            if item['revision']!=index or item['previous_version']!=previous:
                raise QuantError('CORRUPT_HEDGE_INTENT','父意图修订链不连续')
            previous=item['version_hash']
    return result


def prepare(book,account_id,request):
    if (not isinstance(request,dict) or set(request) not in (FIELDS,FIELDS|{'tool_security_ids','tool_security_versions'}) or type(request['schema_version']) is not int
            or request['schema_version']!=1 or any(not isinstance(request[k],str) or not request[k].strip() for k in
                ('request_id','reason','trigger','base_strategy_version','timing'))
            or request['timing'] not in {'forward','historical_research'}
            or not isinstance(request['preview_request'],dict)):
        raise QuantError('INVALID_HEDGE_INTENT','父意图需显式目标/候选、身份版本、时点、依据、触发和原因')
    clock,known,until,now=map(utc,(request['decision_at'],request['knowledge_cutoff'],request['valid_until'],now_utc()))
    historical=request['timing']=='historical_research'
    if clock>now or known>now or until<=clock or (not historical and (known>clock or until<=now)):
        raise QuantError('INVALID_HEDGE_INTENT_TIME','父意图时点/有效窗口无效，不把事后重建当成前向决定')
    if historical and book.environment!='demo':
        raise QuantError('HISTORICAL_INTENT_DEMO_ONLY','历史重建父意图仅限明确demo研究')
    if request['expected_resource_hash']!=resources(book,account_id):
        raise QuantError('STALE_HEDGE_RESOURCES','父意图预检资源已变化')
    candidate=preview(book,account_id,request['preview_request'])
    risk=load(book.path.parent/'hedging/exposures',candidate['exposure_id'])
    if risk['ledger_seq']!=book.sequence(account_id):raise QuantError('STALE_LEDGER_SEQUENCE','风险快照前缀已落后')
    if utc(risk['as_of'])>clock or utc(risk['knowledge_cutoff'])>known:
        raise QuantError('HEDGE_RISK_NOT_AVAILABLE','风险快照在决策/知识截止时尚不可用')
    if not historical and risk['ledger_view']!='known_then':
        raise QuantError('RESTATED_NOT_FORWARD','重述风险不能标记为前向父意图')
    basis_hash=digest([dict(r) for r in book.connection.execute(
        'SELECT seq,event_id,content_hash,effective_at,recorded_at,payload FROM events WHERE account_id=? AND seq<=? ORDER BY seq',
        (account_id,risk['ledger_seq']))])
    if basis_hash!=risk['ledger_basis_hash']:raise QuantError('CORRUPT_EXPOSURE_ARCHIVE','父意图引用的风险账本前缀改变')
    spec=candidate['spec'];mapping=request['security_ids'];versions=request['security_versions']
    if (not isinstance(mapping,dict) or set(mapping)!=set(spec['scope'])
            or any(not isinstance(v,str) or not v for v in mapping.values()) or len(set(mapping.values()))!=len(mapping)):
        raise QuantError('INVALID_HEDGE_SCOPE','父意图范围必须逐项绑定唯一稳定证券ID')
    tools=request.get('tool_security_ids',{});tool_versions=request.get('tool_security_versions',{})
    if (not isinstance(versions,dict) or not isinstance(tools,dict) or not isinstance(tool_versions,dict)
            or set(versions)!=set(mapping) or set(tool_versions)!=set(tools) or set(tools)&set(mapping)
            or any(not isinstance(k,str) or not k or not isinstance(v,str) or not v
                   for k,v in [*versions.items(),*tool_versions.items(),*tools.items()])
            or len(set(list(mapping.values())+list(tools.values())))!=len(mapping)+len(tools)):
        raise QuantError('INVALID_SECURITY_BINDING','额外对冲工具需独立稳定身份，不改变保护范围或重复身份')
    identities=resolve(book.path.parent,book.environment,{**versions,**tool_versions},
                       {**mapping,**tools},clock,known)
    scope=sorted(mapping.values())
    strategy=request['base_strategy_version'];strategy_basis=None
    if strategy!='MANUAL_HOLDINGS':
        if not book.connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='strategy_bindings'").fetchone():
            raise QuantError('HEDGE_BASE_STRATEGY_NOT_ACTIVE','账户尚无基础策略绑定，不自动升级数据库')
        row=book.connection.execute('SELECT * FROM strategy_bindings WHERE account_id=? AND spec_hash=? '
            "AND status='ACTIVE' ORDER BY binding_seq DESC LIMIT 1",(account_id,strategy)).fetchone()
        market_session=clock.astimezone(ZoneInfo('America/New_York')).date().isoformat()
        if row is None or utc(row['requested_at'])>known or row['effective_session']>market_session:
            raise QuantError('HEDGE_BASE_STRATEGY_NOT_ACTIVE','基础策略版本未在该账户和知识时点有效绑定')
        strategy_basis=dict(row)
    stable={'account_id':account_id,'scope':scope,'policy_name':spec['name'],'policy_version':spec['version'],
            'mode':spec['mode'],'decision_at':clock.isoformat(),'trigger':request['trigger']}
    hedge_id=digest(stable);all_records=records(book,account_id)
    chain=sorted([r for r in all_records if r['hedge_id']==hedge_id],key=lambda r:r['revision'])
    old=chain[-1] if chain else None
    from .intent_actions import history as action_history
    closed={r['hedge_id'] for r in action_history(book,account_id)}
    if hedge_id in closed:
        raise QuantError('HEDGE_INTENT_CLOSED','父意图已关闭，不能修订或重新开启')
    from .groups import history as group_history
    if old and any(g['hedge_id']==hedge_id for g in group_history(book,account_id)):
        raise QuantError('HEDGE_INTENT_GROUP_BOUND','父意图已绑定执行组；不能覆盖原执行依据')
    if request['expected_version']!=(old['version_hash'] if old else None):
        raise QuantError('STALE_HEDGE_INTENT_VERSION','父意图已改变，请重新预检')
    heads={}
    for item in all_records:
        if item['hedge_id'] not in heads or item['revision']>heads[item['hedge_id']]['revision']:heads[item['hedge_id']]=item
        previous_spec=item['candidate']['spec']
        if (previous_spec['name'],previous_spec['version'])==(spec['name'],spec['version']) and item['candidate']['spec_hash']!=candidate['spec_hash']:
            raise QuantError('HEDGE_POLICY_VERSION_CONFLICT','同一策略目标版本不能更改参数；请明确增加版本')
    for other in heads.values():
        if (other['hedge_id'] not in closed and other['hedge_id']!=hedge_id and set(scope)&set(other['scope'])
                and max(clock,utc(other['decision_at']))<min(until,utc(other['valid_until']))):
            raise QuantError('HEDGE_SCOPE_CONFLICT','同一账户范围/有效周期已有选定父意图，不能换Spec版本绕开')
    revision=old['revision']+1 if old else 1
    version_basis={'hedge_id':hedge_id,'revision':revision,'previous_version':old['version_hash'] if old else None,
                   'candidate_hash':candidate['preview_hash'],'security_basis':identities,'resource_hash':request['expected_resource_hash'],
                   'base_strategy_version':strategy,'strategy_basis':strategy_basis,'valid_until':until.isoformat(),
                   'timing':request['timing'],'knowledge_cutoff':known.isoformat()}
    return {'hedge_id':hedge_id,'revision':revision,'previous_version':version_basis['previous_version'],
            'version_hash':digest(version_basis),'version_basis':version_basis,'scope':scope,
            'decision_at':clock.isoformat(),'valid_until':until.isoformat(),'knowledge_cutoff':known.isoformat(),
            'timing':request['timing'],'candidate':candidate,'security_basis':identities,
            'base_strategy_version':strategy,'strategy_basis':strategy_basis,
            'ledger_seq':risk['ledger_seq'],'ledger_basis_hash':basis_hash,'exposure_id':risk['exposure_id'],
            'execution_groups':[],'executable':False,'creates_reservations':False,
            'check_status':'RESEARCH_ONLY','meaning':'冻结父研究决定；未授予计划执行资格，不创建额外资源预留'}


def save(book,account_id,request,*,commit=False):
    with publication_lock(book.path.parent),book.transaction():
        key=PREFIX+digest({'account_id':account_id,'request_id':request.get('request_id') if isinstance(request,dict) else None})
        row=book.connection.execute('SELECT details FROM tasks WHERE task_id=?',(key,)).fetchone()
        if row:
            old=json.loads(row[0]);records(book,account_id)
            if old['request_hash']!=digest(request):raise QuantError('HEDGE_INTENT_REQUEST_CONFLICT','请求ID与内容冲突')
            return old
        body=prepare(book,account_id,request)
        if not commit:return {'status':'PREVIEW',**body}
        record={'schema_version':1,'status':'DRAFT','account_id':account_id,'environment':book.environment,
                'request':request,'request_hash':digest(request),'generated_at':now_utc(),**body}
        record['record_hash']=digest(record)
        book.connection.execute('INSERT INTO tasks VALUES(?,?,?,?)',(key,'DRAFT',canonical(record),record['generated_at']))
        return record


def validate_references(root,book):
    from .securities import load as load_security
    for account in book.connection.execute('SELECT id FROM accounts'):
        from .intent_actions import history as action_history
        action_history(book,account[0])
        from .groups import history as group_history
        group_history(book,account[0])
        for item in records(book,account[0]):
            risk=load(root/'hedging/exposures',item['exposure_id'])
            if risk['account_id']!=account[0] or risk['ledger_basis_hash']!=item['ledger_basis_hash']:
                raise QuantError('CORRUPT_HEDGE_INTENT','父意图风险引用改变')
            for binding in item['security_basis'].values():
                if load_security(root,binding['version_hash'])['record']['record_hash']!=binding['record_hash']:
                    raise QuantError('CORRUPT_HEDGE_INTENT','父意图证券引用改变')
            snapshot=item['candidate'].get('option_snapshot_id')
            if snapshot:
                from ..options.data import OptionDataStore
                try:OptionDataStore(root/'options/chains').load(snapshot)
                except (OSError,ValueError,KeyError) as exc:
                    raise QuantError('CORRUPT_HEDGE_INTENT','父意图期权链引用缺失或改变') from exc
