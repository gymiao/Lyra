"""Public frozen exits consuming verified native prefix receipts, never new orders."""
import hashlib
import json
from pathlib import Path
from ..common import QuantError,decimal as D,digest,utc,now_utc
from ..options.engine import LEAN_COMMIT
from ..options.contracts import OptionContract
from ..options.lifecycle import review
from ..options.exit_tasks import preview_freeze,freeze_exit


def cached(book,signal,event):
    request_id='native-prefix-exit:'+signal['monthly_signal_id']+':'+event['effective_at']
    key='option-exit-freeze:'+digest({'plan_id':event['plan_id'],'request_id':request_id})
    row=book.connection.execute('SELECT details FROM tasks WHERE task_id=?',(key,)).fetchone()
    return json.loads(row[0]) if row else None


def verify_receipt(directory,event,contract,signal_id):
    directory=Path(directory);proof=json.loads((directory/'verification.json').read_text())
    from ..options.adapter_resources import source_hashes
    sources=source_hashes()
    if (proof.get('status')!='PASSED' or proof.get('engine_commit')!=LEAN_COMMIT or proof.get('adapter_source')!=sources
            or hashlib.sha256((directory/'bin/LyraX.Options.dll').read_bytes()).hexdigest()!=proof.get('adapter_dll_sha256')):
        raise QuantError('ENGINE_SOURCE_CHANGED','退出原生前缀源码或程序集不可核验')
    candidates=[e for e in json.loads((directory/'engine-events.json').read_text())
                if str(e['order_id'])+':'+str(e['event_id'])==event['event_id']]
    if len(candidates)!=1:raise QuantError('INVALID_ENGINE_FILL','退出凭据缺少唯一原生订单事件')
    e=candidates[0]
    if (e['order_type']!='MarketOnClose' or e['fee_currency']!='USD'
            or e['tag'] not in {signal_id+'|CLOSE',signal_id+'|CLOSE_DELIVERY_RISK'}
            or utc(e['utc_time'])!=utc(event['effective_at']) or e['right']!=contract.right
            or e['expiry']!=contract.expiry or D(e['strike'])!=contract.strike or e['underlying']!=contract.underlying
            or abs(D(e['quantity']))!=D(event['quantity']) or D(e['price'])!=D(event['price']) or D(e['fee'])!=D(event['fee'])
            or ('BUY' if D(e['quantity'])>0 else 'SELL')!=event['trade_side']):
        raise QuantError('INVALID_ENGINE_FILL','退出记录与成熟引擎方向/单位/金额/时点不一致')
    return digest({'proof':proof,'receipt':e})


def freeze(book,store,signal,event,policy,quote_id,clock):
    body=review(book,event['plan_id'],clock);p=signal['input']['request']['parameters']
    params={'plan_id':event['plan_id'],'as_of':clock.isoformat(),'snapshot_id':quote_id,
        'trigger':'RISK_REDUCTION','exit_days':signal['selection']['exit_days_before_expiry'],
        'fee_per_contract':policy['risk']['fee_per_contract'],'reconciliation_max_days':policy['reconciliation_max_days'],
        **{key:p[key] for key in ('max_age_seconds','max_underlying_skew_seconds','max_spread_fraction','max_leg_skew_seconds','max_underlying_price_fraction')}}
    purpose='OBLIGATION_CLOSE' if all(line['side']=='SELL' for line in body['sizing']['lines']) else 'PROTECTION_WITHDRAWAL'
    request={'request_id':'native-prefix-exit:'+signal['monthly_signal_id']+':'+event['effective_at'],
        'review':params,'execution_at':event['effective_at'],'purpose':purpose,'expected_sequence':book.sequence(body['account_id'])}
    identity=digest({'plan_id':event['plan_id'],'request_id':request['request_id']})
    old=book.connection.execute('SELECT details FROM tasks WHERE task_id=?',('option-exit-freeze:'+identity,)).fetchone()
    if old:return json.loads(old[0])
    preview=preview_freeze(book,store,request)
    return freeze_exit(book,store,request,expected_hash=preview['preview_hash'])


def check_fill(book,proposal,event,receipt_hash):
    p=proposal['proposal'];lines={line['contract_id']:line for line in p['review']['lines']}
    if book.environment!='demo':raise QuantError('DEMO_ONLY','原生前缀退出只用于隔离合成模拟')
    if book.connection.execute('SELECT 1 FROM tasks WHERE task_id=?',('option-exit-cancel:'+p['exit_id'],)).fetchone():
        raise QuantError('OPTION_EXIT_CANCELLED','退出意图已取消，不能继续模拟剩余平仓')
    line=lines.get(event['symbol']);quantity=D(event['quantity'])
    if (not line or quantity<=0 or quantity!=quantity.to_integral_value() or event['trade_side']!=line['side']
            or utc(event['effective_at'])!=utc(p['execution_at']) or D(event['fee'])>quantity*D(p['request']['review']['fee_per_contract'])):
        raise QuantError('INVALID_ENGINE_FILL','退出方向、费用、时间或整张数量不符合冻结计划')
    progress_key='option-exit-prefix-progress:'+p['exit_id']
    old=book.connection.execute('SELECT details FROM tasks WHERE task_id=?',(progress_key,)).fetchone()
    progress=json.loads(old[0]) if old else {'closed':{},'receipts':[]}
    if event['event_id'] in [r['event_id'] for r in progress['receipts']]:raise QuantError('EVENT_CONFLICT','重复退出凭据不能再次推进数量')
    if any(D(progress['closed'].get(key,0))<D(lines[key]['contracts']) for key in line['depends_on']):
        raise QuantError('OPTION_EXIT_DEPENDENCY','必须先实际关闭短腿，才可卖出保护腿')
    total=D(progress['closed'].get(event['symbol'],0))+quantity
    current=review(book,p['plan_id'],event['effective_at'])
    if total>D(line['contracts']) or quantity>D(current['lifecycle']['open_contracts'].get(event['symbol'],0)):
        raise QuantError('INVALID_ENGINE_FILL','退出数量超过冻结义务或本计划实际剩余持仓')
    reference=D(line['reference_price']);price=D(event['price']);adverse=D(current['request']['risk']['adverse_slippage_fraction'])
    if reference<=0 or abs(price/reference-1)>adverse:
        raise QuantError('INVALID_EXIT_QUOTE','原生成交偏离冻结退出价格')
    progress['closed'][event['symbol']]=str(total)
    progress['receipts'].append({'event_id':event['event_id'],'receipt_hash':receipt_hash})
    return progress_key,progress


def record(book,proposal,event,progress_key,progress,marks):
    p=proposal['proposal'];account=p['account_id'];clock=event['effective_at']
    state=book.snapshot(account,clock,marks)
    if state['equity'] is None or state['anomalies'] or D(state['available_cash'])<0:
        raise QuantError('EXIT_RESOURCE_FAILED','退出实际中间状态资金、覆盖或估值异常')
    result=review(book,p['plan_id'],clock)
    book.record_task(progress_key,'SUCCESS',progress)
    if all(D(progress['closed'].get(line['contract_id'],0))==D(line['contracts']) for line in p['review']['lines']):
        if result['lifecycle']['position_status']!='CLOSED':raise QuantError('OPTION_EXIT_INCOMPLETE','冻结退出完成但计划仍有义务')
        audit={'status':'SIMULATED','request':{'exit_id':p['exit_id'],'adapter':'verified_native_prefix'},
            'effective_at':clock,'ledger_seq':book.sequence(account),'account_id':account,'proposal_hash':digest(p),
            'hedge_stage_check':p.get('hedge_stage_check'),'receipts':progress['receipts'],'result':result,'account':state,
            'recorded_at':now_utc(),'meaning':'仅以已核验原生期权平仓事实关闭任务，结算状态另行保留'}
        audit['request_hash']=digest(audit['request'])
        book.record_task('option-exit-simulation:'+p['exit_id'],'SUCCESS',audit)
        audit['account']=book.snapshot(account,clock,marks)
        book.record_task('option-exit-simulation:'+p['exit_id'],'SUCCESS',audit)
