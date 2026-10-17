"""Freeze a genuinely observed monthly option decision for later paper/manual review.

The signal remains research data. It never creates an order, account event or
broker permission. Historical reconstruction uses the separate monthly module.
"""
import hashlib
import json
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from ..common import QuantError, decimal as D, digest, now_utc, utc, write_json
from ..locks import publication_lock
from .selection import select
from .source import assess_source


FIELDS={'schema_version','monthly_signal_id','intent','input','input_hash','selection','status',
        'decision_at','generated_at','generation_mode','data_type','environment','account_id',
        'source_assessment','snapshot_created_at','applicable_session','applicable_close',
        'execution_assumption','executable','content_hash'}


def validate_forward(body,identity=None):
    if not isinstance(body,dict) or set(body)!=FIELDS:
        raise QuantError('FORWARD_ARCHIVE_CHANGED','前向月度信号字段缺失或未知')
    try:
        selected=body['selection'];basis=body['input'];intent=body['intent']
        decision_basis={'request':basis['request'],'legs':selected['legs'],
                        'rule':{key:selected[key] for key in ('strategy_version','rule_source_hash','rule_source_files')}}
        clock=utc(body['decision_at']);generated=utc(body['generated_at'])
        valid=(body['schema_version']==2 and body['generation_mode']=='forward_observed'
               and body['status']=='FROZEN_FOR_FORWARD_RESEARCH' and body['data_type']=='real_market'
               and body['environment'] in {'paper','real'} and body['executable'] is False
               and set(intent)=={'account_id','environment','template_id','underlying','session'}
               and intent['account_id']==body['account_id'] and intent['environment']==body['environment']
               and digest(intent)==body['monthly_signal_id']
               and (identity is None or identity==body['monthly_signal_id'])
               and digest({k:v for k,v in body.items() if k!='content_hash'})==body['content_hash']
               and digest(basis)==body['input_hash'] and digest(decision_basis)==selected['decision_hash']
               and selected['snapshot_id']==basis['snapshot_id'] and selected['decision_at']==basis['request']['decision_at']
               and selected['template_id']==intent['template_id'] and selected['underlying']==intent['underlying']
               and selected['status']=='SELECTED_FOR_RESEARCH' and selected['data_type']=='real_market'
               and clock==utc(basis['request']['decision_at'])
               and 0<=(generated-clock).total_seconds()<=60*int(basis['max_generation_delay_minutes'])
               and utc(body['snapshot_created_at'])<=generated
               and body['source_assessment']['status']=='QUALIFIED'
               and body['source_assessment']['actual_source_qualified'] is True)
    except (KeyError,TypeError,ValueError,OverflowError):valid=False
    if not valid:raise QuantError('FORWARD_ARCHIVE_CHANGED','前向信号身份、时点、来源或内容哈希不匹配')
    return body


def verify_snapshot(store,body):
    """Recheck archived quote bytes and acquisition clock, including after restore."""
    validate_forward(body)
    contracts,records,metadata,manifest=store.load(body['input']['snapshot_id'])
    captured=utc(manifest['created_at']);decision=utc(body['decision_at'])
    if (metadata['data_type']!='real_market' or manifest['created_at']!=body['snapshot_created_at']
            or captured>utc(body['generated_at'])
            or any(utc(row['received_at'])>captured for row in records)):
        raise QuantError('CORRUPT_FORWARD_SIGNAL','前向信号快照采集时间或类型与冻结依据不同')
    for leg in body['selection']['legs']:
        reference=leg['reference_quote'];name=leg['contract']['contract_id']
        contract=contracts.get(name)
        if (contract is None or contract.version_hash!=leg['contract_version']
                or contract.content()!=leg['contract']):
            raise QuantError('CORRUPT_FORWARD_SIGNAL','前向信号合约条款与冻结期权链不同')
        matching=[row for row in records if row['contract_id']==name
                  and row['exchange_timestamp']==reference['exchange_timestamp']]
        if len(matching)!=1:
            raise QuantError('CORRUPT_FORWARD_SIGNAL','前向信号选约报价在原快照中不存在或不唯一')
        frozen=dict(matching[0])
        for value_field,time_field in (('open_interest','open_interest_available_at'),('last','last_timestamp')):
            if frozen[time_field] is None or utc(frozen[time_field])>decision:
                frozen[value_field]=None;frozen[time_field]=None
        if frozen!=reference:
            raise QuantError('CORRUPT_FORWARD_SIGNAL','前向信号选约报价与当时可用原始行不一致')
    return metadata


def verify_registered(book,store,body):
    """Resolve the exact local signal and its original source decision on retries."""
    try:
        validate_forward(body)
        book._require_account(body['account_id'])
        if body['environment']!=book.environment:
            raise QuantError('CORRUPT_FORWARD_SIGNAL','前向信号环境与账户不同')
        path=book.path.parent/'options/monthly-forward'/(body['monthly_signal_id']+'.json')
        stored=validate_forward(json.loads(path.read_text()),body['monthly_signal_id'])
        if stored!=body:
            raise QuantError('CORRUPT_FORWARD_SIGNAL','前向信号与本账户原冻结归档不同')
        metadata=verify_snapshot(store,body)
        contracts,_,_,_=store.load(body['input']['snapshot_id'])
        selected=[contracts[leg['contract']['contract_id']] for leg in body['selection']['legs']]
        if assess_source(book,metadata,selected,body['decision_at'])!=body['source_assessment']:
            raise QuantError('CORRUPT_FORWARD_SIGNAL','前向信号来源资格与已登记凭据不一致')
    except QuantError as exc:
        if exc.code=='CORRUPT_FORWARD_SIGNAL':raise
        raise QuantError('CORRUPT_FORWARD_SIGNAL','前向信号归档、快照或来源资格无法核验') from exc
    except (OSError,ValueError,TypeError,KeyError) as exc:
        raise QuantError('CORRUPT_FORWARD_SIGNAL','前向信号本地归档无法核验') from exc
    return body


def freeze_forward(book,store,snapshot_id,request,calendar,archive,account_id,*,
                   publication_delay_minutes,max_generation_delay_minutes):
    if book.environment not in {'paper','real'}:
        raise QuantError('FORWARD_ACCOUNT_REQUIRED','前向信号必须绑定独立paper或real账户')
    book._require_account(account_id)
    delay=D(publication_delay_minutes);lag=D(max_generation_delay_minutes)
    if (delay<0 or delay!=delay.to_integral_value() or lag<=0 or lag!=lag.to_integral_value() or lag>60):
        raise QuantError('INVALID_FORWARD_WINDOW','发布延迟及最大生成延迟须显式配置，生成延迟最多60分钟')
    if not isinstance(request,dict) or set(request)!={'template_id','underlying','decision_at','parameters'}:
        raise QuantError('INVALID_OPTION_RULE','前向选约必须有完整固定规则和决策时点')
    clock=utc(request['decision_at']);session=clock.astimezone(ZoneInfo('America/New_York')).date()
    close=calendar.close(session)
    if session not in {day.date() for day in calendar.month_ends()}:
        return {'status':'NO_ACTION','reason':'尚非日历确认的月末交易日','executable':False}
    if clock!=close.to_pydatetime()+timedelta(minutes=int(delay)):
        raise QuantError('MONTHLY_DECISION_TIME','前向决策须使用实际收盘及显式发布延迟')
    trade=calendar.next(session)
    intent={'account_id':account_id,'environment':book.environment,'template_id':request['template_id'],
            'underlying':request['underlying'],'session':str(session)}
    identity=digest(intent)
    basis={'snapshot_id':snapshot_id,'request':request,'calendar_hash':calendar.hash,
           'publication_delay_minutes':int(delay),'max_generation_delay_minutes':int(lag),
           'scheduler_source_hash':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    destination=Path(archive)/(identity+'.json')
    with publication_lock(archive):
        if destination.exists():
            body=validate_forward(json.loads(destination.read_text()),identity)
            if body['input_hash']!=digest(basis):
                raise QuantError('MONTHLY_INPUT_CHANGED','前向月度意图已冻结，不以修订快照覆盖旧信号')
            metadata=verify_snapshot(store,body)
            contracts,_,_,_=store.load(snapshot_id)
            selected=[contracts[leg['contract']['contract_id']] for leg in body['selection']['legs']]
            if assess_source(book,metadata,selected,body['decision_at'])!=body['source_assessment']:
                raise QuantError('CORRUPT_FORWARD_SIGNAL','前向信号来源资格与已登记凭据不一致')
            return body
        generated=utc(now_utc())
        if generated<clock or generated>clock+timedelta(minutes=int(lag)):
            raise QuantError('MISSED_FORWARD_WINDOW','未在月末决策后的允许窗口内实际生成，不能事后冒充前向信号')
        contracts,records,metadata,manifest=store.load(snapshot_id)
        captured=utc(manifest['created_at'])
        if (metadata['data_type']!='real_market' or captured>generated
                or any(utc(row['received_at'])>captured for row in records)):
            raise QuantError('REAL_OPTION_SNAPSHOT_REQUIRED','前向信号需在生成时已采集的真实期权链')
        selected=select(store,snapshot_id,request)
        if selected['status']!='SELECTED_FOR_RESEARCH':
            return {'status':'BLOCKED','reason':'决策时点报价或合约质量不足','selection':selected,'executable':False}
        proof=assess_source(book,metadata,[contracts[leg['contract']['contract_id']] for leg in selected['legs']],clock)
        if proof['status']!='QUALIFIED' or not proof['actual_source_qualified']:
            return {'status':'BLOCKED','reason':'期权来源或合约单位尚未取得实际资格',
                    'checks':proof['checks'],'source_assessment':proof,'executable':False}
        body={'schema_version':2,'monthly_signal_id':identity,'intent':intent,'input':basis,
              'input_hash':digest(basis),'selection':selected,'status':'FROZEN_FOR_FORWARD_RESEARCH',
              'decision_at':clock.isoformat(),'generated_at':generated.isoformat(),
              'generation_mode':'forward_observed','data_type':'real_market','environment':book.environment,
              'account_id':account_id,'source_assessment':proof,'snapshot_created_at':manifest['created_at'],
              'applicable_session':str(trade.date()),'applicable_close':calendar.close(trade).isoformat(),
              'execution_assumption':'next_session_close_after_fresh_quote_account_and_permission_checks',
              'executable':False}
        body['content_hash']=digest(body);validate_forward(body,identity);write_json(destination,body)
        return body
