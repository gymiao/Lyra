"""Layered v2.0 gates, reusing the complete per-phase v1.95 result verifier."""
import argparse,json,os,signal,subprocess,sys,tempfile,time
from pathlib import Path
import check_v195 as gate
from personal_quant.common import write_json,now_utc
from personal_quant.processes import python_environment,native_tools
from personal_quant.research.artifacts import code_hash
from personal_quant.strategies.archive import source_fingerprint
from personal_quant.options.adapter_resources import source_hashes

FAST=['tests/test_ledger.py','tests/test_data_strategy.py','tests/test_reconciliation_rules.py',
      'tests/test_options_data_v19.py','tests/test_options_selection_v19.py','tests/test_capital_v20.py','tests/test_release_gate_v195.py']


def partition(paths,expected,count):
    """Keep whole modules together, balance collected nodes without dropping any."""
    from collections import Counter
    weights=Counter(node.split('::')[0] for node in expected)
    buckets=[([],0) for _ in range(min(count,len(paths)))]
    for path in sorted(paths,key=lambda value:(-weights[value],value)):
        i=min(range(len(buckets)),key=lambda j:(buckets[j][1],j))
        files,size=buckets[i];files.append(path);buckets[i]=(files,size+weights[path])
    return [sorted(files) for files,_ in buckets if files]


def temp_manifest(directory):
    import hashlib
    result={}
    for parent,dirs,files in os.walk(directory,followlinks=False):
        for name in dirs+files:
            path=Path(parent)/name;key=str(path.relative_to(directory.parent))
            if path.is_symlink():result[key]={'kind':'link','target':os.readlink(path)}
            elif path.is_file():
                with path.open('rb') as stream:value=hashlib.file_digest(stream,'sha256').hexdigest()
                result[key]={'kind':'file','sha256':value}
            elif not path.is_dir():raise RuntimeError('unsupported test artifact: '+key)
    return result


def archive_temp(directory,destination):
    """After a completed test process: verify all bytes/links before freeing temp."""
    import hashlib,shutil,tarfile
    if directory.is_symlink() or not directory.is_dir() or destination.exists():raise RuntimeError('unsafe test artifact archive')
    original=temp_manifest(directory)
    with tarfile.open(destination,'x:gz',dereference=False) as archive:
        archive.add(directory,arcname=directory.name)
    restored={}
    with tarfile.open(destination,'r:gz') as archive:
        for member in archive.getmembers():
            if member.issym():restored[member.name]={'kind':'link','target':member.linkname}
            elif member.isfile() or member.islnk():restored[member.name]={'kind':'file','sha256':hashlib.file_digest(archive.extractfile(member),'sha256').hexdigest()}
            elif not member.isdir():raise RuntimeError('unsupported archived test artifact')
    if original!=restored or original!=temp_manifest(directory):raise RuntimeError('test artifact archive readback mismatch; originals retained')
    manifest=destination.with_suffix('.manifest.json');write_json(manifest,original)
    with destination.open('rb') as stream:fingerprint=hashlib.file_digest(stream,'sha256').hexdigest()
    shutil.rmtree(directory)
    return {'path':str(destination),'sha256':fingerprint,'members':len(original),'manifest':str(manifest),'original_temp':str(directory),'readback_verified':True,'temporary_directory_removed':True}


def main():
    p=argparse.ArgumentParser();p.add_argument('--scope',choices=['fast','core','integration','native','ui','release'],default='fast')
    p.add_argument('--destination',type=Path,required=True);p.add_argument('--timeout-seconds',type=float,default=28800);p.add_argument('--cancel-file',type=Path);p.add_argument('--integration-groups',type=int,default=1);p.add_argument('--archive-temp-to',type=Path)
    a=p.parse_args();root=Path(__file__).absolute().parents[1];writable=Path('/mnt/c/quant/project/lyra')
    if writable.exists() and writable.samefile(root):root=writable
    if not 0<a.timeout_seconds<=86400:p.error('阶段超时需0至86400秒')
    if not 1<=a.integration_groups<=32 or (a.integration_groups>1 and a.scope not in {'release','integration'}):p.error('分组数1至32，只用于release/integration')
    source=source_fingerprint()
    if source!=code_hash(root) or source_hashes()!=source_hashes(root/'engines/lean'):
        p.error('运行解释器中的Python/C#资源与待测源码不同，请使用匹配的开发环境或普通wheel')
    output=a.destination.absolute();output.mkdir(parents=True,exist_ok=False)
    archive_root=a.archive_temp_to.absolute() if a.archive_temp_to else None
    if archive_root:
        if archive_root.resolve().is_relative_to(output.resolve()):p.error('归档放在测试临时目录外的全新目录')
        archive_root.mkdir(parents=True,exist_ok=False)
    environment=python_environment();environment.update(PYTHONDONTWRITEBYTECODE='1',MPLCONFIGDIR=str(output/'mpl-cache'))
    environment.pop('LYRAX_TEST_REPORT_FILE',None)
    inputs=gate.input_hashes(root);write_json(output/'inputs.json',inputs)
    if a.scope=='release':
        native_tools(root);expected,groups=gate.release_groups(root,output,environment)
    else:
        if a.scope=='fast':paths=FAST
        elif a.scope=='core':paths=sorted(str(x.relative_to(root)) for x in (root/'tests').glob('test_*v20.py') if 'native' not in x.stem and 'ui' not in x.stem)
        elif a.scope=='integration':
            native_tools(root);_,all_groups=gate.release_groups(root,output,environment)
            paths=next(paths for name,paths in all_groups if name=='integration')
        elif a.scope=='native':
            native_tools(root);paths=sorted(str(x.relative_to(root)) for x in (root/'tests').glob('test_*native*v20.py'))
        else:paths=sorted(str(x.relative_to(root)) for x in (root/'tests').glob('test_*ui*v20.py'))
        if not paths or any(not (root/x).is_file() for x in paths):p.error('所选分组尚无完整测试，不生成空成功')
        collection=subprocess.run([sys.executable,'-m','pytest','--collect-only','-q',*paths,'-p','no:cacheprovider'],cwd=root,env=environment,capture_output=True,text=True)
        (output/'collection.log').write_text(collection.stdout+collection.stderr)
        expected=[s for s in collection.stdout.splitlines() if s.startswith('tests/') and '::' in s]
        if collection.returncode or not expected:raise RuntimeError('测试收集失败')
        groups=[(a.scope,paths)];write_json(output/'expected-nodeids.json',expected)
    if a.integration_groups>1:
        groups=[(f'{name}-{i+1:02}',part) if name=='integration' else (name,part)
                for name,paths in groups for i,part in enumerate(partition(paths,expected,a.integration_groups) if name=='integration' else [paths])]
    rows=[];nodes=[];phases=[];started=time.monotonic();cancelled=False
    for name,paths in groups:
        receipt=output/(name+'-results.jsonl');log=output/(name+'-pytest.log');timed_out=False
        cmd=[sys.executable,'-m','pytest','-q',*paths,'-p','no:cacheprovider','-o','faulthandler_timeout=0',
             '--basetemp',str(output/(name+'-temp')),'--maxfail=1']
        clock=time.monotonic()
        with log.open('w') as stream:
            child=subprocess.Popen(cmd,cwd=root,env=dict(environment,LYRAX_TEST_REPORT_FILE=str(receipt)),stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
            from personal_quant.research.service import process_identity
            write_json(output/(name+'-process.json'),{'owner':process_identity(child.pid),'source_hash':source,'phase':name})
            def stop():
                from personal_quant.processes import descendant_groups,stop_descendant_groups
                from personal_quant.workspace.batch import _stop
                groups=descendant_groups(child.pid);_stop(child);stop_descendant_groups(groups)
            cancel=a.cancel_file or output/'cancel-request.json'
            deadline=time.monotonic()+a.timeout_seconds
            try:
                while child.poll() is None:
                    if cancel.is_file():
                        try:request=json.loads(cancel.read_text())
                        except (OSError,ValueError):request={}
                        if request.get('source_hash')==source and request.get('confirm_cancel') is True:
                            cancelled=True;stop();break
                    remaining=deadline-time.monotonic()
                    if remaining<=0:timed_out=True;stop();break
                    try:child.wait(timeout=min(1,remaining))
                    except subprocess.TimeoutExpired:pass
            except BaseException:
                stop();raise
        error=None
        try:
            collected=json.loads(Path(str(receipt)+'.collection.json').read_text())
            reports=[json.loads(s) for s in receipt.read_text().splitlines()]
        except (OSError,ValueError) as exc:collected=[];reports=[];error=type(exc).__name__
        selected=[node for node in expected if node.split('::')[0] in paths]
        passed=child.returncode==0 and not timed_out and gate.complete_results(selected,collected,reports)
        phases.append({'name':name,'status':'PASSED' if passed else 'FAILED','exit_code':child.returncode,'timed_out':timed_out,'cancelled':cancelled,
                       'cases':len(collected),'seconds':time.monotonic()-clock,'command':cmd,'evidence_error':error})
        if passed and archive_root:
            try:
                archive_clock=time.monotonic()
                phases[-1]['artifact_archive']=archive_temp(output/(name+'-temp'),archive_root/(name+'.tar.gz'))
                phases[-1]['archive_seconds']=time.monotonic()-archive_clock
                phases[-1]['seconds']=time.monotonic()-clock
            except Exception as exc:
                phases[-1].update(status='FAILED',evidence_error='ARTIFACT_ARCHIVE_FAILED: '+str(exc));passed=False
        nodes.extend(collected);rows.extend(reports);write_json(output/'phases.json',phases)
        if not passed:break # Preserve an explicit failed/incomplete gate; fix before a new complete release run.
    unchanged=inputs==gate.input_hashes(root) and source==source_fingerprint()
    covered=gate.complete_results(expected,nodes,rows);passed=all(x['status']=='PASSED' for x in phases) and covered and unchanged
    result={'status':'PASSED' if passed else 'FAILED','scope':a.scope,'cancelled':cancelled,'source_hash':source,'source_unchanged':unchanged,'phases':phases,
            'collected':len(nodes),'complete_collection_coverage':covered,'skipped':any(x['outcome']=='skipped' or x.get('wasxfail') for x in rows),
            'input_files':len(inputs),'seconds':time.monotonic()-started,'completed_at':now_utc(),'integration_groups':a.integration_groups,'artifact_archive_root':str(archive_root) if archive_root else None,'complete_version':False}
    write_json(output/'verification.json',result);print(json.dumps(result));return 0 if passed else 1

if __name__=='__main__':raise SystemExit(main())
