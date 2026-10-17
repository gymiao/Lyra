"""Explicit localhost workspace viewers; never terminate an unknown process."""
from pathlib import Path
import json
import socket
import subprocess
from ..common import QuantError,write_json,now_utc
from ..processes import python_command,python_environment
from ..execution.daily import daily_lock
from ..research.service import process_identity,worker_alive
from .service import read_workspace


def open_viewer(directory,port):
    if type(port) is not int or not 1024<=port<=65535:raise QuantError('INVALID_UI_PORT','本地端口需1024至65535')
    root,identity,config,path=read_workspace(directory);runtime=root/config.runtime_dir
    record=runtime/'simulation/ui-server.json'
    with daily_lock(runtime/'.ui-server.lock'):
        if record.exists():
            try:
                old=json.loads(record.read_text())
                if old.get('workspace_id')==identity['workspace_id'] and worker_alive(old['owner']):return {**old,'repeated':True}
            except (ValueError,KeyError,TypeError):raise QuantError('UI_OWNER_UNVERIFIED','历史界面记录损坏，请核实后恢复，不杀未知服务')
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
            try:probe.bind(('127.0.0.1',port))
            except OSError as exc:raise QuantError('UI_PORT_UNAVAILABLE','端口已占用，请换端口；不会停止其他服务') from exc
        app=Path(__file__).absolute().parents[1]/'ui/app.py'
        command=[*python_command('streamlit'),'run',str(app),'--server.address','127.0.0.1','--server.port',str(port),
            '--server.headless','true','--server.fileWatcherType','none','--browser.gatherUsageStats','false','--','--config',str(path)]
        child=None
        try:
            with (runtime/'simulation/ui-server.log').open('w') as log:
                child=subprocess.Popen(command,cwd=root,env=python_environment(),stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            result={'workspace_id':identity['workspace_id'],'owner':process_identity(child.pid),'port':port,
                    'url':f'http://127.0.0.1:{port}','started_at':now_utc()}
            write_json(record,result);return result
        except BaseException:
            if child is not None:
                from .batch import _stop
                _stop(child)
            raise


def stop_viewer(directory):
    import os,signal
    root,identity,config,_=read_workspace(directory)
    record=root/config.runtime_dir/'simulation/ui-server.json'
    if not record.exists():return {'status':'NOT_RUNNING'}
    body=json.loads(record.read_text());owner=body['owner']
    if body['workspace_id']!=identity['workspace_id']:raise QuantError('UI_OWNER_UNVERIFIED','界面归属不一致')
    if not worker_alive(owner):return {'status':'NOT_RUNNING','previous':body}
    pid=owner['pid']
    if os.getpgid(pid)!=pid:raise QuantError('UI_OWNER_UNVERIFIED','不是登记的独立进程组，拒绝停止')
    os.killpg(pid,signal.SIGTERM)
    import time
    end=time.monotonic()+5
    while worker_alive(owner) and time.monotonic()<end:time.sleep(.05)
    if worker_alive(owner) and os.getpgid(pid)==pid:
        os.killpg(pid,signal.SIGKILL)
        end=time.monotonic()+2
        while worker_alive(owner) and time.monotonic()<end:time.sleep(.05)
    return {'status':'STOP_REQUESTED' if worker_alive(owner) else 'STOPPED','owner':owner,'financial_events_added':0}
