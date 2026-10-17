"""Content-bound external LEAN/SDK locations; relocation preserves run identity."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
from ..common import QuantError,digest,write_json
from ..options.engine import LEAN_COMMIT


def fingerprint(engine_root,dotnet):
    root=Path(engine_root).absolute();dotnet=Path(dotnet).absolute()
    try:
        revision=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True,stderr=subprocess.PIPE,timeout=30).strip()
        dirty=subprocess.check_output(['git','-C',str(root),'status','--porcelain'],text=True,stderr=subprocess.PIPE,timeout=30).strip()
        sdk=subprocess.check_output([str(dotnet),'--version'],text=True,stderr=subprocess.PIPE,
            env=dict(os.environ,DOTNET_CLI_HOME='/tmp/lyrax-dotnet-home'),timeout=30).strip()
    except (OSError,subprocess.SubprocessError) as exc:
        raise QuantError('SIMULATION_TOOLS_UNAVAILABLE','无法核对外部LEAN/SDK，请显式提供已安装的新路径') from exc
    if revision!=LEAN_COMMIT or sdk!='10.0.100':
        raise QuantError('LEAN_VERSION_MISMATCH','继续模拟需要相同固定LEAN提交及SDK10.0.100')
    if dirty:raise QuantError('LEAN_SOURCE_CHANGED','外部LEAN源码有修改，不能迁移或继续')
    lean_paths=[root/'Launcher/config.json',root/'Data/market-hours/market-hours-database.json',
        root/'Data/symbol-properties/symbol-properties-database.csv',root/'Data/symbol-properties/security-database.csv']
    binaries=root/'Launcher/bin/Release'
    if not (binaries/'QuantConnect.Lean.Launcher.dll').is_file() or not (dotnet.parent/'sdk/10.0.100').is_dir():
        raise QuantError('SIMULATION_TOOLS_UNAVAILABLE','外部引擎编译产物或完整SDK缺失')
    def hashes(paths,base):
        result={}
        for path in sorted(paths):
            if path.is_symlink() or not path.is_file():
                raise QuantError('UNSAFE_SIMULATION_TOOLS','工具清单含链接或缺失文件')
            with path.open('rb') as stream:
                result[path.relative_to(base).as_posix()]=hashlib.file_digest(stream,'sha256').hexdigest()
        return result
    lean=hashes([*lean_paths,*[p for p in binaries.rglob('*') if p.is_file() or p.is_symlink()]],root)
    sdk_files=hashes([p for p in dotnet.parent.rglob('*') if p.is_file() or p.is_symlink()],dotnet.parent)
    body={'schema_version':1,'lean_commit':revision,'sdk_version':sdk,'lean_files':lean,'sdk_files':sdk_files}
    return {**body,'content_hash':digest(body)}


def bind(book,directory,run_id,settings,manifest):
    write_json(Path(directory)/'tool-manifest.json',manifest)
    body={'schema_version':1,'run_id':run_id,'content_hash':manifest['content_hash'],
          'engine_root':settings['engine_root'],'dotnet':settings['dotnet']}
    key='simulation-tools:'+run_id
    old=book.connection.execute('SELECT details FROM tasks WHERE task_id=?',(key,)).fetchone()
    if old:
        value=json.loads(old[0])
        if value['content_hash']!=body['content_hash']:
            raise QuantError('SIMULATION_TOOLS_CHANGED','同一运行已绑定其他引擎资源')
    else:book.record_task(key,'SUCCESS',body)


def archived(book,directory,run_id):
    row=book.connection.execute('SELECT details FROM tasks WHERE task_id=?',('simulation-tools:'+run_id,)).fetchone()
    if not row:raise QuantError('SIMULATION_TOOLS_UNAVAILABLE','运行缺少外部引擎资源绑定')
    binding=json.loads(row[0]);manifest=json.loads((Path(directory)/'tool-manifest.json').read_text())
    identity=digest({k:v for k,v in manifest.items() if k!='content_hash'})
    if (manifest.get('schema_version')!=1 or binding.get('schema_version')!=1
            or binding.get('run_id')!=run_id or identity!=manifest.get('content_hash') or identity!=binding.get('content_hash')):
        raise QuantError('CORRUPT_SIMULATION_TOOLS','外部引擎资源清单与已绑定身份不一致')
    return binding,manifest


def resolve(book,directory,run_id,*,engine_root=None,dotnet=None):
    binding,expected=archived(book,directory,run_id)
    if (engine_root is None)!=(dotnet is None):
        raise QuantError('SIMULATION_TOOL_PATHS_REQUIRED','迁移需要同时显式提供LEAN目录及dotnet路径')
    paths={key:str(Path(value).absolute()) for key,value in
           [('engine_root',engine_root or binding['engine_root']),('dotnet',dotnet or binding['dotnet'])]}
    actual=fingerprint(**paths)
    if actual!=expected:
        raise QuantError('SIMULATION_TOOLS_CHANGED','新路径资源内容与原运行不一致，不修改设置或账本')
    if any(paths[key]!=binding[key] for key in paths):
        from ..locks import publication_lock
        with publication_lock(Path(directory).parents[2]),book.transaction():
            audit={**binding,**paths}
            book.record_task('simulation-tool-relocation:'+digest(audit),'SUCCESS',{'from':binding,'to':audit})
            book.record_task('simulation-tools:'+run_id,'SUCCESS',audit)
    return paths
