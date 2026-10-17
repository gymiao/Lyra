"""Installed adapter sources and isolated builds; package resources stay read-only."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from ..common import QuantError,digest,write_json


def adapter_root():
    package=Path(__file__).resolve().parents[1];project=package.parent.parent
    root=project/'engines/lean' if (project/'src/personal_quant').resolve()==package else Path(sys.prefix)/'share/lyrax/lean-adapter'
    if not (root/'LyraX.Options.csproj').is_file() or not list(root.glob('*.cs')):
        raise QuantError('MISSING_LEAN_ADAPTER','安装缺少LyraX期权适配器资源，请安装完整wheel或源码checkout')
    return root


def source_hashes(root=None):
    root=Path(root) if root is not None else adapter_root()
    paths=[root/'LyraX.Options.csproj',*sorted(root.glob('*.cs'))]
    if any(not p.is_file() or p.is_symlink() for p in paths):
        raise QuantError('MISSING_LEAN_ADAPTER','适配器源码资源缺失或包含链接')
    return {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def build(engine_root,dotnet,destination,*,source_directory,binary_directory,object_directory,log_name):
    destination=Path(destination);origin=adapter_root();expected=source_hashes(origin)
    staged=destination/source_directory;staged.mkdir(parents=True)
    for name in expected:shutil.copyfile(origin/name,staged/name)
    if source_hashes(staged)!=expected:raise QuantError('SOURCE_CHANGED','适配器资源复制期间改变')
    cache_setting=os.environ.get('LYRAX_ADAPTER_CACHE')
    if cache_setting:
        from ..locks import publication_lock
        from uuid import uuid4
        cache=Path(cache_setting).absolute()
        if cache.is_symlink():raise QuantError('UNSAFE_ADAPTER_CACHE','构建缓存不能是链接')
        cache.mkdir(parents=True,exist_ok=True)
        version=subprocess.check_output([str(dotnet),'--version'],text=True).strip()
        sdk=Path(dotnet).parent/'sdk'/version
        inputs={'source':expected,'sdk_version':version,'files':{}}
        dependencies={'dotnet':Path(dotnet),'MSBuild':sdk/'MSBuild.dll','compiler':sdk/'Roslyn/bincore/csc.dll'}
        for name in ('QuantConnect.Algorithm.dll','QuantConnect.Common.dll','Python.Runtime.dll'):
            dependencies[name]=Path(engine_root)/'Launcher/bin/Release'/name
        for name,path in dependencies.items():inputs['files'][name]=hashlib.sha256(path.read_bytes()).hexdigest()
        key=digest(inputs);entry=cache/key
        with publication_lock(cache):
            if entry.exists():
                try:
                    meta=json.loads((entry/'manifest.json').read_text())
                    if (entry.is_symlink() or (entry/'manifest.json').is_symlink() or not isinstance(meta,dict)
                            or meta.get('inputs')!=inputs or not isinstance(meta.get('files'),dict)
                            or set(meta['files'])!={'LyraX.Options.dll','LyraX.Options.deps.json'}):
                        raise ValueError('缓存输入或输出清单不一致')
                    binary=destination/binary_directory;binary.mkdir(parents=True)
                    for name,identity in meta['files'].items():
                        path=entry/name
                        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest()!=identity:raise ValueError('缓存内容改变')
                        shutil.copyfile(path,binary/name)
                    if source_hashes(origin)!=expected or source_hashes(staged)!=expected:raise ValueError('源码在读取缓存期间改变')
                except (OSError,ValueError,KeyError,TypeError) as exc:
                    raise QuantError('CORRUPT_ADAPTER_CACHE','构建缓存损坏，请保留诊断并使用新缓存目录') from exc
                (destination/log_name).write_text('Verified adapter cache hit '+key+'\n')
                return expected
            result=_compile(engine_root,dotnet,destination,staged,origin,expected,binary_directory,object_directory,log_name)
            pending=cache/('.pending-'+uuid4().hex);pending.mkdir()
            try:
                files={}
                for name in ('LyraX.Options.dll','LyraX.Options.deps.json'):
                    path=destination/binary_directory/name;shutil.copyfile(path,pending/name)
                    files[name]=hashlib.sha256(path.read_bytes()).hexdigest()
                write_json(pending/'manifest.json',{'inputs':inputs,'files':files})
                os.rename(pending,entry)
            finally:
                if pending.exists():shutil.rmtree(pending)
            return result
    return _compile(engine_root,dotnet,destination,staged,origin,expected,binary_directory,object_directory,log_name)


def _compile(engine_root,dotnet,destination,staged,origin,expected,binary_directory,object_directory,log_name):
    command=[str(dotnet),'build',str(staged/'LyraX.Options.csproj'),'-c','Release','--ignore-failed-sources',
        '-p:LeanLib='+str(Path(engine_root)/'Launcher/bin/Release'),
        '-p:BaseIntermediateOutputPath='+str(destination/object_directory)+'/',
        '-p:MSBuildProjectExtensionsPath='+str(destination/object_directory)+'/',
        '-p:OutputPath='+str(destination/binary_directory)+'/',
        '-p:Deterministic=true','-p:DebugType=None','-p:PathMap='+str(staged)+'=/_/lyrax-adapter']
    with (destination/log_name).open('w') as log:
        result=subprocess.run(command,cwd=staged,env=dict(os.environ,DOTNET_CLI_HOME='/tmp/lyrax-dotnet-home'),
            stdout=log,stderr=subprocess.STDOUT,timeout=180)
    if result.returncode:raise QuantError('LEAN_ADAPTER_BUILD_FAILED','适配器编译失败，查看'+log_name)
    if source_hashes(origin)!=expected or source_hashes(staged)!=expected:
        raise QuantError('SOURCE_CHANGED','适配器编译期间资源改变')
    return expected
