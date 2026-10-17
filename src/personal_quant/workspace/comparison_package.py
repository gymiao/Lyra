"""Restorable multi-workspace comparisons composed from existing validated backups."""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from uuid import uuid4
from ..common import QuantError,digest,now_utc,write_json
from ..locks import publish_directory
from ..portfolio.backup import verify_bundle,restore_bundle
from .experiments import compare
from .experiment_index import export as export_experiment


def _files(root):
    result={}
    for file in sorted(root.rglob('*')):
        if file.is_symlink():raise QuantError('UNSAFE_COMPARISON_PACKAGE','比较包不接受链接')
        if file.is_file() and file!=root/'package-manifest.json':
            with file.open('rb') as stream:result[file.relative_to(root).as_posix()]=hashlib.file_digest(stream,'sha256').hexdigest()
    return result


def _same(left,right):
    keys=('status','read_only','data_type','policy','metrics','execution','curves','meaning')
    return all(left.get(key)==right.get(key) for key in keys)


def _staging(destination):
    destination=Path(destination).absolute()
    if destination.exists() or destination.is_symlink():raise QuantError('NONEMPTY_DESTINATION','比较导出/恢复需要不存在的新目录')
    destination.parent.mkdir(parents=True,exist_ok=True)
    return destination,Path(tempfile.mkdtemp(prefix='.pending-comparison-',dir=destination.parent))


def export(request,destination):
    summary=compare(request);destination,pending=_staging(destination)
    try:
        cases=[]
        for i,item in enumerate(request):
            relative='cases/'+str(i+1).zfill(3)
            export_experiment(item['workspace'],item['run_id'],pending/relative)
            manifest=json.loads((pending/relative/'manifest.json').read_text())
            cases.append({'name':item['name'],'run_id':item['run_id'],'relative':relative,'backup_manifest_hash':manifest['manifest_hash']})
        if not _same(summary,compare(request)):
            raise QuantError('COMPARISON_SOURCE_CHANGED','导出期间实验事实或规格发生变化，未发布比较包')
        write_json(pending/'comparison.json',summary)
        manifest={'schema_version':1,'package_id':uuid4().hex,'data_type':'synthetic_comparison_bundle',
            'created_at':now_utc(),'cases':cases,'comparison_hash':digest(summary),'files':_files(pending)}
        manifest['content_hash']=digest(manifest);write_json(pending/'package-manifest.json',manifest)
        verify(pending)
        publish_directory(pending,destination)
        return {'status':'SUCCESS','package':str(destination),'package_id':manifest['package_id'],'cases':len(cases),
                'meaning':'完整模拟比较包；每项为独立账户，不合并资金；无外部SDK/LEAN或真实凭据'}
    finally:
        if pending.exists():shutil.rmtree(pending)


def verify(directory):
    root=Path(directory).absolute()
    try:
        manifest=json.loads((root/'package-manifest.json').read_text())
        if (manifest.get('schema_version')!=1 or manifest.get('data_type')!='synthetic_comparison_bundle'
                or digest({k:v for k,v in manifest.items() if k!='content_hash'})!=manifest.get('content_hash')
                or _files(root)!=manifest['files'] or not 2<=len(manifest['cases'])<=7):
            raise QuantError('CORRUPT_COMPARISON_PACKAGE','比较包清单/文件/范围改变')
        summary=json.loads((root/'comparison.json').read_text());request=[];names=set()
        if digest(summary)!=manifest['comparison_hash']:raise QuantError('CORRUPT_COMPARISON_PACKAGE','比较结果哈希改变')
        for i,case in enumerate(manifest['cases']):
            if case['relative']!='cases/'+str(i+1).zfill(3) or case['name'] in names:
                raise QuantError('CORRUPT_COMPARISON_PACKAGE','比较包案例路径或名称无效')
            names.add(case['name']);folder=root/case['relative']
            verify_bundle(folder,'demo')
            native=json.loads((folder/'manifest.json').read_text())
            if native['manifest_hash']!=case['backup_manifest_hash']:
                raise QuantError('CORRUPT_COMPARISON_PACKAGE','比较包案例与已绑定备份不同')
            request.append({'name':case['name'],'workspace':str(folder),'run_id':case['run_id']})
        if not _same(summary,compare(request)):
            raise QuantError('UNVERIFIED_COMPARISON_PACKAGE','包内账户不能重现所声明的曲线/费用/口径')
        return {'status':'PASSED','manifest':manifest,'comparison':summary,'read_only':True}
    except QuantError:raise
    except (OSError,ValueError,KeyError,TypeError) as exc:
        raise QuantError('CORRUPT_COMPARISON_PACKAGE','比较包缺失或格式无效：'+str(exc)) from exc


def restore(directory,destination):
    checked=verify(directory);source=Path(directory).absolute();destination,pending=_staging(destination)
    try:
        stage_request=[];request=[]
        for case in checked['manifest']['cases']:
            relative=case['relative'];restore_bundle(source/relative,pending/relative,'demo')
            stage_request.append({'name':case['name'],'workspace':str(pending/relative),'run_id':case['run_id']})
            request.append({'name':case['name'],'workspace':str(destination/relative),'run_id':case['run_id']})
        summary=compare(stage_request)
        if not _same(checked['comparison'],summary):raise QuantError('COMPARISON_RESTORE_CHANGED','恢复后的资金/曲线/费用不一致')
        summary.update(request=request,request_hash=digest(request))
        write_json(pending/'comparison.json',summary);write_json(pending/'request.json',request)
        result={'status':'SUCCESS','destination':str(destination),'package_id':checked['manifest']['package_id'],
                'request':request,'data_type':'synthetic_comparison_restore','initial_funding_replayed':False}
        write_json(pending/'restore.json',result);publish_directory(pending,destination);return result
    finally:
        if pending.exists():shutil.rmtree(pending)
