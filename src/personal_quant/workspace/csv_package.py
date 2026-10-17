"""CSV preview and explicit content-bound import, reusing normalized price storage."""
import hashlib
import io
from pathlib import Path
import shutil
import tempfile
import pandas as pd
from ..common import QuantError,digest
from ..data.store import DataStore,normalize,REQUIRED
from ..data.calendar import Calendar
from ..locks import publish_directory
from .packages import seal,verify


def _read(content,mapping,calendar_file=None,calendar_kind='verified_market_sessions'):
    if not isinstance(content,bytes) or len(content)>20*1024**2:raise QuantError('CSV_SIZE_LIMIT','CSV需不超过20MiB')
    frame=pd.read_csv(io.BytesIO(content))
    if not isinstance(mapping,dict) or any(k not in frame.columns for k in mapping) or len(set(mapping.values()))!=len(mapping.values()) or set(mapping.values())-set(REQUIRED):
        raise QuantError('INVALID_CSV_MAPPING','字段映射需源列存在且目标标准列唯一')
    frame=frame.rename(columns=mapping)
    if frame.columns.duplicated().any():raise QuantError('INVALID_CSV_MAPPING','映射后列名重复')
    if not {'session_date','available_at'}<=set(frame):raise QuantError('MISSING_CSV_TIME','需显式市场日期和带时区可用时间')
    import re
    if any(not isinstance(x,str) or not re.search(r'(Z|[+-]\d\d:\d\d)$',x) for x in frame.available_at):
        raise QuantError('AMBIGUOUS_CSV_TIMEZONE','available_at必须明确时区，不猜测本地时区')
    calendar=Calendar.csv(Path(calendar_file),calendar_kind) if calendar_file else Calendar.market(str(frame.session_date.min()),str(pd.Timestamp(frame.session_date.max())+pd.Timedelta(days=45))[:10])
    return normalize(frame,calendar),calendar,len(frame)


def preview(content,mapping,*,calendar_file=None,calendar_kind='verified_market_sessions'):
    frame,calendar,input_rows=_read(content,mapping,calendar_file,calendar_kind)
    body={'schema_version':1,'csv_sha256':hashlib.sha256(content).hexdigest(),'mapping':mapping,
          'calendar_file':str(calendar_file) if calendar_file else None,'calendar_kind':calendar_kind,
          'calendar_hash':calendar.hash,'input_rows':input_rows,'normalized_rows':len(frame),'duplicates_removed':input_rows-len(frame),
          'symbols':sorted(frame.symbol.unique()),'data_type':str(frame.data_type.iloc[0]),
          'start':str(frame.session_date.min().date()),'end':str(frame.session_date.max().date()),
          'checks':[] if set(frame.price_basis)=={'unadjusted'} else ['RAW_EXECUTION_PRICES_REQUIRED'],
          'financial_events_added':0,'executable':False}
    body['preview_id']=digest(body);return body


def commit(file,mapping,destination,expected_preview,*,calendar_file=None,calendar_kind='verified_market_sessions'):
    content=Path(file).read_bytes();current=preview(content,mapping,calendar_file=calendar_file,calendar_kind=calendar_kind)
    if current['preview_id']!=expected_preview:raise QuantError('CSV_PREVIEW_CHANGED','输入、映射或日历改变，请重新预检')
    if current['checks']:raise QuantError('CSV_PACKAGE_BLOCKED','用途不完整，复权价不能作为真实份额成交参考')
    destination=Path(destination).absolute()
    if destination.exists():raise QuantError('NONEMPTY_DESTINATION','CSV包需新输出目录')
    destination.parent.mkdir(parents=True,exist_ok=True);pending=Path(tempfile.mkdtemp(prefix='.pending-csv-',dir=destination.parent))
    try:
        frame,calendar,_=_read(content,mapping,calendar_file,calendar_kind)
        saved=DataStore(pending/'data').save(frame,calendar)
        body=seal(pending,roles={r:saved['snapshot_id'] for r in ('signal','execution','valuation')},spec={'csv_preview_id':expected_preview})
        verify(pending);publish_directory(pending,destination)
        return {'status':'IMPORTED','input_bundle_id':body['input_bundle_id'],'directory':str(destination),'financial_events_added':0,'source_qualification':'UNVERIFIED'}
    finally:
        if pending.exists():shutil.rmtree(pending)
