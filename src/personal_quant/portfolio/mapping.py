"""Declarative statement mapping: no expressions, guessed IDs or executable code."""
from datetime import datetime
import hashlib
from zoneinfo import ZoneInfo
import pandas as pd
from pytz.exceptions import AmbiguousTimeError, NonExistentTimeError
from ..common import QuantError, decimal, digest, utc, canonical, now_utc
from .imports import _rows

FIELDS={'event_id','kind','effective_at','source','evidence_type','account_id','environment','currency','symbol',
        'plan_id','reference_event_id','amount','quantity','price','fee','ratio','settlement_at'}


def validate_mapping(mapping):
    required={'schema_version','mapping_id','revision','source','columns','constants','kind_values',
              'datetime_format','timezone','absolute_fields','fee_policy','dividend_basis'}
    if not isinstance(mapping,dict) or set(mapping)!=required or mapping['schema_version']!=1 or type(mapping['revision']) is not int or mapping['revision']<1:
        raise QuantError('INVALID_STATEMENT_MAPPING','映射规格字段或修订无效')
    if not isinstance(mapping['columns'],dict) or not isinstance(mapping['constants'],dict):
        raise QuantError('INVALID_STATEMENT_MAPPING','列映射和常量必须为对象')
    columns,constants=mapping['columns'],mapping['constants']
    if set(columns)&set(constants) or (set(columns)|set(constants))-FIELDS or any(not isinstance(v,str) or not v for v in columns.values()):
        raise QuantError('INVALID_STATEMENT_MAPPING','映射包含未知、重复字段或非法来源列')
    if not {'event_id','kind','effective_at'}<=columns.keys() or 'source' in columns or 'source' in constants:
        raise QuantError('INVALID_STATEMENT_MAPPING','稳定ID、类型、时间必须映射；来源由规格固定')
    if any(not isinstance(mapping[k],str) or not mapping[k].strip() for k in ('mapping_id','source','datetime_format','timezone')):
        raise QuantError('INVALID_STATEMENT_MAPPING','映射身份、来源、时间格式和时区不可为空')
    if not isinstance(mapping['kind_values'],dict) or not mapping['kind_values']:
        raise QuantError('INVALID_STATEMENT_MAPPING','必须显式声明类型映射')
    allowed={'BUY','SELL','DEPOSIT','WITHDRAWAL','DIVIDEND','FEE','SPLIT','DIVIDEND_ACCRUAL','DIVIDEND_PAYMENT'}
    if any(k not in allowed for k in mapping['kind_values'].values()):raise QuantError('INVALID_STATEMENT_MAPPING','未支持的事件类型')
    if not isinstance(mapping['absolute_fields'],list) or set(mapping['absolute_fields'])-{'quantity','amount','fee'}:
        raise QuantError('INVALID_STATEMENT_MAPPING','仅金额、数量、费用支持明确绝对值转换')
    if mapping['fee_policy'] not in {'trade_fee_included','separate_fee_rows'} or mapping['dividend_basis']!='net_cash':
        raise QuantError('INVALID_STATEMENT_MAPPING','需声明费用单一来源及分红净到账口径；总额/预扣税待独立核对')
    try:ZoneInfo(mapping['timezone'])
    except (KeyError,ValueError) as exc:raise QuantError('INVALID_STATEMENT_MAPPING','未知时区') from exc
    return mapping


def map_statement(content, mapping):
    mapping=validate_mapping(mapping);raw=_rows(content);events=[];pending=[]
    def timestamp(value):
        parsed=datetime.strptime(value,mapping['datetime_format'])
        if parsed.tzinfo is None:
            # Reject ambiguous/nonexistent DST instants instead of silently choosing a fold.
            parsed=pd.Timestamp(parsed).tz_localize(mapping['timezone'],ambiguous='raise',nonexistent='raise').to_pydatetime()
        return utc(parsed).isoformat()
    for line,row in enumerate(raw,2):
        try:
            missing=[column for target,column in mapping['columns'].items() if column not in row and target in {'event_id','kind','effective_at'}]
            if missing:raise QuantError('MISSING_MAPPED_FIELD','缺少必需来源列：'+str(missing))
            event={**mapping['constants'],**{target:row[column] for target,column in mapping['columns'].items() if column in row}}
            kind=mapping['kind_values'].get(event['kind'])
            if not kind:raise QuantError('UNKNOWN_STATEMENT_KIND','未定义来源类型：'+str(event['kind']))
            event['kind']=kind;event['source']=mapping['source']
            event['event_id']=mapping['source']+':'+event['event_id']
            for field in mapping['absolute_fields']:
                if field in event:event[field]=str(abs(decimal(event[field])))
            for field in ('effective_at','settlement_at'):
                if field in event:event[field]=timestamp(event[field])
            if mapping['fee_policy']=='trade_fee_included' and kind=='FEE':
                raise QuantError('AMBIGUOUS_FEE','独立费用行与成交费用可能重复，请核对后采用单一来源')
            if mapping['fee_policy']=='separate_fee_rows' and decimal(event.get('fee',0)):
                raise QuantError('AMBIGUOUS_FEE','独立费用模式不得同时导入成交附带费用')
            events.append(event)
        except (QuantError,KeyError,ValueError,TypeError,AmbiguousTimeError,NonExistentTimeError) as exc:
            pending.append({'line':line,'reason':str(exc),'raw':row})
    raw_bytes=content if isinstance(content,bytes) else content.encode('utf-8')
    return {'status':'BLOCKED' if pending else 'READY_FOR_PREVIEW','mapping_hash':digest(mapping),
            'mapping_id':mapping['mapping_id'],'revision':mapping['revision'],
            'original_file_hash':hashlib.sha256(raw_bytes).hexdigest(),'events':events,'pending':pending,
            'event_hash':digest(events),'read_only':True}


def mapped_import(ledger,account_id,content,mapping,as_of,*,commit=False,expected_sequence=None,expected_hash=None,prices=None):
    if ledger.connection.execute('SELECT version FROM schema_version').fetchone()[0]<5:
        raise QuantError('V19_NOT_ENABLED','映射归档需要先备份升级v1.9')
    result=map_statement(content,mapping)
    if result['pending']:
        if commit:raise QuantError('MAPPING_REVIEW_REQUIRED','有未核实行，不得部分提交后隐藏疑点')
        return result
    if not commit:
        return {**result,'preview':ledger.preview(account_id,result['events'],as_of,prices),
                'expected_hash':digest({'file':result['original_file_hash'],'mapping':result['mapping_hash'],'events':result['event_hash']})}
    identity=digest({'file':result['original_file_hash'],'mapping':result['mapping_hash'],'events':result['event_hash']})
    if expected_hash!=identity or expected_sequence is None:
        raise QuantError('PREVIEW_REQUIRED','映射提交须提供文件/映射/事件合并预检哈希及账户序号')
    with ledger.transaction():
        existing=ledger.connection.execute('SELECT content_hash FROM statement_mappings WHERE mapping_id=? AND revision=?',
            (mapping['mapping_id'],mapping['revision'])).fetchone()
        if existing and existing[0]!=result['mapping_hash']:
            raise QuantError('MAPPING_VERSION_CONFLICT','映射修订已冻结，修改需新修订号')
        outcome=ledger.import_events(account_id,result['events'],expected_sequence)
        ledger.connection.execute('INSERT OR IGNORE INTO statement_mappings VALUES(?,?,?,?,?)',
            (mapping['mapping_id'],mapping['revision'],canonical(mapping),result['mapping_hash'],now_utc()))
        ledger.connection.execute('INSERT OR IGNORE INTO mapped_imports VALUES(?,?,?,?)',
            (digest({'account':account_id,'preview':identity}),account_id,canonical({key:value for key,value in result.items() if key!='events'}),now_utc()))
    return {**outcome,'mapping_hash':result['mapping_hash'],'original_file_hash':result['original_file_hash']}
