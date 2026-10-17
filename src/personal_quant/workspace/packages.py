"""Self-contained immutable input packages; source/permissions remain independent."""
import json
import hashlib
from pathlib import Path
import shutil
import tempfile
from ..common import QuantError,digest,write_json
from ..locks import publish_directory
from ..data.store import DataStore
from ..options.data import OptionDataStore


def files(root):
    result={}
    for p in sorted(root.rglob('*')):
        if p.is_symlink():raise QuantError('UNSAFE_INPUT_PACKAGE','输入包不接受符号链接')
        if p.is_file() and p!=root/'input-manifest.json':result[p.relative_to(root).as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
    return result


def seal(root,*,roles,chain_snapshots=(),spec=None,checks=()):
    body={'schema_version':1,'artifact_type':'input_package','roles':roles,'option_snapshots':list(chain_snapshots),
          'scenario_spec':spec,'checks':list(checks),'source_qualification':'UNVERIFIED','executable':False}
    body['input_bundle_id']=digest(body)
    body['files']=files(root);body['content_hash']=digest(body);write_json(root/'input-manifest.json',body)
    return body


def verify(directory):
    root=Path(directory).absolute()
    try:
        if root.is_symlink():raise ValueError('linked root')
        body=json.loads((root/'input-manifest.json').read_text())
        if (body['schema_version']!=1 or body['artifact_type']!='input_package' or body.get('source_qualification')!='UNVERIFIED' or body.get('executable') is not False
                or digest({k:v for k,v in body.items() if k!='content_hash'})!=body['content_hash']
                or digest({k:v for k,v in body.items() if k not in {'input_bundle_id','files','content_hash'}})!=body['input_bundle_id']
                or body['files']!=files(root) or set(body['roles'])!={'signal','execution','valuation'}):raise ValueError('manifest')
        store=DataStore(root/'data');types=set()
        for role,identity in body['roles'].items():
            _,meta,_=store.load(identity);types.add(meta['data_type'])
            if role!='signal' and set(meta['price_basis'])!={'unadjusted'}:raise ValueError('price basis')
        if len(types)!=1:raise ValueError('mixed source types')
        for identity in body['option_snapshots']:OptionDataStore(root/'chains').load(identity)
        return body
    except (OSError,ValueError,KeyError,TypeError) as exc:
        raise QuantError('CORRUPT_INPUT_PACKAGE','输入包缺失、改变或口径不一致：'+str(exc)) from exc


def import_prices(request,destination):
    if (not isinstance(request,dict) or set(request)!={'schema_version','data_root','roles'} or request['schema_version']!=1
            or not isinstance(request['roles'],dict) or set(request['roles'])!={'signal','execution','valuation'}):
        raise QuantError('INVALID_INPUT_PACKAGE','需schema1、已有行情目录及三种用途的确切快照')
    source=Path(request['data_root']).absolute()
    if not source.is_dir() or source.is_symlink():raise QuantError('UNSAFE_INPUT_PACKAGE','行情源需已有普通目录')
    destination=Path(destination).absolute()
    if destination.exists():raise QuantError('NONEMPTY_DESTINATION','输入包输出需新目录')
    destination.parent.mkdir(parents=True,exist_ok=True)
    pending=Path(tempfile.mkdtemp(prefix='.pending-input-',dir=destination.parent))
    try:
        reader=DataStore(source);writer=DataStore(pending/'data');roles={}
        for role,identity in request['roles'].items():
            frame,meta,calendar=reader.load(identity)
            roles[role]=writer.save(frame,calendar,historical_availability_assumed=meta['historical_availability_assumed'])['snapshot_id']
        body=seal(pending,roles=roles);verify(pending);publish_directory(pending,destination)
        return {'status':'IMPORTED','input_bundle_id':body['input_bundle_id'],'directory':str(destination),'qualification':'UNVERIFIED','executable':False}
    finally:
        if pending.exists():shutil.rmtree(pending)


def copy_prices(directory,runtime):
    root=Path(directory).absolute();body=verify(root)
    if body['checks']:raise QuantError('INPUT_PACKAGE_BLOCKED','输入包存在未解决事项：'+','.join(body['checks']))
    reader=DataStore(root/'data');writer=DataStore(runtime/'data');roles={}
    for role,identity in body['roles'].items():
        frame,meta,calendar=reader.load(identity)
        roles[role]=writer.save(frame,calendar,historical_availability_assumed=meta['historical_availability_assumed'])['snapshot_id']
    write_json(runtime/'simulation/imported-input.json',{'input_bundle_id':body['input_bundle_id'],'roles':roles,'source_qualification':'UNVERIFIED'})
    return roles

def assemble(request,destination):
    """Assemble existing complete CSV-normalized chains and explicit price paths."""
    fields={'schema_version','price_package','chain_root','cycles','execution_path','underlying','corporate_actions'}
    if not isinstance(request,dict) or set(request)!=fields or request['schema_version']!=1 or not isinstance(request['cycles'],list) or not 1<=len(request['cycles'])<=24:
        raise QuantError('INVALID_INPUT_PACKAGE','组合包需原价包、完整链、1至24周期、明确路径/标的和行动凭据')
    base=Path(request['price_package']).absolute();original=verify(base)
    destination=Path(destination).absolute()
    if destination.exists():raise QuantError('NONEMPTY_DESTINATION','组合包需新目录')
    destination.parent.mkdir(parents=True,exist_ok=True);pending=Path(tempfile.mkdtemp(prefix='.pending-assemble-',dir=destination.parent))
    try:
        shutil.copytree(base/'data',pending/'data')
        frame,meta,calendar=DataStore(pending/'data').load(original['roles']['signal'])
        reader=OptionDataStore(request['chain_root']);writer=OptionDataStore(pending/'chains');snapshots=[];sessions=[]
        for month in request['cycles']:
            if not isinstance(month,dict) or set(month)!={'decision_session','snapshot_id','expiry'}:raise QuantError('INVALID_INPUT_PACKAGE','周期须明确决策日、完整链快照和到期日')
            calendar.close(month['decision_session']);sessions.append(month['decision_session'])
            contracts,records,metadata,_=reader.load(month['snapshot_id'])
            if metadata['data_type']!=meta['data_type']:raise QuantError('MIXED_INPUT_SOURCES','标的与期权链不可混用合成和真实来源类型')
            if request['underlying'] not in {c.underlying for c in contracts.values()}:raise QuantError('MISSING_OPTION_UNDERLYING','完整链未覆盖配置标的')
            saved=writer.save(list(contracts.values()),__import__('pandas').DataFrame(records),metadata)
            if saved['snapshot_id']!=month['snapshot_id']:raise QuantError('INPUT_ID_CHANGED','复制期权链身份改变')
            snapshots.append(month['snapshot_id'])
        if sessions!=sorted(set(sessions)):raise QuantError('INVALID_INPUT_PACKAGE','决策周期必须严格递增且不重复')
        path=request['execution_path']
        if not isinstance(path,dict) or set(path)!={'schema_version','data_type','stocks','options'} or path['data_type']!='synthetic':
            raise QuantError('UNQUALIFIED_EXECUTION_PATH','本地组合执行路径须明确合成，真实报价执行需独立来源资格')
        if not isinstance(request['corporate_actions'],list):raise QuantError('INVALID_CORPORATE_ACTIONS','行动需显式列表，不忽略未知行动')
        dates=sorted(path['stocks'].get(request['underlying'],{}))
        if not dates:raise QuantError('MISSING_EXECUTION_PATH','路径缺少标的交易日价格')
        spec={'start':dates[0],'end':dates[-1],'option_underlying':request['underlying']}
        write_json(pending/'scenario.json',{'schema_version':1,'kind':'imported_complete_chain_and_synthetic_path','spec':spec,
            'cycles':request['cycles'],'execution_path':path,'corporate_actions':request['corporate_actions'],
            'meaning':'完整链与显式合成回放路径，不将导入文件视为真实来源/交易权限'})
        checks=list(original['checks'])+(['CORPORATE_ACTION_REQUIRES_QUALIFIED_INPUT'] if request['corporate_actions'] else [])
        body=seal(pending,roles=original['roles'],chain_snapshots=snapshots,spec={'price_bundle_id':original['input_bundle_id'],'cycles':request['cycles'],'path_hash':digest(path),'underlying':request['underlying'],'corporate_actions':request['corporate_actions']},checks=checks)
        verify(pending);publish_directory(pending,destination)
        return {'status':'ASSEMBLED','input_bundle_id':body['input_bundle_id'],'directory':str(destination),'executable':False,'source_qualification':'UNVERIFIED'}
    finally:
        if pending.exists():shutil.rmtree(pending)
