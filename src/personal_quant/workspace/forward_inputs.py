"""Local forward-observation manifest contract, separate from historical replay."""
import json
from pathlib import Path
from ..common import QuantError,digest,utc,now_utc,write_json
from ..locks import publication_lock


def append(directory,request,*,clock=None,test_clock=False):
    required={'session','observed_at','available_at','processed_at','input_bundle_id','data_type'}
    if not isinstance(request,dict) or set(request)!=required or not isinstance(request['input_bundle_id'],str) or len(request['input_bundle_id'])!=64:
        raise QuantError('INVALID_FORWARD_INPUT','前向日输入需明确日期、三种时点及输入身份')
    from datetime import date
    try:
        if date.fromisoformat(request['session']).isoformat()!=request['session']:raise ValueError('session')
    except (TypeError,ValueError) as exc:raise QuantError('INVALID_FORWARD_SESSION','前向会话需有效市场日期') from exc
    actual=utc(now_utc())
    if clock is not None and test_clock is not True:raise QuantError('FORWARD_CLOCK_INJECTION_FORBIDDEN','正式前向不得注入回填时钟')
    now=utc(clock) if test_clock and clock else actual
    observed,available,processed=(utc(request[k]) for k in ('observed_at','available_at','processed_at'))
    if not observed<=available<=processed<=now:raise QuantError('FORWARD_INPUT_NOT_AVAILABLE','输入尚不可用或处理时点顺序错误')
    if not test_clock and (actual-processed).total_seconds()>300:raise QuantError('HISTORICAL_FORWARD_PROCESSING_FORBIDDEN','正式处理时点需当前真实时间，不能回填历史决定')
    if request['data_type'] not in {'real_market','synthetic','model'}:raise QuantError('INVALID_FORWARD_DATA_TYPE','需明确真实、合成或模型类型')
    root=Path(directory);root.mkdir(parents=True,exist_ok=True)
    with publication_lock(root):
        path=root/'forward-inputs.json';body=json.loads(path.read_text()) if path.exists() else {'schema_version':1,'run_mode':'forward_paper','entries':[]}
        for old in body['entries']:
            if old['input']['session']==request['session']:
                if old['input']!=request:raise QuantError('FORWARD_INPUT_REVISION_REQUIRES_NEW_EXPERIMENT','已有日输入不可修订，保留旧信号/事实')
                return {**old,'repeated':True}
        if body['entries'] and (request['session']<=body['entries'][-1]['input']['session'] or processed<utc(body['entries'][-1]['input']['processed_at'])):
            raise QuantError('LATE_FORWARD_INPUT','迟到历史数据需独立研究，不能补造原决定')
        old=body['entries'][-1]['entry_hash'] if body['entries'] else None
        entry={'input':request,'previous_hash':old,'test_clock':test_clock,'natural_forward_verified':False}
        entry['entry_hash']=digest(entry);body['entries'].append(entry);write_json(path,body)
        return entry
