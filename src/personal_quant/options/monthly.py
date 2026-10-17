"""Freeze calendar-qualified monthly research decisions; never grant execution permission."""
import hashlib
import json
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from ..common import QuantError, decimal, digest, now_utc, utc, write_json
from ..locks import publication_lock
from .selection import select


def validate_frozen(body, identity=None):
    if not isinstance(body,dict):raise QuantError('MONTHLY_ARCHIVE_CHANGED','冻结月度信号必须为对象')
    try:
        payload={key:value for key,value in body.items() if key!='content_hash'}
        selection=body['selection']
        decision_basis={'request':body['input']['request'],'legs':selection['legs'],
            'rule':{key:selection[key] for key in ['strategy_version','rule_source_hash','rule_source_files']}}
        valid=(body['schema_version']==1 and body['generation_mode']=='historical_reconstruction'
               and digest(payload)==body['content_hash'] and digest(body['input'])==body['input_hash']
               and digest(decision_basis)==selection['decision_hash']
               and digest(body['intent'])==body['monthly_signal_id']
               and (identity is None or identity==body['monthly_signal_id'])
               and body['selection']['snapshot_id']==body['input']['snapshot_id']
               and body['selection']['decision_at']==body['input']['request']['decision_at']
               and body['selection']['template_id']==body['intent']['template_id']
               and body['selection']['underlying']==body['intent']['underlying']
               and body['selection']['status']=='SELECTED_FOR_RESEARCH'
               and body['status']=='FROZEN_FOR_RESEARCH' and body['executable'] is False)
    except (KeyError,TypeError,ValueError):
        valid=False
    if not valid:
        raise QuantError('MONTHLY_ARCHIVE_CHANGED', '冻结月度信号身份或内容哈希不匹配')
    return body


def freeze_monthly(store, snapshot_id, request, calendar, archive, *, scope, publication_delay_minutes):
    if not isinstance(scope, str) or not scope.strip():
        raise QuantError('INVALID_MONTHLY_SCOPE', '必须显式提供独立研究/账户范围')
    delay=decimal(publication_delay_minutes)
    if delay<0 or delay!=delay.to_integral_value():
        raise QuantError('INVALID_PUBLICATION_DELAY', '发布延迟必须为非负整数分钟')
    clock=utc(request['decision_at'])
    session=clock.astimezone(ZoneInfo('America/New_York')).date()
    # The following month must be covered; the final downloaded day is not month-end proof.
    close=calendar.close(session)
    if session not in {day.date() for day in calendar.month_ends()}:
        return {'status':'NO_ACTION','reason':'不是日历确认的月末交易日','executable':False}
    decision=close.to_pydatetime()+timedelta(minutes=int(delay))
    if clock!=decision:
        raise QuantError('MONTHLY_DECISION_TIME', '月度决策时点必须为该交易日实际收盘加显式发布延迟')
    if clock>utc(now_utc()):
        raise QuantError('FUTURE_MONTHLY_DECISION', '不得冻结尚未到达的月度决策')
    trade=calendar.next(session)
    intent={'scope':scope,'template_id':request['template_id'],'underlying':request['underlying'],
            'session':str(session)}
    identity=digest(intent)
    basis={'snapshot_id':snapshot_id,'request':request,'calendar_hash':calendar.hash,
           'publication_delay_minutes':int(delay),
           'scheduler_source_hash':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    archive=Path(archive)
    with publication_lock(archive):
        path=archive/(identity+'.json')
        if path.exists():
            body=validate_frozen(json.loads(path.read_text()),identity)
            if body['input_hash']!=digest(basis):
                raise QuantError('MONTHLY_INPUT_CHANGED', '本月意图已冻结，修订输入不能覆盖原始信号')
            return body
        selected=select(store,snapshot_id,request)
        if selected['status']!='SELECTED_FOR_RESEARCH':
            return {'status':'BLOCKED','reason':'月末选约数据不足或质量不通过','selection':selected,'executable':False}
        body={'schema_version':1,'monthly_signal_id':identity,'intent':intent,'input':basis,
              'input_hash':digest(basis),'selection':selected,'status':'FROZEN_FOR_RESEARCH',
              'decision_at':clock.isoformat(),'generated_at':now_utc(),
              'generation_mode':'historical_reconstruction','executable':False,
              'applicable_session':str(trade.date()),'applicable_close':calendar.close(trade).isoformat(),
              'execution_assumption':'next_session_close_requires_engine_validation'}
        body['content_hash']=digest(body)
        write_json(path,body)
        return body
