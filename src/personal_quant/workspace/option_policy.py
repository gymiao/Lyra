"""Freeze simulation planning inputs and connect native facts to public plans."""
import json
from pathlib import Path
import shutil
import tempfile
import pandas as pd
from ..common import QuantError,decimal as D,digest,write_json,utc
from ..locks import publish_directory
from ..options.data import OptionDataStore
from ..options.plans import RISK_FIELDS,draft
from ..options.qualification import assess_engine
from ..options.lifecycle import review


def freeze_policy(request,directory,fee):
    policy=request['plan_policy']
    fields={'schema_version','chain_root','engine_evidence_files','risk','reconciliation_max_days'}
    if not isinstance(policy,dict) or set(policy) not in (fields,fields|{'execution_window_sessions'}) or policy['schema_version']!=1:
        raise QuantError('INVALID_SIMULATION_PLAN_POLICY','计划模式需要完整schema1、链归档、资格、风险和对账参数')
    risk=policy['risk']
    if not isinstance(risk,dict) or set(risk)!=RISK_FIELDS or any(D(v)<0 for v in risk.values()):
        raise QuantError('INVALID_OPTION_RISK','模拟计划须冻结全部非负风险参数')
    if (D(risk['fee_per_contract'])!=D(fee) or D(risk['maximum_contracts'])!=D(risk['maximum_contracts']).to_integral_value()
            or D(risk['adverse_slippage_fraction'])>=1):
        raise QuantError('INVALID_OPTION_RISK','计划费用须与原生费用一致，张数整数且滑点小于1')
    days=D(policy['reconciliation_max_days'])
    if days<0 or days!=days.to_integral_value():raise QuantError('INVALID_SIMULATION_PLAN_POLICY','对账期限须为非负整数')
    window=policy.get('execution_window_sessions')
    if window is not None and (type(window) is not int or window<1):
        raise QuantError('INVALID_OPTION_EXECUTION_WINDOW','模拟执行窗口须为明确的正整数交易日数')
    templates={s['selection']['template_id'] for s in request['signals']}
    evidence=policy['engine_evidence_files']
    if not isinstance(evidence,dict) or set(evidence)!=templates:
        raise QuantError('INVALID_SIMULATION_PLAN_POLICY','须逐模板提供当前源码生命周期资格')
    # Validate everything before copying. Frozen chains reproduce selection,
    # rather than reconstructing a smaller chain from only the chosen legs.
    source=OptionDataStore(policy['chain_root']);loaded={}
    from ..options.selection import select
    for signal in request['signals']:
        identity=signal['input']['snapshot_id']
        loaded[identity]=source.load(identity)
        if loaded[identity][2]['data_type']!='synthetic' or select(source,identity,signal['input']['request'])!=signal['selection']:
            raise QuantError('SIMULATION_PLAN_CHAIN_MISMATCH','完整合成链不能复现冻结选约')
    assessed={}
    for template,file in evidence.items():
        result=assess_engine(file,template)
        if result['status']!='PASSED':raise QuantError('ENGINE_LIFECYCLE_UNQUALIFIED','计划模式的生命周期资格未通过当前源码核验')
        assessed[template]=result
    directory=Path(directory);target=OptionDataStore(directory/'plan-chains')
    for identity,(contracts,quotes,metadata,_) in loaded.items():
        if target.save(list(contracts.values()),pd.DataFrame(quotes),metadata)['snapshot_id']!=identity:
            raise QuantError('SIMULATION_PLAN_CHAIN_MISMATCH','复制链内容身份变化')
    frozen={}
    for template,file in evidence.items():
        source_dir=Path(file).absolute().parent
        dest=directory/'plan-evidence'/assessed[template]['evidence_hash']
        if source_dir==dest or dest.resolve().is_relative_to(source_dir.resolve()) or any(p.is_symlink() for p in source_dir.rglob('*')):
            raise QuantError('UNSAFE_ENGINE_EVIDENCE','资格归档不接受链接或复制到自身内部')
        if not dest.exists():
            dest.parent.mkdir(parents=True,exist_ok=True)
            staged=Path(tempfile.mkdtemp(prefix='.pending-',dir=dest.parent))
            try:
                shutil.copytree(source_dir,staged,dirs_exist_ok=True)
                check=assess_engine(staged/'verification.json',template)
                if check['status']!='PASSED' or check['evidence_hash']!=assessed[template]['evidence_hash']:
                    raise QuantError('ENGINE_EVIDENCE_CHANGED','冻结期间资格内容改变')
                publish_directory(staged,dest)
            finally:
                if staged.exists():shutil.rmtree(staged)
        if assess_engine(dest/'verification.json',template)['status']!='PASSED':
            raise QuantError('ENGINE_EVIDENCE_CHANGED','冻结资格不可核验')
        frozen[template]=str((dest/'verification.json').relative_to(directory))
    result={'schema_version':1,'risk':risk,'reconciliation_max_days':int(days),'engine_evidence_files':frozen,
            'chain_snapshots':sorted(loaded),'request_hash':digest(policy),'execution_window_sessions':window}
    write_json(directory/'plan-policy.json',result)
    return result


def plan_identity(account_id,signal,packages,risk):
    intent=digest({'account_id':account_id,'decision_hash':signal['selection']['decision_hash'],'risk':risk,'packages':packages})
    return digest({'intent_id':intent,'revision':1})


def current_marks(path,day):
    marks={s:values[day] for s,values in path['stocks'].items()}
    marks.update({s:str((D(values[day]['bid'])+D(values[day]['ask']))/2) for s,values in path['options'].items() if day in values})
    return marks


def refresh_reference(book,store,signal,path,account_id,clock):
    day=pd.Timestamp(clock).tz_convert('America/New_York').strftime('%Y-%m-%d')
    contracts,quotes,metadata,_=store.load(signal['input']['snapshot_id'])
    selected={l['contract']['contract_id'] for l in signal['selection']['legs']};fresh=[]
    for identity in selected:
        original=max((q for q in quotes if q['contract_id']==identity and utc(q['received_at'])<=utc(signal['decision_at'])),key=lambda q:utc(q['exchange_timestamp']))
        at=(pd.Timestamp(clock)-pd.Timedelta(minutes=1)).isoformat()
        row={**original,**path['options'][identity][day],'underlying_price':path['stocks'][contracts[identity].underlying][day]}
        for field in ('exchange_timestamp','available_at','received_at','underlying_timestamp','last_timestamp'):row[field]=at
        row['last']=str((D(row['bid'])+D(row['ask']))/2);fresh.append(row)
    quote_id=store.save([contracts[k] for k in selected],pd.DataFrame(fresh),metadata)['snapshot_id']
    marks=current_marks(path,day);snapshot=book.snapshot(account_id,clock,marks)
    if snapshot['equity'] is None or snapshot['anomalies']:
        raise QuantError('SIMULATION_PLAN_ACCOUNT_BLOCKED','计划前账本不完整或存在异常')
    book.reconcile(account_id,{'account_id':account_id,'currency':'USD','as_of':clock.isoformat(),
        'cash_basis':'settled','cash':snapshot['settled_cash'],'positions':snapshot['positions'],
        'option_positions':snapshot['option_positions'],'equity':snapshot['equity'],'source':'internal_simulation_check'},marks)
    return quote_id,marks


def bind_events(rows,cycles,signals,packages,account_id,policy,run_id=None):
    """Explicit cycle/contract association, never infer from similar fill prices."""
    mapping={s['monthly_signal_id']:(s,n) for s,n in zip(signals,packages)}
    result=[]
    for event in rows:
        if event['kind'] in {'BUY','SELL'} and run_id:
            from .stock_policy import match,identity
            cycle,day=match(event,cycles)
            result.append({**event,'plan_id':identity(run_id,cycle,event['kind'],day)})
            continue
        if not event['kind'].startswith('OPTION_'):
            result.append(event);continue
        day=pd.Timestamp(event['effective_at']).tz_convert('America/New_York').strftime('%Y-%m-%d')
        matches=[c for c in cycles if c['entry_submit_at'][:10]<=day<=c['exit_submit_at'][:10]
                 and any(l['contract_id']==event['symbol'] for l in c['legs'])]
        if len(matches)!=1:raise QuantError('SIMULATION_PLAN_ASSOCIATION','原生期权事实不能唯一关联冻结周期')
        signal,n=mapping[matches[0]['signal_id']]
        result.append({**event,'plan_id':plan_identity(account_id,signal,n,policy['risk'])})
    return result


def import_planned_events(book,directory,account_id,rows,signals,packages,path,policy,*,config=None,run_id=None,cycles=None,native_directory=None):
    """Activate before each observed opening fill; commit with the outer transaction."""
    if book.environment!='demo':raise QuantError('DEMO_ONLY','原生计划关联仅用于明确的合成模拟账户')
    from ..options.activation import activate
    store=OptionDataStore(Path(directory)/'plan-chains')
    by_plan={plan_identity(account_id,s,n,policy['risk']):(s,n) for s,n in zip(signals,packages)}
    added=0
    for event in rows:
        if book.connection.execute('SELECT 1 FROM events WHERE account_id=? AND event_id=?',(account_id,event['event_id'])).fetchone():continue
        if event['kind'] in {'BUY','SELL'}:
            from .stock_policy import match,prepare
            cycle,day=match(event,cycles)
            if prepare(book,config,account_id,run_id,cycle,event['kind'],day,path)!=event['plan_id']:
                raise QuantError('SIMULATION_STOCK_ASSOCIATION','股票事实的明确计划身份不一致')
        if event['kind']=='OPTION_TRADE' and event['action']=='OPEN':
            signal,n=by_plan[event['plan_id']]
            body=draft(book,store,signal['input']['snapshot_id'],account_id,
                {'selection':signal['input']['request'],'packages':n,'risk':policy['risk'],'revision':1})
            if not body.get('activation'):
                close=utc(event['effective_at']);clock=(pd.Timestamp(close)-pd.Timedelta(minutes=20)).to_pydatetime()
                day=pd.Timestamp(clock).tz_convert('America/New_York').strftime('%Y-%m-%d')
                quote_id,marks=refresh_reference(book,store,signal,path,account_id,clock)
                authority={'request_id':'workspace-native-open','plan_id':body['plan_id'],
                    'as_of':clock.isoformat(),'valid_until':close.isoformat(),'expected_sequence':book.sequence(account_id),
                    'monthly_signal':signal,'engine_evidence_file':str(Path(directory)/policy['engine_evidence_files'][signal['selection']['template_id']]),
                    'quote_snapshot_id':quote_id,'reconciliation_max_days':policy['reconciliation_max_days']}
                if policy['execution_window_sessions'] is not None:
                    authority['execution_window']={'session':day,'maximum_sessions':policy['execution_window_sessions']}
                audit=activate(book,store,authority)
                if audit['status']!='ACTIVATED':raise QuantError('SIMULATION_PLAN_BLOCKED','开仓计划检查失败：'+','.join(audit['checks']))
        closing=event['kind']=='OPTION_TRADE' and event['action']=='CLOSE'
        if closing:
            from . import option_exit
            signal,_=by_plan[event['plan_id']]
            body=review(book,event['plan_id'],event['effective_at'])
            contract=next(leg['contract'] for leg in body['selection']['legs'] if leg['contract_version']==event['contract_version'])
            from ..options.contracts import OptionContract
            receipt_hash=option_exit.verify_receipt(native_directory,event,OptionContract.from_dict(contract),signal['monthly_signal_id'])
            proposal=option_exit.cached(book,signal,event)
            clock=(pd.Timestamp(utc(event['effective_at']))-pd.Timedelta(minutes=20)).to_pydatetime()
            marks=current_marks(path,pd.Timestamp(clock).tz_convert('America/New_York').strftime('%Y-%m-%d'))
            if proposal is None:
                quote_id,marks=refresh_reference(book,store,signal,path,account_id,clock)
                proposal=option_exit.freeze(book,store,signal,event,policy,quote_id,clock)
            progress_key,progress=option_exit.check_fill(book,proposal,event,receipt_hash)
        added+=book.import_events(account_id,[event])['added']
        if closing:option_exit.record(book,proposal,event,progress_key,progress,marks)
    return added
