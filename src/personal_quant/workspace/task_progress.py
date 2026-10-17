"""Operational stage receipts; disabled for library calls without an owned job."""
import time
from ..common import now_utc,write_json
_folder=None
_started=None
_events=[]


def configure(folder):
    global _folder,_started,_events
    _folder=folder;_started=time.monotonic();_events=[]


def phase(name):
    if _folder is None:return
    _events.append({'phase':name,'at':now_utc(),'elapsed_seconds':time.monotonic()-_started})
    try:write_json(_folder/'phase.json',{'schema_version':1,'phase':name,'events':_events[-512:]})
    except OSError:pass # Durable job intent/ledger remain authoritative if diagnostics cannot persist.
