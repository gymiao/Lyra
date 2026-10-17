"""Synthetic option prefix replay; commit only newly observed native facts."""
import json
from pathlib import Path
import sqlite3
from uuid import uuid4
import pandas as pd
from ..common import QuantError,canonical,digest,now_utc,utc,write_json
from ..locks import publication_lock
from ..execution.daily import daily_lock
from ..options.monthly import validate_frozen
from ..options.monthly_replay import monthly_replay
from ..options.ledger import register_contract
from ..portfolio import Ledger
from ..portfolio.report import account_report
from ..strategies.archive import source_fingerprint
from .service import read_workspace


def publish_checkpoint(book,runtime,account_id,run_id,session,*,update_run=True):
    """Recover publication after facts commit without replaying or adding fills."""
    row=book.connection.execute('SELECT details FROM simulation_checkpoints WHERE run_id=? AND session=?',(run_id,session)).fetchone()
    detail=json.loads(row['details'])
    if 'prices' not in detail:
        raise QuantError('INCOMPLETE_CHECKPOINT','期权检查点缺少冻结估值，不能猜测恢复价格')
    with publication_lock(runtime),book.transaction():
        if book.snapshot(account_id,detail['as_of'],detail['prices'])['equity']!=detail['equity']:
            raise QuantError('SIMULATION_CHECKPOINT_CHANGED','已提交检查点权益发生变化，不能覆盖原依据')
        report=account_report(book,account_id,detail['as_of'],detail['prices'],runtime/'reports/account-latest',
            quote_info={'status':'SIMULATED_REFERENCE_PRICES','prices':detail['prices'],'as_of':detail['as_of'],
                        'data_type':'synthetic','reason':'原生前缀执行路径参考中价，不是实际报价'})
        if report['equity']!=detail['equity']:
            raise QuantError('SIMULATION_CHECKPOINT_CHANGED','已提交检查点权益发生变化，不能覆盖原依据')
        detail['report_id']=report['report_id']
        book.connection.execute('UPDATE simulation_checkpoints SET details=? WHERE run_id=? AND session=?',
                                (canonical(detail),run_id,session))
        if update_run:
            book.connection.execute('UPDATE simulation_runs SET status=?,updated_at=?,details=? WHERE run_id=?',
                                    ('COMPLETED' if detail.get('terminal') else 'PAUSED',now_utc(),canonical(detail),run_id))
    return detail


def publish_pending_checkpoints(book,runtime,account_id,run_id):
    """Complete every committed daily report before publishing the final head."""
    rows=book.connection.execute('SELECT session,details FROM simulation_checkpoints WHERE run_id=? ORDER BY session',(run_id,)).fetchall()
    for row in rows:
        if not json.loads(row['details']).get('report_id'):
            publish_checkpoint(book,runtime,account_id,run_id,row['session'],update_run=False)


def settle_checkpoint(book,runtime,account_id,run_id,cutoff,clock):
    """After all positions close, advance only documented cash settlement facts."""
    previous=book.connection.execute('SELECT through_session,details FROM simulation_runs WHERE run_id=?',(run_id,)).fetchone()
    if not previous or not previous['through_session']:
        raise QuantError('CLOSE_CHECKPOINT_REQUIRED','需先完成最后行情日的平仓检查点，不能跳过成交阶段')
    before=json.loads(previous['details'])
    state=book.snapshot(account_id,before['as_of'],before.get('prices',{}))
    if state['positions'] or state['option_positions']:
        raise QuantError('OPEN_POSITIONS_WITHOUT_PRICES','仍有持仓，不能用缺失行情推进结算或虚构平仓')
    facts=book.active_events(account_id,before['as_of'])
    trades=[event for event in facts if event['kind'] in {'BUY','SELL','OPTION_TRADE','OPTION_ASSIGNMENT','OPTION_EXERCISE','OPTION_CASH_SETTLEMENT'}]
    if not trades or any(not event.get('settlement_at') for event in trades):
        raise QuantError('UNKNOWN_SETTLEMENT','缺少已成交事件的明确结算时间')
    end=max(utc(event['settlement_at']) for event in trades)
    if pd.Timestamp(clock).tz_convert('America/New_York').date()!=pd.Timestamp(end).tz_convert('America/New_York').date() or utc(clock)<end:
        raise QuantError('INVALID_SETTLEMENT_DAY','终点须是账本明确的最后结算日，不延长无行情观察区间')
    with publication_lock(runtime),book.transaction():
        state=book.snapshot(account_id,clock,{})
        from ..common import decimal as D
        if state['anomalies'] or state['equity'] is None or D(state['receivables'])!=0 or D(state['payables'])!=0:
            raise QuantError('INCOMPLETE_SETTLEMENT','结算后账户仍有异常或未结清应收应付')
        detail={'as_of':clock,'prices':{},'equity':state['equity'],'added':0,'terminal':True,
                'input_bundle_id':before.get('input_bundle_id'),
                'data_type':'synthetic_prefix_simulation','stage':'CASH_SETTLEMENT',
                'plan_support':'RESEARCH_SCHEDULE_ONLY','previous_session':previous['through_session']}
        book.connection.execute('INSERT INTO simulation_checkpoints VALUES(?,?,?)',(run_id,cutoff,canonical(detail)))
        book.connection.execute('UPDATE simulation_runs SET status=?,through_session=?,updated_at=?,details=? WHERE run_id=?',
                                ('REPORT_PENDING',cutoff,now_utc(),canonical(detail),run_id))
    return publish_checkpoint(book,runtime,account_id,run_id,cutoff)


def run(action,run_id=None,through=None,requested_at=None,*,input_file=None,engine_root=None,dotnet=None,fee_per_contract=None):
    from .worker import SCHEMA
    root,workspace,config,_=read_workspace(Path.cwd());runtime=root/config.runtime_dir
    book=Ledger(runtime/'account.sqlite','demo');source=source_fingerprint();owned=False
    request_time=utc(requested_at or now_utc())
    try:
        if action=='pause':
            if not run_id or len(run_id)!=64 or any(c not in '0123456789abcdef' for c in run_id):
                raise QuantError('RUN_REQUIRED','需要有效run-id')
            row=book.connection.execute('SELECT * FROM simulation_runs WHERE run_id=?',(run_id,)).fetchone()
            if row is None:raise QuantError('UNKNOWN_SIMULATION','不存在期权运行')
            write_json(runtime/'simulation/pauses'/(run_id+'.json'),{'requested_at':request_time.isoformat()})
            if row['status'] not in {'RUNNING','COMPLETED','REPORT_PENDING'}:
                book.connection.execute('UPDATE simulation_runs SET status=?,updated_at=? WHERE run_id=?',('PAUSED',now_utc(),run_id))
            result=dict(book.connection.execute('SELECT * FROM simulation_runs WHERE run_id=?',(run_id,)).fetchone())
            return {**result,'pause_requested':True}
        with daily_lock(runtime/'.simulation.lock'):
            book.connection.executescript(SCHEMA)
            if action=='start':
                if not input_file or not engine_root or not dotnet or fee_per_contract is None:
                    raise QuantError('OPTION_INPUT_REQUIRED','期权启动需明确file、engine-root、dotnet、fee-per-contract')
                request=json.loads(Path(input_file).read_text())
                if set(request)-{'signals','packages','stock_basket','execution_path','final_lifecycle','retain_stock','rolling_end_session','wheel','wheel_end_session','plan_policy','prepare_stock','assignment_scenarios'} or not request.get('execution_path'):
                    raise QuantError('INVALID_OPTION_SIMULATION','期权工作台需要冻结信号及明确合成执行路径')
                if 'assignment_scenarios' in request:
                    scenarios=request['assignment_scenarios']
                    if not isinstance(scenarios,list) or not scenarios or any(not isinstance(s,dict) or set(s)!={'contract_id','session','quantity'} for s in scenarios):
                        raise QuantError('INVALID_ASSIGNMENT_SCENARIO','需完整合成指派场景列表')
                    if 'plan_policy' in request:
                        raise QuantError('UNQUALIFIED_ASSIGNMENT_POLICY','指派故障模型仅研究前缀，不复用普通公共计划资格')
                if request.get('final_lifecycle') not in {None,'natural_expiry','natural_expiry_with_delivery_exit'}:
                    raise QuantError('INVALID_OPTION_SIMULATION','未知末期处置政策')
                if type(request.get('retain_stock',False)) is not bool:
                    raise QuantError('INVALID_ROLLING_POLICY','retain_stock必须为布尔值')
                if request.get('retain_stock'):
                    last_day=max(max(rows) for rows in request['execution_path']['stocks'].values())
                    if request.get('rolling_end_session')!=last_day:
                        raise QuantError('INVALID_ROLLING_POLICY','滚动工作区需冻结与执行路径终点相同的持股截止日')
                elif request.get('rolling_end_session'):
                    raise QuantError('INVALID_ROLLING_POLICY','未启用持续持股，不能指定滚动结束日')
                if type(request.get('wheel',False)) is not bool:raise QuantError('INVALID_WHEEL_PATH','wheel必须为布尔值')
                if request.get('wheel'):
                    if request.get('retain_stock') or request.get('stock_basket') or request.get('wheel_end_session')!=max(max(rows) for rows in request['execution_path']['stocks'].values()):
                        raise QuantError('INVALID_WHEEL_PATH','Wheel需固定恢复终点、单标的且不混用股票篮子/普通滚动')
                elif request.get('wheel_end_session'):raise QuantError('INVALID_WHEEL_PATH','未启用Wheel，不设置Wheel终点')
                if not isinstance(request.get('signals'),list) or not request['signals'] or any(isinstance(s,list) for s in request['signals']):
                    raise QuantError('INVALID_OPTION_SIMULATION','当前前缀工作台接受逐月单标的信号，篮子仍可显式配置')
                for signal in request['signals']:validate_frozen(signal)
                if any(s['selection']['data_type']!='synthetic' for s in request['signals']):raise QuantError('DEMO_ONLY','前缀回放只接受合成信号')
                if 'assignment_scenarios' in request:
                    known={leg['contract']['contract_id'] for signal in request['signals'] for leg in signal['selection']['legs']}
                    seen=set()
                    for scenario in request['assignment_scenarios']:
                        identity=scenario['contract_id'];day=scenario['session'];quantity=scenario['quantity']
                        if (not isinstance(identity,str) or identity not in known or identity in seen
                                or not isinstance(day,str) or not __import__('re').fullmatch(r'\d{4}-\d{2}-\d{2}',day)
                                or type(quantity) is not int or quantity<=0):
                            raise QuantError('INVALID_ASSIGNMENT_SCENARIO','指派故障合约/日期/数量无效或重复')
                        seen.add(identity)
                settings={'request_hash':digest(request),'source_hash':source,'engine_root':str(Path(engine_root).absolute()),
                          'dotnet':str(Path(dotnet).absolute()),'fee_per_contract':float(fee_per_contract)}
                settings.update(run_mode='frozen_replay',input_bundle_id=digest(request))
                calendar_index={'request_hash':settings['request_hash'],'signals':[
                    {k:s[k] for k in ('monthly_signal_id','decision_at','applicable_session','applicable_close','generation_mode')}
                    for s in request['signals']]}
                settings['calendar_index_hash']=digest(calendar_index)
                if settings['fee_per_contract']<0 or not __import__('math').isfinite(settings['fee_per_contract']):raise QuantError('INVALID_FEES','费用须为有限非负值')
                from .portable_tools import fingerprint as tool_fingerprint
                tools=tool_fingerprint(settings['engine_root'],settings['dotnet'])
                settings['tool_identity_hash']=tools['content_hash']
                policy_staging=None
                if 'plan_policy' in request:
                    from .option_policy import freeze_policy
                    policy_staging=runtime/'simulation/options'/('.policy-'+digest(settings))
                    settings['plan_policy_hash']=digest(freeze_policy(request,policy_staging,settings['fee_per_contract']))
                run_id=digest({'workspace':workspace['workspace_id'],'settings':settings})
                if book.connection.execute('SELECT 1 FROM simulation_runs WHERE run_id<>?',(run_id,)).fetchone():
                    raise QuantError('WORKSPACE_RUN_CONFLICT','期权工作区只接受一份冻结运行；修改请求请复制独立实验')
                if book.connection.execute('SELECT 1 FROM simulation_runs WHERE source_hash<>?',(source,)).fetchone():
                    raise QuantError('SIMULATION_SOURCE_CHANGED','旧运行实现已变化，请建立独立工作区')
                directory=runtime/'simulation/options'/run_id;directory.mkdir(parents=True,exist_ok=True)
                if policy_staging:
                    import shutil
                    shutil.copytree(policy_staging,directory,dirs_exist_ok=True)
                    shutil.rmtree(policy_staging)
                write_json(directory/'request.json',request);write_json(directory/'settings.json',settings)
                write_json(directory/'calendar-index.json',calendar_index)
                with publication_lock(runtime),book.transaction():
                    from .source_archive import bind
                    bind(book,runtime,run_id,source)
                    from .portable_tools import bind as bind_tools
                    bind_tools(book,directory,run_id,settings,tools)
                    book.connection.execute('INSERT OR IGNORE INTO simulation_runs VALUES(?,?,?,?,?,?)',(run_id,'CREATED',None,source,now_utc(),'{}'))
            row=book.connection.execute('SELECT * FROM simulation_runs WHERE run_id=?',(run_id,)).fetchone()
            if row is None:raise QuantError('UNKNOWN_SIMULATION','不存在期权运行')
            if row['source_hash']!=source:raise QuantError('SIMULATION_SOURCE_CHANGED','实现已变化，请建立独立新工作区')
            from .source_archive import require
            require(book,runtime,run_id,source)
            directory=runtime/'simulation/options'/run_id
            settings=json.loads((directory/'settings.json').read_text());request=json.loads((directory/'request.json').read_text())
            if (digest(request)!=settings['request_hash'] or settings['source_hash']!=source
                    or digest({'workspace':workspace['workspace_id'],'settings':settings})!=run_id):raise QuantError('SIMULATION_INPUT_CHANGED','冻结输入或实现身份改变')
            policy=None
            if 'plan_policy' in request:
                policy=json.loads((directory/'plan-policy.json').read_text())
                if policy['request_hash']!=digest(request['plan_policy']) or digest(policy)!=settings['plan_policy_hash']:raise QuantError('SIMULATION_INPUT_CHANGED','冻结计划政策改变')
            if action=='pause':book.connection.execute('UPDATE simulation_runs SET status=? WHERE run_id=?',('PAUSED',run_id))
            elif action in {'step','resume'}:
                if not through:raise QuantError('SIMULATION_DAY_REQUIRED','期权推进需明确交易日through')
                cutoff=str(pd.Timestamp(through).date())
                if row['through_session'] and cutoff<row['through_session']:raise QuantError('SIMULATION_TIME_REVERSED','运行只能前进')
                if row['through_session']==cutoff:
                    publish_pending_checkpoints(book,runtime,workspace['account_id'],run_id)
                    detail=publish_checkpoint(book,runtime,workspace['account_id'],run_id,cutoff)
                    return {**dict(row),'status':'COMPLETED' if detail.get('terminal') else 'PAUSED','details':detail,'events':book.sequence(workspace['account_id']),'repeated':True}
                if row['status']=='REPORT_PENDING' and row['through_session']:
                    publish_pending_checkpoints(book,runtime,workspace['account_id'],run_id)
                    publish_checkpoint(book,runtime,workspace['account_id'],run_id,row['through_session'])
                from .portable_tools import archived as archived_tools,resolve as resolve_tools
                _,tool_manifest=archived_tools(book,directory,run_id)
                if tool_manifest['content_hash']!=settings.get('tool_identity_hash'):
                    raise QuantError('CORRUPT_SIMULATION_TOOLS','原始运行设置与外部工具清单不一致')
                tool_paths=resolve_tools(book,directory,run_id,engine_root=engine_root,dotnet=dotnet)
                from ..data.calendar import Calendar
                calendar=Calendar.market(str(min(min(rows) for rows in request['execution_path']['stocks'].values())),cutoff)
                if pd.Timestamp(cutoff) not in calendar.sessions:raise QuantError('INVALID_SIMULATION_DAY','终点不是市场交易日')
                clock=(calendar.close(cutoff)+pd.Timedelta(minutes=config.publication_delay_minutes)).isoformat()
                if request.get('final_lifecycle') or request.get('wheel'):
                    clock=(pd.Timestamp(cutoff)+pd.Timedelta(days=1)).tz_localize('America/New_York').tz_convert('UTC').isoformat()
                last_market_day=max(max(rows) for rows in request['execution_path']['stocks'].values())
                if cutoff>last_market_day:
                    if row['through_session']!=last_market_day:
                        raise QuantError('CLOSE_CHECKPOINT_REQUIRED','先推进到执行路径最后行情日，再处理结算')
                    settlement_clock=(calendar.close(cutoff)+pd.Timedelta(minutes=config.publication_delay_minutes)).isoformat()
                    detail=settle_checkpoint(book,runtime,workspace['account_id'],run_id,cutoff,settlement_clock)
                    return {'run_id':run_id,'status':'COMPLETED','through_session':cutoff,'details':detail,'events':book.sequence(workspace['account_id'])}
                indices=[i for i,s in enumerate(request['signals']) if utc(s['decision_at'])<=utc(clock)]
                if not indices:raise QuantError('WAITING_FOR_SIGNAL','该时点尚无冻结月度信号')
                signals=[request['signals'][i] for i in indices]
                if signals[0]['applicable_session']>cutoff:raise QuantError('WAITING_FOR_EXECUTION','尚未到达首个适用成交日')
                current=book.snapshot(workspace['account_id'],clock)
                if current['anomalies']:
                    raise QuantError('UNRESOLVED_ACCOUNT_FACTS','账户有未解决凭据/单位异常：'+'；'.join(current['anomalies']))
                opening_id='workspace:'+workspace['workspace_id']+':opening'
                if any(event['event_id']!=opening_id and event['source']!='synthetic_monthly_lean'
                       for event in book.active_events(workspace['account_id'],clock)):
                    raise QuantError('SIMULATION_EXTERNAL_FACTS','账本有额外资金/费用/单位事实，保留原事实并暂停旧机械路径；请建立符合新事实的独立实验')
                book.connection.execute('UPDATE simulation_runs SET status=?,updated_at=? WHERE run_id=?',('RUNNING',now_utc(),run_id))
                owned=True
                contracts={leg['contract']['contract_id'] for s in signals for leg in s['selection']['legs']}
                path=request['execution_path']
                clipped={**path,'stocks':{s:{d:p for d,p in rows.items() if d<=cutoff} for s,rows in path['stocks'].items()},
                         'options':{s:{d:p for d,p in rows.items() if d<=cutoff} for s,rows in path['options'].items() if s in contracts}}
                packages=[request['packages'][i] for i in indices] if request.get('packages') is not None else None
                lifecycle=request.get('final_lifecycle') if indices[-1]==len(request['signals'])-1 else None
                attempt=directory/('prefix-'+cutoff+'-'+uuid4().hex[:8])
                from .task_progress import phase
                phase('ENGINE_EXECUTION')
                proof=monthly_replay(tool_paths['engine_root'],tool_paths['dotnet'],attempt,signals,initial_cash=float(workspace['initial_cash']),
                    fee_per_contract=settings['fee_per_contract'],stock_commission_bps=config.commission_bps,
                    packages=packages,stock_basket=request.get('stock_basket'),execution_path=clipped,through=cutoff,final_lifecycle=lifecycle,
                    retain_stock=request.get('retain_stock',False),rolling_end_session=request.get('rolling_end_session'),
                    wheel=request.get('wheel',False),wheel_end_session=request.get('wheel_end_session'),prepare_stock=request.get('prepare_stock',False),
                    assignment_scenarios=[s for s in request.get('assignment_scenarios',[]) if s['contract_id'] in contracts and s['session']<=cutoff] or None)
                pause=runtime/'simulation/pauses'/(run_id+'.json')
                if pause.exists() and utc(json.loads(pause.read_text())['requested_at'])>request_time:
                    book.connection.execute('UPDATE simulation_runs SET status=?,updated_at=? WHERE run_id=?',('PAUSED',now_utc(),run_id))
                    result=dict(book.connection.execute('SELECT * FROM simulation_runs WHERE run_id=?',(run_id,)).fetchone())
                    return {**result,'details':json.loads(result['details']),'events':book.sequence(workspace['account_id']),'pause_requested':True}
                engine=sqlite3.connect((attempt/'bridge.sqlite').as_uri()+'?mode=ro',uri=True)
                try:
                    terms=[json.loads(r[0]) for r in engine.execute('SELECT payload FROM option_contracts')]
                    rows=[json.loads(r[0]) for r in engine.execute('SELECT payload FROM events ORDER BY seq') if json.loads(r[0])['event_id']!='capital']
                finally:engine.close()
                # Prefix comparison protects already recorded fills from rerun drift.
                existing=book.connection.execute("SELECT event_id,payload FROM events WHERE account_id=? AND json_extract(payload,'$.source')='synthetic_monthly_lean' ORDER BY seq",(workspace['account_id'],)).fetchall()
                desired=[]
                for event in rows:
                    event={**event,'account_id':workspace['account_id']}
                    desired.append(event)
                if policy:
                    from .option_policy import bind_events
                    desired=bind_events(desired,proof['cycles'],signals,packages or [1]*len(signals),workspace['account_id'],policy,run_id=run_id)
                if len(existing)>len(desired) or any(json.loads(old['payload'])!=new for old,new in zip(existing,desired)):
                    raise QuantError('SIMULATION_PREFIX_CHANGED','成熟引擎输出改变已记账前缀，保留原事实并暂停')
                marks={symbol:values[cutoff] for symbol,values in clipped['stocks'].items()}
                for identity,values in clipped['options'].items():
                    if cutoff in values:marks[identity]=str((__import__('decimal').Decimal(values[cutoff]['bid'])+__import__('decimal').Decimal(values[cutoff]['ask']))/2)
                # Match the declared valuation cutoff, including actual native
                # expiry facts at next local midnight. Never redate those facts.
                if lifecycle or request.get('wheel'):clock=proof['ledger_bridge']['as_of']
                with publication_lock(runtime),book.transaction():
                    for term in terms:register_contract(book,term)
                    submitted=[{k:v for k,v in event.items() if k!='contract'} for event in desired]
                    if policy:
                        from .option_policy import import_planned_events
                        added=import_planned_events(book,directory,workspace['account_id'],submitted,signals,
                            packages or [1]*len(signals),clipped,policy,config=config,run_id=run_id,cycles=proof['cycles'],native_directory=attempt)
                    else:added=book.import_events(workspace['account_id'],submitted)['added']
                    snapshot=book.snapshot(workspace['account_id'],clock,marks)
                    if snapshot['equity'] is None or snapshot['anomalies']:raise QuantError('SIMULATION_ACCOUNT_MISMATCH','账户估值/覆盖或资金异常')
                    from ..common import decimal as D
                    if abs(D(snapshot['equity'])-D(proof['ledger_bridge']['equity']))>D('.01'):
                        raise QuantError('SIMULATION_ACCOUNT_MISMATCH','工作区实际资金/持仓与原生前缀不同，不能继续机械模拟')
                    detail={'equity':snapshot['equity'],'native_proof':str(attempt.relative_to(runtime)),'added':added,'as_of':clock,'prices':marks,
                            'input_bundle_id':settings['input_bundle_id'],
                            'data_type':'synthetic_prefix_simulation','plan_support':'OPENING_PLANS_LINKED_EXIT_FACTS' if policy else 'RESEARCH_SCHEDULE_ONLY',
                            'valuation_cutoff':'next_local_midnight' if request.get('final_lifecycle') or request.get('wheel') else 'session_close_with_publication_delay',
                            'final_lifecycle':lifecycle,'lifecycle_receipts':proof.get('lifecycle_receipts',[])}
                    detail['retain_stock']=request.get('retain_stock',False)
                    detail['rolling_end_session']=request.get('rolling_end_session')
                    detail['wheel']=request.get('wheel',False)
                    detail['wheel_end_session']=request.get('wheel_end_session')
                    detail['terminal']=(cutoff==last_market_day and not snapshot['positions'] and not snapshot['option_positions']
                                        and D(snapshot['receivables'])==0 and D(snapshot['payables'])==0)
                    daily=pd.read_csv(attempt/'daily-equity.csv')
                    for _,point in daily.iterrows():
                        day=str(point['date'])
                        if day==cutoff or book.connection.execute('SELECT 1 FROM simulation_checkpoints WHERE run_id=? AND session=?',(run_id,day)).fetchone():continue
                        day_clock=((pd.Timestamp(day)+pd.Timedelta(days=1)).tz_localize('America/New_York').tz_convert('UTC')
                                   if request.get('final_lifecycle') or request.get('wheel') else calendar.close(day)+pd.Timedelta(minutes=config.publication_delay_minutes))
                        day_marks={s:values[day] for s,values in clipped['stocks'].items()}
                        for identity,values in clipped['options'].items():
                            if day in values:day_marks[identity]=str((D(values[day]['bid'])+D(values[day]['ask']))/2)
                        state=book.snapshot(workspace['account_id'],day_clock.isoformat(),day_marks)
                        if state['equity'] is None or state['anomalies'] or abs(D(state['equity'])-D(point['equity']))>D('.01'):
                            raise QuantError('SIMULATION_DAILY_MISMATCH','逐日账户与原生净值不同，整批事实/检查点回滚')
                        day_detail={**detail,'as_of':day_clock.isoformat(),'prices':day_marks,'equity':state['equity'],
                                    'terminal':False,'added':0,'stage':'DAILY_OBSERVATION'}
                        book.connection.execute('INSERT INTO simulation_checkpoints VALUES(?,?,?)',(run_id,day,canonical(day_detail)))
                    book.connection.execute('INSERT INTO simulation_checkpoints VALUES(?,?,?)',(run_id,cutoff,canonical(detail)))
                    book.connection.execute('UPDATE simulation_runs SET status=?,through_session=?,updated_at=?,details=? WHERE run_id=?',
                        ('REPORT_PENDING',cutoff,now_utc(),canonical(detail),run_id))
                owned=False # Persisted facts retain REPORT_PENDING on publication failure.
                publish_pending_checkpoints(book,runtime,workspace['account_id'],run_id)
                publish_checkpoint(book,runtime,workspace['account_id'],run_id,cutoff)
            result=dict(book.connection.execute('SELECT * FROM simulation_runs WHERE run_id=?',(run_id,)).fetchone())
            result['details']=json.loads(result['details']);result['events']=book.sequence(workspace['account_id'])
            return result
    except BaseException as exc:
        if owned:
            try:book.connection.execute('UPDATE simulation_runs SET status=?,updated_at=? WHERE run_id=?',('FAILED',now_utc(),run_id))
            except Exception as logging_error:exc.add_note('失败状态未能写入，恢复前需核实任务和账本：'+str(logging_error))
            try:write_json(runtime/'simulation/options'/run_id/'last-failure.json',
                {'code':getattr(exc,'code','INTERRUPTED'),'reason':str(exc),'at':now_utc()})
            except Exception as logging_error:exc.add_note('失败诊断未能落盘：'+str(logging_error))
        raise
    finally:book.close()
