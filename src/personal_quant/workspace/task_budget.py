"""Owned worker deadline, with persistent intent and no financial rollback claims."""
from contextlib import contextmanager
from datetime import timedelta
import math
import os
import signal
import threading
from ..common import QuantError,now_utc,utc
from ..research.service import process_identity

DEFAULT_SECONDS=3600


def seconds(value):
    value=DEFAULT_SECONDS if value is None else value
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<value<=86400:
        raise QuantError('INVALID_TASK_BUDGET','任务总预算须为0至86400秒内有限正数')
    return float(value)


def deadline(submitted_at,value):return (utc(submitted_at)+timedelta(seconds=seconds(value))).isoformat()


@contextmanager
def enforce(deadline_at):
    """Worker must own its process group; signal also stops its native descendants."""
    owned=os.getpgrp()==os.getpid()
    if not owned:
        if deadline_at:raise QuantError('UNOWNED_TASK_GROUP','预算任务必须在自己的进程组执行')
        yield;return
    remaining=(utc(deadline_at)-utc(now_utc())).total_seconds() if deadline_at else None
    if remaining is not None and remaining<=0:raise QuantError('TASK_DEADLINE_LIMIT','队列/启动已用完总预算；未启动业务操作')
    owner=process_identity();expired=threading.Event()
    def interrupted(signum,frame):
        code='TASK_DEADLINE_LIMIT' if expired.is_set() else 'TASK_INTERRUPTED'
        raise QuantError(code,'任务已中断；已提交事实和发布目录须核实，不能假定操作未发生')
    def stop_owned():
        if owner==process_identity() and os.getpgrp()==os.getpid():
            expired.set();os.killpg(os.getpid(),signal.SIGTERM)
    previous=signal.signal(signal.SIGTERM,interrupted)
    timer=threading.Timer(remaining,stop_owned) if remaining is not None else None
    if timer:timer.daemon=True;timer.start()
    try:yield
    finally:
        if timer:timer.cancel()
        signal.signal(signal.SIGTERM,previous)
