"""Reentrant local publication locks; acquire before any SQLite write transaction."""
from contextlib import contextmanager
import fcntl
from pathlib import Path
import threading
import time
from .common import QuantError

_guard = threading.Lock()
_locks = {}
_local = threading.local()


def publish_directory(staged, target):
    """Keep rename atomic; retry transient WSL/Windows directory sharing failures."""
    staged,target=Path(staged),Path(target)
    if staged.parent!=target.parent or not staged.is_dir():
        raise QuantError('INVALID_PUBLICATION_PATH','发布需同目录的完整暂存目录')
    for attempt in range(5):
        if target.exists():raise QuantError('PUBLICATION_CONFLICT','目标已存在，不能覆盖原归档')
        try:
            staged.rename(target)
            return
        except PermissionError as exc:
            if attempt==4:
                raise QuantError('PUBLICATION_PERMISSION_DENIED','目录原子发布被系统拒绝；原账本未激活，请核对文件占用及目录权限后重跑') from exc
            time.sleep(.1*(2**attempt))


@contextmanager
def publication_lock(runtime, timeout=10):
    path = Path(runtime).absolute() / '.publication.lock'
    key = str(path)
    with _guard:
        lock = _locks.setdefault(key, threading.RLock())
    if not lock.acquire(timeout=timeout):
        raise QuantError('PUBLICATION_BUSY', '发布正在进行，请稍后重试')
    owned = getattr(_local, 'owned', {})
    handle = None
    try:
        if key not in owned:
            path.parent.mkdir(parents=True, exist_ok=True)
            handle = path.open('a+')
            deadline = time.monotonic() + timeout
            while True:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise QuantError('PUBLICATION_BUSY', '其他进程正在发布，未抢占锁')
                    time.sleep(.05)
            owned[key] = handle
            _local.owned = owned
        yield
    finally:
        if handle is not None:
            owned.pop(key, None)
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()
        lock.release()
