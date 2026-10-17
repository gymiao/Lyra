"""Rebuildable source/wheel and same-source validation receipts; no Git actions."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import zipfile
import check_v195 as gate
from personal_quant.common import QuantError,write_json,now_utc
from personal_quant.strategies.archive import source_fingerprint


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()



def delivery_files(root):
    files={root/x for x in gate.input_hashes(root)}
    files.update((root/'docs').glob('*.md'));files.update(root/x for x in ('README.md','agents.md','.gitignore'))
    return {str(p.relative_to(root)):sha(p) for p in sorted(files)}

def archive_source(root,out):
    files=delivery_files(root)
    with tarfile.open(out/'source.tar.gz','w:gz') as archive:
        for name,expected in files.items():
            file=root/name
            if file.is_symlink():raise QuantError('UNSAFE_RELEASE_SOURCE','归档不接受链接')
            archive.add(file,arcname=name,recursive=False)
    with tarfile.open(out/'source.tar.gz') as archive:
        restored={m.name:hashlib.sha256(archive.extractfile(m).read()).hexdigest() for m in archive.getmembers() if m.isfile()}
    if restored!=files:raise QuantError('SOURCE_ARCHIVE_CHANGED','源码归档读回与原文件不一致')
    return files


def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['build','refresh-source','finalize','verify']);p.add_argument('--destination',type=Path,required=True)
    p.add_argument('--evidence',type=Path,help='JSON对象：release/installed/browser/offline/online/backup六项同源PASSED回执绝对路径')
    a=p.parse_args();root=Path('/mnt/c/quant/project/lyra')
    if not root.is_dir():root=Path(__file__).absolute().parents[1]
    out=a.destination.absolute()
    if a.action=='build':
        out.mkdir(parents=True,exist_ok=False);source=source_fingerprint();inputs=gate.input_hashes(root)
        delivery=archive_source(root,out)
        result=subprocess.run([sys.executable,'-m','pip','wheel','--no-deps','--no-build-isolation','--wheel-dir',str(out/'wheel'),str(root)],capture_output=True,text=True)
        (out/'build.log').write_text(result.stdout+result.stderr)
        if result.returncode:raise QuantError('WHEEL_BUILD_FAILED','查看build.log')
        wheels=list((out/'wheel').glob('*.whl'))
        if len(wheels)!=1:raise QuantError('WHEEL_BUILD_FAILED','普通wheel不唯一')
        with zipfile.ZipFile(wheels[0]) as z:
            packaged={n:hashlib.sha256(z.read(n)).hexdigest() for n in z.namelist() if n.startswith('personal_quant/') and n.endswith('.py')}
        for file in (root/'src/personal_quant').rglob('*.py'):
            key=str(file.relative_to(root/'src'))
            if packaged.get(key)!=sha(file):raise QuantError('WHEEL_SOURCE_MISMATCH','wheel与源码不同：'+key)
        if source_fingerprint()!=source or gate.input_hashes(root)!=inputs:raise QuantError('SOURCE_CHANGED','构建期间输入改变')
        write_json(out/'build.json',{'status':'BUILT','source_hash':source,'inputs':inputs,'wheel':wheels[0].name,
            'wheel_sha256':sha(wheels[0]),'source_archive_sha256':sha(out/'source.tar.gz'),'delivery_files':delivery,'created_at':now_utc(),'version_complete':False})
    elif a.action=='refresh-source':
        build=json.loads((out/'build.json').read_text())
        if build['source_hash']!=source_fingerprint() or build['inputs']!=gate.input_hashes(root):raise QuantError('SOURCE_CHANGED','仅允许业务/测试/脚本等冻结后刷新交付文档')
        build['delivery_files']=archive_source(root,out);build['source_archive_sha256']=sha(out/'source.tar.gz');build['refreshed_at']=now_utc()
        write_json(out/'build.json',build)
    elif a.action=='finalize':
        build=json.loads((out/'build.json').read_text())
        if build['source_hash']!=source_fingerprint() or build['inputs']!=gate.input_hashes(root):raise QuantError('SOURCE_CHANGED','构建后输入变化，请建立新发布批次')
        if build.get('delivery_files')!=delivery_files(root) or sha(out/'source.tar.gz')!=build['source_archive_sha256'] or sha(out/'wheel'/build['wheel'])!=build['wheel_sha256']:
            raise QuantError('RELEASE_ARTIFACT_CHANGED','交付文档或已构建归档/wheel变化，先核实再发布')
        if not a.evidence:raise QuantError('RELEASE_EVIDENCE_REQUIRED','需要六项实际同源回执')
        references=json.loads(a.evidence.read_text());required={'release','installed','browser','offline','online','backup'}
        if set(references)!=required:raise QuantError('RELEASE_EVIDENCE_REQUIRED','回执必须覆盖release/installed/browser/offline/online/backup')
        receipts={};folder=out/'evidence';folder.mkdir(exist_ok=False)
        for key,name in references.items():
            file=Path(name);record=json.loads(file.read_text())
            if record.get('status')!='PASSED' or record.get('source_hash')!=build['source_hash']:
                raise QuantError('RELEASE_EVIDENCE_MISMATCH',key+'不是当前源码的PASSED证据')
            if key=='release' and (record.get('skipped') or not record.get('complete_collection_coverage') or not record.get('source_unchanged')):
                raise QuantError('INCOMPLETE_RELEASE_GATE','全量门禁需完整阶段覆盖、无跳过且输入未变')
            shutil.copyfile(file,folder/(key+'.json'));receipts[key]={'original':str(file),'sha256':sha(file)}
        write_json(out/'release.json',{'status':'PASSED','source_hash':build['source_hash'],'receipts':receipts,'external_conditions':'E1/E2/E3_UNVERIFIED',
            'created_at':now_utc(),'meaning':'本地模拟版本发布；日志/原生中间产物按回执原始目录另存，不把外部条件算完成'})
        files={str(f.relative_to(out)):sha(f) for f in out.rglob('*') if f.is_file() and f.name not in {'manifest.json','SHA256SUMS'}}
        write_json(out/'manifest.json',files);(out/'SHA256SUMS').write_text(''.join(f'{value}  {name}\n' for name,value in sorted(files.items())))
    else:
        files=json.loads((out/'manifest.json').read_text())
        if not isinstance(files,dict) or not {'build.json','release.json','source.tar.gz'}<=set(files):raise QuantError('RELEASE_CORRUPT','发布清单缺少必要身份/归档')
        actual={str(f.relative_to(out)) for f in out.rglob('*') if f.is_file() and f.name not in {'manifest.json','SHA256SUMS'}}
        if set(files)!=actual:raise QuantError('RELEASE_CORRUPT','发布文件增减与清单不一致')
        for name,expected in files.items():
            file=out/name
            if not file.resolve().is_relative_to(out.resolve()) or file.is_symlink() or sha(file)!=expected:raise QuantError('RELEASE_CORRUPT','发布文件改变：'+name)
        print(json.dumps({'status':'PASSED','files':len(files),'read_only':True}));return 0
    print(json.dumps({'status':'PASSED','action':a.action,'directory':str(out),'source_hash':source_fingerprint()}));return 0

if __name__=='__main__':raise SystemExit(main())
