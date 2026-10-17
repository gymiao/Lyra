"""Multiple frozen monthly decisions in one mature-engine portfolio, synthetic evidence only."""
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import zipfile
import pandas as pd
from ..common import QuantError,decimal as D,digest,write_json
from ..data.calendar import Calendar
from .contracts import OptionContract
from .monthly import validate_frozen
from .replay import upstream_config
from .engine import LEAN_COMMIT
from .catalog import A8


def write_zip_member(stream,name,content):
    # Storage timestamps must not change the identity of identical execution data.
    info=zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0))
    stream.writestr(info,content,compress_type=zipfile.ZIP_DEFLATED)


def monthly_replay(engine_root,dotnet,destination,signals,*,initial_cash,fee_per_contract,control=None,stock_commission_bps=0,packages=None,stock_basket=None,execution_path=None,final_lifecycle=None,through=None,retain_stock=False,rolling_end_session=None,wheel=False,wheel_end_session=None,prepare_stock=False,assignment_scenarios=None):
    if type(prepare_stock) is not bool or (prepare_stock and (not retain_stock or wheel or execution_path is None)):
        raise QuantError('INVALID_STOCK_PREPARATION','股票准备需持续持股及明确执行路径，不混用Wheel')
    if type(wheel) is not bool or (wheel and (execution_path is None or retain_stock or stock_basket or control)):
        raise QuantError('INVALID_WHEEL_PATH','Wheel需单标的明确执行路径，不混用股票篮子/研究控制或普通滚动')
    if wheel:final_lifecycle='natural_expiry'
    if (wheel and through and not wheel_end_session) or (wheel_end_session and not wheel):
        raise QuantError('WHEEL_HORIZON_REQUIRED','Wheel前缀需冻结终点，不从当前已知信号虚构清股')
    if type(retain_stock) is not bool or (retain_stock and execution_path is None):
        raise QuantError('INVALID_ROLLING_POLICY','持续持股滚动需明确执行路径')
    if (through and retain_stock and not rolling_end_session) or (rolling_end_session and not retain_stock):
        raise QuantError('ROLLING_HORIZON_REQUIRED','滚动前缀需显式冻结最终持股截止日，不依据当前已知信号提前卖股')
    if final_lifecycle not in {None,'natural_expiry','natural_expiry_with_delivery_exit'} or (final_lifecycle and execution_path is None):
        raise QuantError('INVALID_MONTHLY_REPLAY','自然末期需显式合成路径')
    if control not in {None,'stock','cash'}:raise QuantError('INVALID_MONTHLY_REPLAY','未知月度控制组')
    from ..workspace.task_progress import phase
    phase('ENGINE_PRECHECK')
    from .monthly_portfolio import normalize,flat,signal_id,event_contract
    batches,counts,multi=normalize(signals,packages,minimum_batches=1 if through else 2,wheel=wheel)
    signals=flat(batches)
    stock_basket={} if stock_basket is None else stock_basket
    if not isinstance(stock_basket,dict) or any(not re.fullmatch(r'[A-Z][A-Z0-9.-]{0,15}',k) or D(v)<=0 or D(v)!=D(v).to_integral_value() for k,v in stock_basket.items()):
        raise QuantError('INVALID_MONTHLY_REPLAY','篮子需明确正整数股票数量')
    if (multi or stock_basket or any(n!=[1] for n in counts)) and execution_path is None:
        raise QuantError('EXECUTION_PATH_REQUIRED','多标的/新数量/篮子需显式执行路径，不继承固定演示价')
    if D(initial_cash)<=0 or D(fee_per_contract)<0 or D(stock_commission_bps)<0:raise QuantError('INVALID_MONTHLY_REPLAY','资本/费用无效')
    destination=Path(destination).absolute();root=Path(engine_root).absolute();dotnet=Path(dotnet).absolute()
    if destination.exists():raise QuantError('NONEMPTY_DESTINATION','月度回放必须使用新目录')
    if subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()!=LEAN_COMMIT or subprocess.check_output([str(dotnet),'--version'],text=True).strip()!='10.0.100':
        raise QuantError('LEAN_VERSION_MISMATCH','需已验证LEAN/SDK版本')
    if subprocess.check_output(['git','-C',str(root),'status','--porcelain'],text=True).strip():raise QuantError('LEAN_SOURCE_CHANGED','第三方引擎有修改')
    destination.mkdir(parents=True)
    from .adapter_resources import build as build_adapter
    sources=build_adapter(root,dotnet,destination,source_directory='source',binary_directory='bin',object_directory='obj',log_name='build.log')
    env=dict(os.environ,DOTNET_CLI_HOME='/tmp/lyrax-dotnet-home')
    first=batches[0][0]['applicable_session'];last=batches[-1][0]['selection']
    last_exit=pd.Timestamp(last['expiry']) if final_lifecycle else pd.Timestamp(last['expiry'])-pd.Timedelta(days=last['exit_days_before_expiry'])
    calendar_end=last_exit+pd.Timedelta(days=10)
    if rolling_end_session:calendar_end=max(calendar_end,pd.Timestamp(rolling_end_session)+pd.Timedelta(days=10))
    if wheel_end_session:calendar_end=max(calendar_end,pd.Timestamp(wheel_end_session)+pd.Timedelta(days=10))
    if through and execution_path is not None:calendar_end=max(calendar_end,pd.Timestamp(through)+pd.Timedelta(days=10))
    calendar=Calendar.market(first,str(calendar_end.date()))
    if final_lifecycle:last_exit=calendar.next(last_exit)
    if prepare_stock:last_exit=calendar.next(max(day for day in calendar.sessions if day<=last_exit))
    if wheel:
        wheel_horizon=pd.Timestamp(wheel_end_session or last_exit)
        if wheel_horizon not in calendar.sessions or (not through and wheel_horizon!=last_exit):
            raise QuantError('INVALID_WHEEL_HORIZON','Wheel终点须为最后恢复交易日，前缀不补未来价格')
        if through:last_exit=wheel_horizon
    planned_limit=max(last_exit,pd.Timestamp(rolling_end_session)) if rolling_end_session else last_exit
    planned_end=calendar.sessions[calendar.sessions<=planned_limit][-1]
    # Cash observation may extend beyond the last option exit. Keep planned
    # exits independent of a prefix cutoff so no early liquidation is invented.
    observation_end=max(planned_limit,pd.Timestamp(through)) if through else planned_limit
    sessions=calendar.sessions[calendar.sessions<=observation_end]
    if through:
        cutoff=pd.Timestamp(through)
        if cutoff not in sessions:raise QuantError('INVALID_SIMULATION_DAY','原生前缀终点须为已知交易日')
        sessions=sessions[sessions<=cutoff]
    cycles=[];contracts={};quotes={};native_ids={};underlying=batches[0][0]['selection']['underlying']
    underlyings={s['selection']['underlying'] for s in signals}
    if underlyings&set(stock_basket):raise QuantError('INVALID_MONTHLY_REPLAY','篮子不重复覆盖期权主标的，由逐项包数明确股份')
    for index,batch in enumerate(batches):
        selected=batch[0]['selection'];entry=pd.Timestamp(batch[0]['applicable_session'])
        # One shared cash ledger: previous cycle closes before T+1 funded entry.
        if index and not wheel:entry=calendar.next(entry)
        preparation=entry if prepare_stock and index==0 else None
        if preparation is not None:entry=calendar.next(entry)
        exit=pd.Timestamp(batches[index+1][0]['applicable_session']) if index+1<len(batches) else planned_end
        if prepare_stock and final_lifecycle and index==len(batches)-1:
            exit=max(day for day in calendar.sessions if day<planned_end)
        expiry_exit=pd.Timestamp(selected['expiry'])-pd.Timedelta(days=selected['exit_days_before_expiry'])
        if wheel:exit=calendar.next(pd.Timestamp(selected['expiry']))
        elif not (final_lifecycle and index==len(batches)-1):exit=min(exit,max(day for day in calendar.sessions if day<=expiry_exit))
        legs=[];positions=dict(stock_basket);control_positions=dict(stock_basket);shares=0
        for signal,n in zip(batch,counts[index]):
            selected=signal['selection'];symbol=selected['underlying']
            q=100*n if selected['template_id'] in {'protective_put','covered_call','collar'} else 0
            if q:positions[symbol]=q;shares+=q
            reference=q or (0 if stock_basket else 100*n)
            if reference:control_positions[symbol]=reference
            for leg in selected['legs']:
                c=OptionContract.from_dict(leg['contract']);c.require_standard_vanilla()
                if c.underlying!=symbol or c.quote_multiplier!=100 or c.style!='AMERICAN' or c.settlement!='PHYSICAL':
                    raise QuantError('UNSUPPORTED_LEAN_FIXTURE','仅同标的标准100股美式实物合约')
                if abs(D(leg['quantity_per_package']))!=1 or (execution_path is None and D(leg['reference_quote']['underlying_price'])!=100):
                    raise QuantError('UNSUPPORTED_LEAN_FIXTURE','每腿1张/包；变价必须明确路径')
                native=(c.underlying,c.expiry,c.right,c.strike)
                if native in native_ids and native_ids[native]!=c.contract_id:raise QuantError('LEAN_UNIT_MAPPING_FAILED','同一原生证券不能登记两个合约ID')
                native_ids[native]=c.contract_id
                if c.contract_id in contracts:
                    if contracts[c.contract_id].version_hash!=c.version_hash or (execution_path is None and any(D(quotes[c.contract_id][side])!=D(leg['reference_quote'][side]) for side in ['bid','ask'])):
                        raise QuantError('UNSUPPORTED_LEAN_FIXTURE','同一合约跨月变化需独立执行行情，不覆盖原报价')
                else:contracts[c.contract_id]=c;quotes[c.contract_id]=leg['reference_quote']
                legs.append(dict(contract_id=c.contract_id,underlying=c.underlying,right=c.right,strike=float(c.strike),expiry=c.expiry,quantity=leg['quantity_per_package']*n))
        submit=lambda day:(calendar.close(day).tz_convert('America/New_York')-pd.Timedelta(minutes=20)).strftime('%Y-%m-%dT%H:%M:%S')
        cycles.append(dict(signal_id=signal_id(batch),signal_ids=[s['monthly_signal_id'] for s in batch],
            entry_submit_at=submit(entry),exit_submit_at=submit(exit),underlying_shares=shares,legs=legs,
            stock_positions=positions,stock_comparator=control_positions))
        if preparation is not None:cycles[-1]['stock_entry_submit_at']=submit(preparation)
        if final_lifecycle and index==len(batches)-1:cycles[-1]['natural_expiry']=True
        if wheel:
            cycles[-1].update(natural_expiry=True,wheel=True,retain_stock_after_exit=exit<wheel_horizon)
        if final_lifecycle=='natural_expiry_with_delivery_exit' and index==len(batches)-1:
            cycles[-1]['delivery_exit_submit_at']=submit(pd.Timestamp(selected['expiry']))
    if control:
        for cycle in cycles:cycle.update(legs=[],underlying_shares=0,stock_positions=cycle['stock_comparator'] if control=='stock' else {})
    if prepare_stock and not control and not cycles[0]['stock_positions']:
        raise QuantError('INVALID_STOCK_PREPARATION','股票准备必须有明确的正股票目标')
    if retain_stock:
        horizon=pd.Timestamp(rolling_end_session or planned_end)
        if (horizon not in calendar.sessions or (through and horizon<pd.Timestamp(through))
                or (not through and horizon!=planned_end)):
            raise QuantError('INVALID_ROLLING_HORIZON','持股截止须为有效交易日，完整回放需与最后退出日一致')
        if any(c['stock_positions']!=cycles[0]['stock_positions'] for c in cycles):
            raise QuantError('ROLLING_STOCK_CHANGED','持续持股数量须固定；数量变化需独立计划/资金验证')
        for index,cycle in enumerate(cycles):
            cycle['retain_stock_after_exit']=pd.Timestamp(cycle['exit_submit_at'][:10])<horizon
            cycle['stock_entry']=cycle['stock_positions'] if index==0 else {}
            cycle['stock_exit']=cycle['stock_positions'] if not cycle['retain_stock_after_exit'] else {}
        if pd.Timestamp(cycles[-1]['exit_submit_at'][:10])<horizon:
            cycles[-1]['stock_exit_submit_at']=submit(horizon)
            cycles[-1]['stock_exit']=cycles[-1]['stock_positions']
    from .assignment_scenarios import validate as validate_assignments
    assignments=validate_assignments(assignment_scenarios,cycles,calendar,through=through,synthetic=execution_path is not None)
    stock_symbols=sorted(set(stock_basket)|underlyings)
    from .monthly_path import validate_path,expected_equity
    if execution_path is not None:validate_path(execution_path,sessions,stock_symbols,contracts,quotes)
    stock_price=lambda symbol,day:D(execution_path['stocks'][symbol][str(day)]) if execution_path is not None else D(100)
    option_price=lambda identity,day,side:D(execution_path['options'][identity][str(day)][side]) if execution_path is not None else D(quotes[identity][side])
    for cycle,batch in zip(cycles,batches):
        if control or not batch[0]['selection']['template_id'].endswith('credit_spread'):continue
        day=cycle['entry_submit_at'][:10]
        if through and pd.Timestamp(day)>sessions[-1]:continue
        for signal in batch:
            legs=signal['selection']['legs']
            credit=-sum(D(leg['quantity_per_package'])*option_price(leg['contract']['contract_id'],day,'ask' if leg['quantity_per_package']>0 else 'bid') for leg in legs)
            width=abs(D(legs[0]['contract']['strike'])-D(legs[1]['contract']['strike']))
            if not 0<credit<width:raise QuantError('INVALID_EXECUTION_CREDIT','成交路径必须产生合法净信用，不以事前选约报价替代实际成交条件')
    data=destination/'data'
    for folder in ['market-hours','symbol-properties']:shutil.copytree(root/'Data'/folder,data/folder)
    for folder in ['map_files','factor_files']:(data/'equity/usa'/folder).mkdir(parents=True)
    for symbol in stock_symbols:
        code=symbol.lower()
        (data/'equity/usa/map_files'/f'{code}.csv').write_text(f'20000101,{code},P\n20501231,{code},P\n')
        (data/'equity/usa/factor_files'/f'{code}.csv').write_text('20000101,1,1,1\n20501231,1,1,1\n')
    for day in sessions:
        date=day.strftime('%Y%m%d');close=calendar.close(day).tz_convert('America/New_York');minute=close.hour*60+close.minute
        times=[(minute-21)*60000,(minute-1)*60000]
        for symbol in stock_symbols:
            code=symbol.lower();amount=int(stock_price(symbol,str(day.date()))*10000)
            path=data/'equity/usa/minute'/code/(date+'_trade.zip');path.parent.mkdir(parents=True,exist_ok=True)
            with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
                write_zip_member(z,f'{date}_{code}_minute_trade.csv','\n'.join(','.join(map(str,[time,amount,amount,amount,amount,1000000])) for time in times)+'\n')
        for option_underlying in sorted(underlyings):
            ticker=option_underlying.lower()
            path=data/'option/usa/minute'/ticker/(date+'_quote_american.zip');path.parent.mkdir(parents=True,exist_ok=True)
            with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
                for identity,c in contracts.items():
                    if c.underlying!=option_underlying or day.date()>pd.Timestamp(c.expiry).date() or day.date()<pd.Timestamp(c.listed_at).date():continue
                    if day.date()<pd.Timestamp(quotes[identity]['received_at']).date():continue
                    bid,ask=[int(option_price(identity,str(day.date()),side)*10000) for side in ['bid','ask']]
                    name=f'{date}_{ticker}_minute_quote_american_{c.right.lower()}_{int(c.strike*10000)}_{c.expiry.replace("-","")}.csv'
                    write_zip_member(z,name,'\n'.join(','.join(map(str,[time,*([bid]*4),100,*([ask]*4),100])) for time in times)+'\n')
    body={'initial_cash':float(D(initial_cash)),'fee_per_contract':float(D(fee_per_contract)),'stock_commission_bps':float(D(stock_commission_bps)),'underlying':underlying,'stocks':stock_symbols,'cycles':cycles,'execution_path':execution_path}
    if assignments:body['assignment_scenarios']=assignments
    if through:body['stop_at']=str(sessions[-1].date())
    if through and final_lifecycle:
        # LEAN emits backdated delisting at the next tradable-date boundary.
        # Supply no later quotes and forbid submissions after the frozen cutoff.
        body['valuation_until']=str(calendar.next(sessions[-1]).date())
        body['prefix_as_of']=(sessions[-1]+pd.Timedelta(days=1)).tz_localize('America/New_York').tz_convert('UTC').isoformat()
    write_json(destination/'input.json',body);write_json(destination/'signals.json',signals)
    manifest={str(p.relative_to(data)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(data.rglob('*')) if p.is_file()};write_json(destination/'data-files.json',manifest)
    dll=destination/'bin/LyraX.Options.dll';config=upstream_config(root/'Launcher/config.json')
    config.update({'algorithm-type-name':'LyraX.LyraXMonthly','algorithm-location':str(dll),'data-folder':str(data),
        'results-destination-folder':str(destination),'parameters':{'lyrax-input':str(destination/'input.json')},'close-automatically':True})
    write_json(destination/'config.json',config);launcher=root/'Launcher/bin/Release/QuantConnect.Lean.Launcher.dll'
    phase('ENGINE_EXECUTION')
    with (destination/'launcher.log').open('w') as log:
        run=subprocess.run([str(dotnet),str(launcher),'--config',str(destination/'config.json')],cwd=launcher.parent,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=180)
    paths=list(destination.glob('*-summary.json'))
    if run.returncode or len(paths)!=1:raise QuantError('LEAN_REPLAY_FAILED','查看月度launcher.log')
    summary=json.loads(paths[0].read_text())
    if summary['state']['Status']!='Completed' or summary['state'].get('RuntimeError'):raise QuantError('LEAN_REPLAY_FAILED','月度引擎未完成')
    events=json.loads((destination/'engine-events.json').read_text())
    if assignments:
        from .assignment_scenarios import validate_native
        validate_native(assignments,events,contracts)
    if through:
        cutoff_clock=((sessions[-1]+pd.Timedelta(days=1)).tz_localize('America/New_York').tz_convert('UTC')
                      if final_lifecycle else calendar.close(sessions[-1]))
        if any(pd.Timestamp(e['utc_time'])>cutoff_clock for e in events):
            raise QuantError('LEAN_PREFIX_FUTURE_FACT','原生前缀含估值截止之后的事件，不能提前记账')
    expected_count=sum(int(pd.Timestamp(c['entry_submit_at']).date()<=sessions[-1].date())*len(c['legs'])+
                       int(pd.Timestamp(c.get('stock_entry_submit_at',c['entry_submit_at'])).date()<=sessions[-1].date())*len(c.get('stock_entry',c['stock_positions']))+
                       int(pd.Timestamp(c['exit_submit_at']).date()<=sessions[-1].date())*len(c['legs'])+
                       int(pd.Timestamp(c.get('stock_exit_submit_at',c['exit_submit_at'])).date()<=sessions[-1].date())*len(c.get('stock_exit',c['stock_positions'])) for c in cycles)
    if not final_lifecycle and not assignments and len(events)!=expected_count:raise QuantError('LEAN_MONTHLY_EVENTS','开平仓事件不完整')
    for e in events:
        clock=pd.Timestamp(e['utc_time'])
        if (final_lifecycle or assignments) and e['order_type']=='OptionExercise':continue
        if e['order_type']!='MarketOnClose' or clock!=calendar.close(clock.tz_convert('America/New_York').date()):raise QuantError('LEAN_EXECUTION_TIME_FAILED','月度成交时点错误')
    if through:
        expected=None # No future exit prices enter a prefix simulation.
    elif wheel:
        from .wheel_path import expected_wheel,validate_wheel_events
        validate_wheel_events(events,cycles,contracts)
        expected=expected_wheel(initial_cash,cycles,stock_price,option_price,fee_per_contract,stock_commission_bps,underlying)
    elif final_lifecycle:
        from .monthly_natural import expected_natural,expected_retained_natural,validate_events
        validate_events(events,cycles,contracts)
        calculator=expected_retained_natural if retain_stock else expected_natural
        expected=calculator(initial_cash,cycles,stock_price,option_price,fee_per_contract,stock_commission_bps,underlying)
    else:expected=expected_equity(initial_cash,cycles,stock_price,option_price,fee_per_contract,stock_commission_bps)
    actual=D(summary['statistics']['End Equity'].replace(',','').replace('$',''))
    if not through and abs(actual-expected)>D('.01'):raise QuantError('LEAN_CASH_BRIDGE_FAILED','跨月独立资金预期不一致')
    phase('ACCOUNT_VALIDATION')
    from ..portfolio.ledger import Ledger
    from ..portfolio.schema import apply_workbench_schema,apply_v18_schema,apply_v19_schema
    from .ledger import register_contract
    book=Ledger(destination/'bridge.sqlite','demo');book.account('monthly-bridge')
    try:
        with book.transaction():apply_workbench_schema(book.connection);apply_v18_schema(book.connection);apply_v19_schema(book.connection)
        for c in contracts.values():register_contract(book,c.content())
        rows=[{'event_id':'capital','kind':'DEPOSIT','amount':str(initial_cash),'effective_at':calendar.close(first).isoformat(),
               'source':'synthetic_monthly_lean','evidence_type':'test'}]
        for e in events:
            day=pd.Timestamp(e['utc_time']).tz_convert('America/New_York').date()
            if e['order_type']=='OptionExercise' and e['symbol']!=e['order_symbol']:continue
            base={'event_id':str(e['order_id'])+':'+str(e['event_id']),'effective_at':e['utc_time'],
                'settlement_at':calendar.close(next(d for d in calendar.sessions if d.date()>day)).isoformat(),'quantity':abs(e['quantity']),
                'price':e['price'],'fee':e['fee'],'source':'synthetic_monthly_lean','evidence_type':'test'}
            if e['order_type']=='OptionExercise':
                from .monthly_natural import lifecycle_fact
                base.update(lifecycle_fact(e,contracts,cycles))
            elif e['right'] is None:base.update(kind='BUY' if e['quantity']>0 else 'SELL',symbol=e['symbol'])
            else:
                matched=event_contract(e,contracts)
                action=e['tag'].split('|')[-1]
                base.update(kind='OPTION_TRADE',contract_version=matched.version_hash,
                    action='CLOSE' if action=='CLOSE_DELIVERY_RISK' else action,trade_side='BUY' if e['quantity']>0 else 'SELL')
            rows.append(base)
        book.import_events('monthly-bridge',rows)
        duplicate=book.import_events('monthly-bridge',rows)
        if duplicate['added']!=0:raise QuantError('LEAN_LEDGER_BRIDGE_FAILED','引擎事件重复导入改变账本')
        path=[];lifecycle_receipts=[]
        for sequence,row in enumerate(rows,1):
            clock=pd.Timestamp(row['effective_at']);valuation_day=clock.tz_convert('America/New_York').date();
            day=str(max(d.date() for d in sessions if d.date()<=valuation_day));marks={s:stock_price(s,day) for s in stock_symbols}
            for identity,quote in quotes.items():
                if pd.Timestamp(quote['available_at'])<=clock and day<=contracts[identity].expiry:marks[identity]=(option_price(identity,day,'bid')+option_price(identity,day,'ask'))/2
            point=book.snapshot('monthly-bridge',row['effective_at'],marks,ledger_seq=sequence)
            if row['kind'] in {'OPTION_EXPIRY','OPTION_EXERCISE','OPTION_ASSIGNMENT'}:
                from .monthly_natural import receipt_view
                lifecycle_receipts.append(receipt_view(row,point,sequence))
            if sequence<len(rows) and pd.Timestamp(rows[sequence]['effective_at'])==pd.Timestamp(row['effective_at']):continue
            if point['anomalies'] or point['equity'] is None:raise QuantError('LEAN_LEDGER_BRIDGE_FAILED','月度统一账本资源或估值异常')
            path.append(point)
        final_marks={s:stock_price(s,str(sessions[-1].date())) for s in stock_symbols}
        for identity,c in contracts.items():
            day=str(sessions[-1].date())
            if day in (execution_path or {}).get('options',{}).get(identity,{}) or execution_path is None:
                final_marks[identity]=(option_price(identity,day,'bid')+option_price(identity,day,'ask'))/2
        prefix_clock=((sessions[-1]+pd.Timedelta(days=1)).tz_localize('America/New_York').tz_convert('UTC')
                      if through and final_lifecycle else calendar.close(sessions[-1]))
        final=book.snapshot('monthly-bridge',prefix_clock.isoformat() if through else calendar.close(calendar.next(sessions[-1])).isoformat(),final_marks if through else {})
        if through:
            expected=D(final['equity']) if final['equity'] is not None else D('-1')
            if final['anomalies'] or abs(expected-actual)>D('.01'):raise QuantError('LEAN_CASH_BRIDGE_FAILED','原生前缀净值与独立账本不一致')
        elif D(final['equity'])!=expected or final['positions'] or final['option_positions'] or D(final['receivables']) or D(final['payables']):
            raise QuantError('LEAN_LEDGER_BRIDGE_FAILED','月度结算后现金/持仓与独立预期不一致')
        write_json(destination/'ledger-path.json',path);write_json(destination/'ledger-bridge.json',final)
        write_json(destination/'lifecycle-receipts.json',lifecycle_receipts)
        daily=[]
        for session in sessions:
            close=calendar.close(session);day=str(session.date());marks={s:stock_price(s,day) for s in stock_symbols}
            for identity,quote in quotes.items():
                if pd.Timestamp(quote['available_at'])<=close and day<=contracts[identity].expiry:marks[identity]=(option_price(identity,day,'bid')+option_price(identity,day,'ask'))/2
            # LEAN's daily OHLC sample ends at next local midnight, including
            # expiry events at that instant. Keep receipt timestamps unchanged.
            valuation_at=((session+pd.Timedelta(days=1)).tz_localize('America/New_York').tz_convert('UTC')
                          if final_lifecycle else close)
            state=book.snapshot('monthly-bridge',valuation_at.to_pydatetime(),marks)
            if state['equity'] is None or state['anomalies']:raise QuantError('LEAN_LEDGER_BRIDGE_FAILED','逐日收盘估值不完整')
            daily.append({'date':str(session.date()),'as_of':valuation_at.isoformat(),'equity':state['equity']})
        pd.DataFrame(daily).to_csv(destination/'daily-equity.csv',index=False)
    finally:book.close()
    proof={'status':'PASSED','data_type':'synthetic_variable_path' if execution_path is not None else 'synthetic_monthly_mechanical','cycles':cycles,'final_lifecycle':final_lifecycle,'expected_equity':str(expected),'actual_equity':str(actual),
        'member':control or last['template_id'],'initial_cash':initial_cash,'option_fee_per_contract':fee_per_contract,
        'retain_stock':retain_stock,'rolling_end_session':str(horizon.date()) if retain_stock else None,'wheel':wheel,'prepare_stock':prepare_stock,
        'wheel_end_session':str(wheel_horizon.date()) if wheel else None,
        'stock_commission_bps':stock_commission_bps,'evaluation_start':first,'evaluation_end':str(sessions[-1].date()),
        'calendar_hash':calendar.hash,'input_hash':digest(body),'statistics':summary['statistics'],
        'ledger_bridge':final,'duplicate_events_added':duplicate['added'],'ledger_path':path,
        'lifecycle_receipts':lifecycle_receipts,'daily_valuation_cutoff':'next_local_midnight' if final_lifecycle else 'session_close',
        'adapter_source':sources,'adapter_dll_sha256':hashlib.sha256(dll.read_bytes()).hexdigest(),'engine_commit':LEAN_COMMIT,
        'data_manifest_hash':digest(manifest),'no_user_account_writes':True,
        'limitations':['明确合成路径；每交易日两采样点同价为工程假设，不是历史策略收益或自然前向' ,'T+1等待是工程假设，不证明券商购买力','计划/前向任务及真实来源资格尚待']}
    write_json(destination/'verification.json',proof);return proof
