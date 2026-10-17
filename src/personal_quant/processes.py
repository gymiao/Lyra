"""Python worker imports and tool resolution shared by CLI and background jobs."""
import os
from pathlib import Path
import sys
from .common import QuantError


def installed():
    return 'site-packages' in Path(__file__).resolve().parts


def python_command(module):
    return [sys.executable, '-I' if installed() else '-P', '-m', module]


def python_environment():
    env = dict(os.environ)
    for name in ('PYTHONPATH', 'PYTHONHOME', 'PYTHONSTARTUP', 'PYTHONUSERBASE'):
        env.pop(name, None)
    env['PYTHONNOUSERSITE'] = '1'
    if not installed():
        # Editable and source development are explicit: only our own src tree.
        env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1])
    return env


def native_tools(project=None, *, engine_root=None, dotnet=None):
    project = Path(project or Path(__file__).resolve().parents[2])
    engine = Path(engine_root or os.environ.get('LYRAX_TEST_ENGINE_ROOT') or project/'.tools/lean').absolute()
    sdk = Path(dotnet or os.environ.get('LYRAX_TEST_DOTNET') or project/'.tools/dotnet/dotnet').absolute()
    if not engine.is_dir() or not sdk.is_file() or not os.access(sdk, os.X_OK):
        raise QuantError('MISSING_NATIVE_TOOLS', '需明确可用LEAN目录及可执行dotnet；可使用专用环境变量选择外部工具')
    return engine, sdk


def run_owned(command,*,cwd,timeout_seconds=3600):
    """Capture a synchronous Python worker and clean its owned group on interruption."""
    import subprocess
    from .workspace.task_budget import seconds
    child=subprocess.Popen(command,cwd=cwd,env=python_environment(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
    try:
        stdout,stderr=child.communicate(timeout=seconds(timeout_seconds)+5)
    except BaseException as exc:
        from .workspace.batch import _stop
        groups=descendant_groups(child.pid)
        _stop(child)
        stop_descendant_groups(groups)
        if isinstance(exc,subprocess.TimeoutExpired):raise QuantError('TASK_DEADLINE_LIMIT','同步任务总预算到期，保留已提交事实/输出并核对后恢复') from exc
        raise
    return subprocess.CompletedProcess(command,child.returncode,stdout,stderr)


def descendant_groups(parent_pid):
    """Capture only descendants of our live launcher, with PID reuse identities."""
    from .research.service import process_identity
    processes={}
    for file in Path('/proc').glob('[0-9]*/stat'):
        try:
            fields=file.read_text().rsplit(')',1)[1].split()
            processes[int(file.parent.name)]=(int(fields[1]),process_identity(int(file.parent.name)))
        except (OSError,ValueError,IndexError):pass
    owned={parent_pid};changed=True
    while changed:
        added={pid for pid,(ppid,identity) in processes.items() if ppid in owned and identity and pid not in owned}
        changed=bool(added);owned.update(added)
    groups={}
    for pid in owned:
        identity=processes.get(pid,(None,None))[1]
        if not identity:continue
        try:
            group=os.getpgid(pid)
            if group in owned:groups.setdefault(group,[]).append(identity)
        except ProcessLookupError:pass
    return groups


def stop_descendant_groups(groups):
    import signal,time
    from .research.service import process_identity
    def verified(group,members):
        for owner in members:
            try:
                if process_identity(owner['pid'])==owner and os.getpgid(owner['pid'])==group:return True
            except ProcessLookupError:pass
        return False
    for group,members in groups.items():
        if verified(group,members):
            try:os.killpg(group,signal.SIGTERM)
            except ProcessLookupError:pass
    end=time.monotonic()+5
    while any(verified(g,m) for g,m in groups.items()) and time.monotonic()<end:time.sleep(.05)
    for group,members in groups.items():
        if verified(group,members):
            try:os.killpg(group,signal.SIGKILL)
            except ProcessLookupError:pass
