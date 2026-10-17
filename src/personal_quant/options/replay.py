"""LEAN adapter verification with frozen synthetic quotes, never real history."""
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
from uuid import uuid4
import zipfile
from ..common import QuantError, decimal as D, digest, now_utc, write_json, utc
from ..data.calendar import Calendar
from .catalog import A8
from .contracts import OptionContract
from .engine import LEAN_COMMIT


def upstream_config(path):
    # Official LEAN uses JSON comments. Match strings first so URL // and
    # comment-like text inside quoted strings remain intact.
    token=re.compile(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/|,(?=\s*[}\]])',re.S)
    text=token.sub(lambda match:match.group() if match.group().startswith('"') else '',Path(path).read_text())
    return json.loads(text)


def fixture_replay(engine_root,dotnet,destination,store,snapshot_id,selection_request,*,initial_cash=100000,fee_per_contract=2,exercise_case=False,market_on_close=False,templates=None,minimum_spread_width=None):
    from .selection import select
    if market_on_close and exercise_case:raise QuantError('INVALID_OPTION_REPLAY','收盘成交诊断与生命周期诊断分别运行')
    root=Path(engine_root).absolute();destination=Path(destination).absolute();dotnet=Path(dotnet).absolute()
    if destination.exists():raise QuantError('NONEMPTY_DESTINATION','期权引擎验证需新目录')
    if D(initial_cash)<=0 or D(fee_per_contract)<0:raise QuantError('INVALID_OPTION_REPLAY','研究资本须为正，费用不可负')
    sdk=subprocess.run([str(dotnet),'--version'],capture_output=True,text=True,check=True).stdout.strip()
    commit=subprocess.run(['git','-C',str(root),'rev-parse','HEAD'],capture_output=True,text=True,check=True).stdout.strip()
    if sdk!='10.0.100' or commit!=LEAN_COMMIT:raise QuantError('LEAN_VERSION_MISMATCH','引擎或SDK不是已验证版本')
    if subprocess.run(['git','-C',str(root),'status','--porcelain'],capture_output=True,text=True,check=True).stdout.strip():
        raise QuantError('LEAN_SOURCE_CHANGED','第三方核心有修改，禁止混作已验证引擎')
    dll=destination/'adapter-bin/LyraX.Options.dll'
    four_templates={'iron_condor','iron_butterfly'}
    credit_templates={'bull_put_credit_spread','bear_call_credit_spread'} | four_templates
    vol_templates={'long_straddle','long_strangle'}
    requested=sorted(A8) if templates is None else templates
    if not isinstance(requested,list) or not requested or any(not isinstance(name,str) for name in requested) or len(set(requested))!=len(requested) or set(requested)-A8-credit_templates-vol_templates:
        raise QuantError('INVALID_OPTION_REPLAY','模板须明确且属于已实现生命周期诊断模板')
    if set(requested)&credit_templates and (minimum_spread_width is None or D(minimum_spread_width)<=0):
        raise QuantError('INVALID_OPTION_REPLAY','信用价差诊断需显式正最小宽度')
    selected={}
    for strategy in sorted(requested):
        parameters=dict(selection_request['parameters'])
        if strategy in credit_templates:parameters['minimum_spread_width']=minimum_spread_width
        result=select(store,snapshot_id,{**selection_request,'template_id':strategy,'parameters':parameters})
        if result['status']!='SELECTED_FOR_RESEARCH':raise QuantError('INCOMPLETE_OPTION_FIXTURE','合成链须覆盖全部八种选约')
        for leg in result['legs']:
            c=OptionContract.from_dict(leg['contract']);c.require_standard_vanilla()
            if c.quote_multiplier!=100 or c.style!='AMERICAN' or c.settlement!='PHYSICAL':
                raise QuantError('UNSUPPORTED_LEAN_FIXTURE','当前适配仅验证标准100股美式实物交割合成样本')
        selected[strategy]=result
    if any(result['data_type']!='synthetic' for result in selected.values()):
        raise QuantError('FIXTURE_ONLY','该入口只能跑合成机械验证，不能冒充真实历史报价接入')
    from datetime import date
    if date.fromisoformat(selection_request['decision_at'][:10])>=utc(now_utc()).date():
        raise QuantError('FUTURE_FIXTURE','引擎只回放已过去的合成样本；不能回测未来交易或偷偷改变其日期')
    destination.mkdir(parents=True);data=destination/'data'
    from .adapter_resources import build as build_adapter
    source=build_adapter(root,dotnet,destination,source_directory='adapter-source',binary_directory='adapter-bin',object_directory='adapter-obj',log_name='adapter-build.log')
    for name in ['market-hours','symbol-properties']:
        shutil.copytree(root/'Data'/name,data/name)
    underlying=selection_request['underlying'];ticker=underlying.lower()
    # Frozen engineering dates: after the decision and seven days before expiry.
    decision=selection_request['decision_at'][:10]
    expiry=next(iter(selected.values()))['expiry']
    import pandas as pd
    calendar=Calendar.market(decision,expiry)
    sessions=[session for session in calendar.sessions if str(session.date())>decision and session<=pd.Timestamp(expiry)-pd.Timedelta(days=7)]
    if len(sessions)<2:raise QuantError('INCOMPLETE_OPTION_FIXTURE','缺少下一交易日及到期前退出日')
    entry,exit=sessions[0],sessions[-1]
    for folder in ['map_files','factor_files']:(data/'equity/usa'/folder).mkdir(parents=True,exist_ok=True)
    (data/'equity/usa/map_files'/f'{ticker}.csv').write_text(f'20000101,{ticker},P\n20501231,{ticker},P\n')
    (data/'equity/usa/factor_files'/f'{ticker}.csv').write_text('20000101,1,1,1\n20501231,1,1,1\n')
    quotes={leg['contract']['contract_id']:leg for result in selected.values() for leg in result['legs']}
    spot=D(next(iter(quotes.values()))['reference_quote']['underlying_price'])
    def ziprow(path,name,row):
        path.parent.mkdir(parents=True,exist_ok=True)
        with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as stream:stream.writestr(name,row+'\n')
    for session in sessions:
        date=session.strftime('%Y%m%d');milliseconds=15*3600000+45*60000
        value=int(spot*10000)
        close_ms=int((calendar.close(session).tz_convert('America/New_York').hour*60+calendar.close(session).tz_convert('America/New_York').minute-1)*60000)
        times=[close_ms-20*60000,close_ms] if market_on_close else [milliseconds]
        ziprow(data/'equity/usa/minute'/ticker/(date+'_trade.zip'),f'{date}_{ticker}_minute_trade.csv',
               '\n'.join(','.join(map(str,[time,value,value,value,value,1000000])) for time in times))
        path=data/'option/usa/minute'/ticker/(date+'_quote_american.zip');path.parent.mkdir(parents=True,exist_ok=True)
        with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as stream:
            for leg in quotes.values():
                c=OptionContract.from_dict(leg['contract']);row=leg['reference_quote']
                bid,ask=int(D(row['bid'])*10000),int(D(row['ask'])*10000)
                name=f'{date}_{ticker}_minute_quote_american_{c.right.lower()}_{int(c.strike*10000)}_{c.expiry.replace("-","")}.csv'
                # Distinct close quote proves MOC does not reuse the submission quote.
                stream.writestr(name,'\n'.join(','.join(map(str,[time,
                    *([bid+(2000 if market_on_close and time==close_ms else 0)]*4),100,
                    *([ask+(2000 if market_on_close and time==close_ms else 0)]*4),100])) for time in times)+'\n')
    cases={}
    expiry_templates={'long_put_worthless_expiry':'long_put','cash_put_worthless_expiry':'cash_secured_put',
        'covered_call_worthless_expiry':'covered_call','protective_put_worthless_expiry':'protective_put',
        'long_call_worthless_expiry':'long_call','collar_worthless_expiry':'collar',
        'bull_call_worthless_expiry':'bull_call_debit_spread','bear_put_worthless_expiry':'bear_put_debit_spread',
        'bull_put_credit_spread_worthless_expiry':'bull_put_credit_spread','bear_call_credit_spread_worthless_expiry':'bear_call_credit_spread',
        'long_straddle_worthless_expiry':'long_straddle','long_strangle_worthless_expiry':'long_strangle'}
    other_cases={'protective_put_exercise':'protective_put','long_call_exercise':'long_call',
        'covered_call_assignment':'covered_call','cash_put_assignment':'cash_secured_put','long_put_itm_exit':'long_put',
        'bull_call_partial_assignment':'bull_call_debit_spread','bear_put_partial_assignment':'bear_put_debit_spread',
        'collar_call_assignment':'collar','collar_put_exercise':'collar',
        'bull_put_credit_spread_partial_assignment':'bull_put_credit_spread','bear_call_credit_spread_partial_assignment':'bear_call_credit_spread',
        'long_straddle_call_exercise':'long_straddle','long_strangle_call_exercise':'long_strangle',
        'long_straddle_put_itm_exit':'long_straddle','long_strangle_put_itm_exit':'long_strangle'}
    for name in sorted(four_templates):
        expiry_templates[name+'_worthless_expiry']=name
        other_cases[name+'_put_assignment']=name
        other_cases[name+'_call_assignment']=name
    lifecycle_cases=[name for name,identifier in {**other_cases,**expiry_templates}.items() if identifier in selected] if exercise_case else []
    for strategy in [*sorted(selected),'benchmark_stock','benchmark_cash',*lifecycle_cases]:
        case=destination/strategy;case.mkdir()
        call_exercise=strategy=='long_call_exercise';exercising=strategy in {'protective_put_exercise','long_call_exercise'}
        vol_call=strategy in {'long_straddle_call_exercise','long_strangle_call_exercise'}
        vol_put=strategy in {'long_straddle_put_itm_exit','long_strangle_put_itm_exit'}
        itm_exit=strategy=='long_put_itm_exit' or vol_put
        four_assignment=strategy.endswith(('_put_assignment','_call_assignment')) and strategy.rsplit('_',2)[0] in four_templates
        collar_assignment=strategy=='collar_call_assignment';collar_exercise=strategy=='collar_put_exercise';put_spread=(four_assignment and strategy.endswith('_put_assignment')) or strategy in {'bear_put_partial_assignment','bull_put_credit_spread_partial_assignment'}
        assigning=strategy in {'covered_call_assignment','cash_put_assignment'};put_assignment=strategy=='cash_put_assignment';expiring=strategy in expiry_templates;spread=four_assignment or strategy in {'bull_call_partial_assignment','bear_put_partial_assignment','bull_put_credit_spread_partial_assignment','bear_call_credit_spread_partial_assignment'};lifecycle=exercising or assigning or expiring or spread or itm_exit or collar_assignment or collar_exercise or vol_call
        template_name=expiry_templates.get(strategy) or other_cases.get(strategy) or strategy
        chosen=selected.get(template_name);legs=chosen['legs'] if chosen else []
        shares=100 if template_name in {'protective_put','collar','covered_call','benchmark_stock'} else 0
        execution_data=data
        if lifecycle:
            execution_data=case/'data';shutil.copytree(data,execution_data)
            c=OptionContract.from_dict(legs[-1 if spread or collar_assignment else 0]['contract'])
            if four_assignment:c=OptionContract.from_dict(next(leg['contract'] for leg in legs if leg['quantity_per_package']<0 and leg['contract']['right']==('PUT' if put_spread else 'CALL')))
            if vol_call or vol_put:c=OptionContract.from_dict(next(leg['contract'] for leg in legs if leg['contract']['right']==('CALL' if vol_call else 'PUT')))
            positive=(c.right=='PUT') if expiring else (spread and not put_spread) or collar_assignment or call_exercise or vol_call or (assigning and not put_assignment)
            exercise_spot=c.strike+(D(10) if positive else -D(10))
            if expiring:
                rights={leg['contract']['right'] for leg in legs}
                strikes=[D(leg['contract']['strike']) for leg in legs]
                exercise_spot=min(strikes)-10 if rights=={'CALL'} else max(strikes)+10 if rights=={'PUT'} else spot
                if any((exercise_spot>D(leg['contract']['strike']) if leg['contract']['right']=='CALL' else exercise_spot<D(leg['contract']['strike'])) for leg in legs):
                    raise QuantError('INVALID_OPTION_FIXTURE','无价值到期样例必须逐腿无内在价值')
            if exercise_spot<=0:raise QuantError('INVALID_OPTION_FIXTURE','行权样例需正标的价格')
            day=exit.strftime('%Y%m%d');value=int(exercise_spot*10000)
            ziprow(execution_data/'equity/usa/minute'/ticker/(day+'_trade.zip'),f'{day}_{ticker}_minute_trade.csv',
                   ','.join(map(str,[milliseconds,value,value,value,value,1000000])))
            bid=99000 if assigning or spread or collar_assignment else 100000;ask=bid+1000
            with zipfile.ZipFile(execution_data/'option/usa/minute'/ticker/(day+'_quote_american.zip'),'w',zipfile.ZIP_DEFLATED) as stream:
                name=f'{day}_{ticker}_minute_quote_american_{c.right.lower()}_{int(c.strike*10000)}_{c.expiry.replace("-","")}.csv'
                stream.writestr(name,','.join(map(str,[milliseconds,bid,bid,bid,bid,100,ask,ask,ask,ask,100]))+'\n')
                if vol_call or vol_put:
                    other=OptionContract.from_dict(next(leg['contract'] for leg in legs if leg['contract']['right']!=c.right))
                    name=f'{day}_{ticker}_minute_quote_american_{other.right.lower()}_{int(other.strike*10000)}_{other.expiry.replace("-","")}.csv'
                    stream.writestr(name,','.join(map(str,[milliseconds,100,100,100,100,100,200,200,200,200,100]))+'\n')
                if spread:
                    long=OptionContract.from_dict(next(leg['contract'] for leg in legs if leg['quantity_per_package']>0 and leg['contract']['right']==c.right));long_bid=int((long.strike-exercise_spot if put_spread else exercise_spot-long.strike)*10000)
                    long_name=f'{day}_{ticker}_minute_quote_american_{long.right.lower()}_{int(long.strike*10000)}_{long.expiry.replace("-","")}.csv'
                    stream.writestr(long_name,','.join(map(str,[milliseconds,long_bid,long_bid,long_bid,long_bid,100,long_bid+1000,long_bid+1000,long_bid+1000,long_bid+1000,100]))+'\n')
                if four_assignment:
                    for leg in legs:
                        term=OptionContract.from_dict(leg['contract'])
                        if term.right==c.right:continue
                        name=f'{day}_{ticker}_minute_quote_american_{term.right.lower()}_{int(term.strike*10000)}_{term.expiry.replace("-","")}.csv'
                        stream.writestr(name,','.join(map(str,[milliseconds,100,100,100,100,100,200,200,200,200,100]))+'\n')
                if collar_assignment or collar_exercise:
                    other=OptionContract.from_dict(legs[0 if collar_assignment else 1]['contract'])
                    name=f'{day}_{ticker}_minute_quote_american_{other.right.lower()}_{int(other.strike*10000)}_{other.expiry.replace("-","")}.csv'
                    stream.writestr(name,','.join(map(str,[milliseconds,100,100,100,100,100,200,200,200,200,100]))+'\n')
            if spread:
                recovery_session=next(day for day in Calendar.market(str(exit.date()),str((exit+pd.Timedelta(days=7)).date())).sessions if day>exit)
                recovery_day=recovery_session.strftime('%Y%m%d');recovery_ms=9*3600000+30*60000
                ziprow(execution_data/'equity/usa/minute'/ticker/(recovery_day+'_trade.zip'),f'{recovery_day}_{ticker}_minute_trade.csv',
                       ','.join(map(str,[recovery_ms,value,value,value,value,1000000])))
                with zipfile.ZipFile(execution_data/'option/usa/minute'/ticker/(recovery_day+'_quote_american.zip'),'w',zipfile.ZIP_DEFLATED) as stream:
                    for leg in legs:
                        term=OptionContract.from_dict(leg['contract']);leg_bid=int((term.strike-exercise_spot if put_spread else exercise_spot-term.strike)*10000)-(1000 if leg['quantity_per_package']<0 else 0)
                        if four_assignment and term.right!=c.right:leg_bid=100
                        name=f'{recovery_day}_{ticker}_minute_quote_american_{term.right.lower()}_{int(term.strike*10000)}_{term.expiry.replace("-","")}.csv'
                        leg_ask=200 if four_assignment and term.right!=c.right else leg_bid+1000
                        stream.writestr(name,','.join(map(str,[recovery_ms,*([leg_bid]*4),100,*([leg_ask]*4),100]))+'\n')
            if expiring or collar_assignment:
                expiry_sessions=Calendar.market(str(exit.date()),str(pd.Timestamp(c.expiry)+pd.Timedelta(days=1))[:10]).sessions
                for session in expiry_sessions:
                    day=session.strftime('%Y%m%d');value=int(exercise_spot*10000)
                    ziprow(execution_data/'equity/usa/minute'/ticker/(day+'_trade.zip'),f'{day}_{ticker}_minute_trade.csv',
                           ','.join(map(str,[milliseconds,value,value,value,value,1000000])))
                    if session.date()<=pd.Timestamp(c.expiry).date():
                        with zipfile.ZipFile(execution_data/'option/usa/minute'/ticker/(day+'_quote_american.zip'),'w',zipfile.ZIP_DEFLATED) as stream:
                            for leg in legs:
                                term=OptionContract.from_dict(leg['contract'])
                                name=f'{day}_{ticker}_minute_quote_american_{term.right.lower()}_{int(term.strike*10000)}_{term.expiry.replace("-","")}.csv'
                                leg_bid=99000 if collar_assignment and term.right=='CALL' else 100
                                leg_ask=leg_bid+1000 if collar_assignment and term.right=='CALL' else 200
                                stream.writestr(name,','.join(map(str,[milliseconds,*([leg_bid]*4),100,*([leg_ask]*4),100]))+'\n')
        body={'data_type':'synthetic_mechanical_fixture','underlying':underlying,'initial_cash':float(initial_cash),
              'fee_per_contract':float(fee_per_contract),'underlying_shares':shares,
              'entry_at_market_time':str(entry.date())+'T15:46:00','exit_at_market_time':str(exit.date())+'T15:46:00',
              'legs':[{'right':leg['contract']['right'],'strike':float(D(leg['contract']['strike'])),
                       'expiry':leg['contract']['expiry'],'quantity':leg['quantity_per_package'],'multiplier':100} for leg in legs]}
        if exercising:body['exit_action']='exercise'
        if vol_call:body['exit_action']='vol_call_exercise'
        if market_on_close:
            body.update(execution_method='market_on_close',
                entry_at_market_time=(calendar.close(entry).tz_convert('America/New_York')-pd.Timedelta(minutes=20)).strftime('%Y-%m-%dT%H:%M:%S'),
                exit_at_market_time=(calendar.close(exit).tz_convert('America/New_York')-pd.Timedelta(minutes=20)).strftime('%Y-%m-%dT%H:%M:%S'))
        if assigning:body['exit_action']='assignment'
        if spread:body['exit_action']='spread_put_assignment' if put_spread else 'spread_assignment'
        if spread:body['recovery_at_market_time']=str(recovery_session.date())+'T09:31:00'
        if expiring:body.update(exit_action='expiry',exit_at_market_time=c.expiry+'T15:46:00')
        if collar_assignment:body.update(exit_action='collar_assignment',exit_at_market_time=c.expiry+'T15:46:00')
        if collar_exercise:body['exit_action']='collar_put_exercise'
        if put_assignment or call_exercise or vol_call or (expiring and shares):body['expected_end_shares']=100
        if lifecycle:body['exercise_and_delivery_fee_per_contract']=0
        if assigning:body['assignment_model']='LEAN_DefaultOptionAssignmentModel_prior_expiration_10_days'
        write_json(case/'input.json',body)
        data_manifest={str(path.relative_to(execution_data)):hashlib.sha256(path.read_bytes()).hexdigest()
                       for path in sorted(execution_data.rglob('*')) if path.is_file()}
        write_json(case/'data-files.json',data_manifest)
        config=upstream_config(root/'Launcher/config.json')
        config.update({'algorithm-type-name':'LyraX.LyraXReplay','algorithm-location':str(dll),'data-folder':str(execution_data),
                       'results-destination-folder':str(case),'parameters':{'lyrax-input':str(case/'input.json')},'close-automatically':True})
        write_json(case/'config.json',config)
        launcher=root/'Launcher/bin/Release/QuantConnect.Lean.Launcher.dll'
        with (case/'launcher.log').open('w') as log:
            run=subprocess.run([str(dotnet),str(launcher),'--config',str(case/'config.json')],cwd=launcher.parent,
                env=dict(os.environ,DOTNET_CLI_HOME='/tmp/lyrax-dotnet-home'),stdout=log,stderr=subprocess.STDOUT,timeout=180)
        summary_path=case/'LyraX.LyraXReplay-summary.json'
        if not summary_path.exists():summary_path=case/'LyraXReplay-summary.json'
        if run.returncode or not summary_path.exists():raise QuantError('LEAN_REPLAY_FAILED','合成引擎运行失败，查看 '+str(case/'launcher.log'))
        summary=json.loads(summary_path.read_text());state=summary['state']
        if state['Status']!='Completed' or state.get('RuntimeError'):raise QuantError('LEAN_REPLAY_FAILED','LEAN未完整执行 '+strategy)
        leg_count=len(legs);expected=D(initial_cash)-sum((D(leg['reference_quote']['ask'])-D(leg['reference_quote']['bid']))*100 for leg in legs)-D(fee_per_contract)*2*leg_count
        if exercising:expected=D(initial_cash)-spot*100-D(legs[0]['reference_quote']['ask'])*100-D(fee_per_contract)+c.exercise_cash
        if call_exercise:expected=D(initial_cash)-D(legs[0]['reference_quote']['ask'])*100-D(fee_per_contract)-c.exercise_cash+exercise_spot*100
        if assigning:expected=D(initial_cash)-spot*100+D(legs[0]['reference_quote']['bid'])*100-D(fee_per_contract)+c.exercise_cash
        if put_assignment:expected=D(initial_cash)+D(legs[0]['reference_quote']['bid'])*100-D(fee_per_contract)-c.exercise_cash+exercise_spot*100
        if expiring:expected=D(initial_cash)-sum(D(leg['quantity_per_package'])*D(leg['reference_quote']['ask' if leg['quantity_per_package']>0 else 'bid'])*100 for leg in legs)-D(fee_per_contract)*len(legs)+(exercise_spot-spot)*shares
        if itm_exit:expected=D(initial_cash)-D(legs[0]['reference_quote']['ask'])*100+10*100-D(fee_per_contract)*2
        if vol_call or vol_put:
            expected=D(initial_cash)-sum(D(leg['reference_quote']['ask'])*100 for leg in legs)-D(fee_per_contract)*(3 if vol_call else 4)+D(1001)
        if spread:expected=D(initial_cash)+c.exercise_cash-OptionContract.from_dict(legs[0]['contract']).exercise_cash-D(legs[0]['reference_quote']['ask'])*100+D(legs[1]['reference_quote']['bid'])*100-D(fee_per_contract)*2
        if put_spread:expected=D(initial_cash)+OptionContract.from_dict(legs[0]['contract']).exercise_cash-c.exercise_cash-D(legs[0]['reference_quote']['ask'])*100+D(legs[1]['reference_quote']['bid'])*100-D(fee_per_contract)*2
        if four_assignment:
            protection=OptionContract.from_dict(next(leg['contract'] for leg in legs if leg['quantity_per_package']>0 and leg['contract']['right']==c.right))
            opening=-sum(D(leg['reference_price'])*leg['quantity_per_package']*100 for leg in legs)
            expected=D(initial_cash)+opening-abs(c.strike-protection.strike)*100-D(fee_per_contract)*6-1
        if collar_assignment:expected=D(initial_cash)-spot*100-D(legs[0]['reference_quote']['ask'])*100+D(legs[1]['reference_quote']['bid'])*100-D(fee_per_contract)*2+c.exercise_cash
        if collar_exercise:expected=D(initial_cash)-spot*100-D(legs[0]['reference_quote']['ask'])*100+D(legs[1]['reference_quote']['bid'])*100-D('.02')*100-D(fee_per_contract)*3+c.exercise_cash
        actual=D(summary['statistics']['End Equity'].replace(',','').replace('$',''))
        if abs(actual-expected)>D('.01'):raise QuantError('LEAN_CASH_BRIDGE_FAILED',f'{strategy}期末{actual}不符独立买ask/卖bid手算{expected}')
        cases[strategy]={'status':'PASSED','expected_equity':str(expected),'actual_equity':str(actual),'statistics':summary['statistics'],
                         'decision_hash':chosen['decision_hash'] if chosen else None,'input_hash':digest(body),
                         'data_root':str(execution_data),'data_manifest_hash':digest(data_manifest),
                         'purpose':'lifecycle_validation' if lifecycle else 'strategy_mechanical_comparison',
                         'entry_at_market_time':body['entry_at_market_time'],'exit_at_market_time':body['exit_at_market_time']}
        if market_on_close:
            events=json.loads((case/'engine-events.json').read_text())
            if len(events)!=2*(len(legs)+(1 if shares else 0)):
                raise QuantError('LEAN_EXECUTION_TIME_FAILED','收盘订单数量与完整开平仓预期不一致')
            for event in events:
                instant=pd.Timestamp(event['utc_time'])
                if event['order_type']!='MarketOnClose' or instant!=calendar.close(instant.tz_convert('America/New_York').date()):
                    raise QuantError('LEAN_EXECUTION_TIME_FAILED','收盘订单未在该交易日实际收盘成交')
                if event['symbol']!=underlying:
                    side='ask' if D(event['quantity'])>0 else 'bid'
                    matches=[leg for leg in legs if event['symbol'].endswith(
                        ('C' if leg['contract']['right']=='CALL' else 'P')+f'{int(D(leg["contract"]["strike"])*1000):08d}')]
                    if len(matches)!=1 or D(event['price'])!=D(matches[0]['reference_quote'][side])+D('.2'):
                        raise QuantError('LEAN_EXECUTION_PRICE_FAILED','收盘订单未使用独立的收盘报价')
        if lifecycle:
            events=json.loads((case/'engine-events.json').read_text())
            exercises=[e for e in events if e['order_type']=='OptionExercise' and e['symbol']==e['order_symbol']]
            if spread:
                if len(exercises)!=2 or sum(e['assignment'] for e in exercises)!=1:raise QuantError('LEAN_LIFECYCLE_FAILED','缺少短腿指派和长腿保护行权')
            elif collar_assignment:
                if len(exercises)!=2 or sum(e['assignment'] for e in exercises)!=1 or sum(e['in_the_money'] for e in exercises)!=1:raise QuantError('LEAN_LIFECYCLE_FAILED','缺少collar Call指派和剩余Put到期')
            elif collar_exercise:
                if len(exercises)!=1 or not exercises[0]['in_the_money'] or exercises[0]['assignment']:raise QuantError('LEAN_LIFECYCLE_FAILED','缺少collar Put行权')
            elif expiring:
                if len(exercises)!=len(legs) or len({e['order_symbol'] for e in exercises})!=len(legs) or any(e['in_the_money'] for e in exercises):raise QuantError('LEAN_LIFECYCLE_FAILED','缺少逐腿官方无价值到期事件')
            elif itm_exit:
                fills=[e for e in events if e['symbol']!=underlying]
                if exercises or len(fills)!=2*len(legs) or sum(D(e['quantity']) for e in fills)!=0:raise QuantError('LEAN_LIFECYCLE_FAILED','价内退出必须是完整买入/卖出，不能记为行权')
            elif len(exercises)!=1 or exercises[0]['in_the_money']==expiring or (not expiring and exercises[0]['assignment']!=assigning):raise QuantError('LEAN_LIFECYCLE_FAILED','缺少成熟引擎实际行权/指派/到期事件')
            from ..portfolio.ledger import Ledger
            from ..portfolio.schema import apply_workbench_schema,apply_v18_schema,apply_v19_schema
            from .ledger import register_contract
            book=Ledger(case/'bridge.sqlite','demo');book.account('engine-bridge')
            try:
                with book.transaction():apply_workbench_schema(book.connection);apply_v18_schema(book.connection);apply_v19_schema(book.connection)
                registered=[register_contract(book,leg['contract']) for leg in legs]
                def event_contract(event):
                    matches=[contract for contract in registered if event['order_symbol'].endswith(('C' if contract.right=='CALL' else 'P')+f'{int(contract.strike*1000):08d}')]
                    if len(matches)!=1:raise QuantError('LEAN_UNIT_MAPPING_FAILED','引擎事件不能唯一匹配冻结合约')
                    return matches[0]
                rows=[{'event_id':'capital','kind':'DEPOSIT','amount':str(initial_cash),'source':'synthetic_lean','evidence_type':'test','effective_at':events[0]['utc_time']}]
                for e in events:
                    base={'event_id':str(e['order_id'])+':'+str(e['event_id']),'source':'synthetic_lean','evidence_type':'test',
                          'effective_at':e['utc_time'],'settlement_at':e['utc_time'],'quantity':abs(e['quantity']),'price':e['price'],'fee':e['fee']}
                    if e['order_type']=='OptionExercise':
                        if e['symbol']!=e['order_symbol']:continue # Delivery is represented once by the option event.
                        contract=event_contract(e)
                        direction=next(leg['quantity_per_package'] for leg in legs if leg['contract_version']==contract.version_hash)
                        base.update(kind='OPTION_EXPIRY' if not e['in_the_money'] else 'OPTION_ASSIGNMENT' if e['assignment'] else 'OPTION_EXERCISE',contract_version=contract.version_hash,position_side='SHORT' if direction<0 else 'LONG')
                    elif e['symbol']==underlying:base.update(kind='BUY' if e['quantity']>0 else 'SELL',symbol=underlying)
                    else:
                        contract=event_contract(e)
                        direction=next(leg['quantity_per_package'] for leg in legs if leg['contract_version']==contract.version_hash)
                        base.update(kind='OPTION_TRADE',contract_version=contract.version_hash,action='OPEN' if D(e['quantity'])*direction>0 else 'CLOSE',trade_side='SELL' if e['quantity']<0 else 'BUY')
                    rows.append(base)
                book.import_events('engine-bridge',rows)
                if spread:
                    path=[]
                    for sequence,row in enumerate(rows,1):
                        if row['kind'] not in {'OPTION_ASSIGNMENT','OPTION_EXERCISE'}:continue
                        point=book.snapshot('engine-bridge',row['effective_at'],{underlying:exercise_spot},ledger_seq=sequence)
                        path.append({'event_kind':row['kind'],'snapshot':point})
                    if len(path)!=2 or path[0]['snapshot']['positions'].get(underlying)!=('100' if put_spread else '-100') or path[1]['snapshot']['positions']:
                        raise QuantError('LEAN_LEDGER_BRIDGE_FAILED','多腿指派后的临时空头及恢复路径不一致')
                    if (not put_spread and not path[0]['snapshot']['anomalies']) or path[1]['snapshot']['anomalies']:
                        raise QuantError('LEAN_LEDGER_BRIDGE_FAILED','临时证券空头必须阻断新计划，恢复后异常应解除')
                    # Missing option marks remain explicit; no future quote is used to value this prefix.
                    write_json(case/'ledger-lifecycle-path.json',path)
                    cases[strategy]['ledger_lifecycle_path']=path
                state=book.snapshot('engine-bridge',events[-1]['utc_time'],{underlying:exercise_spot})
                expected_positions={underlying:'100'} if put_assignment or call_exercise or vol_call or (expiring and shares) else {}
                if D(state['equity'])!=expected or state['positions']!=expected_positions or state['option_positions']:
                    raise QuantError('LEAN_LEDGER_BRIDGE_FAILED','引擎行权事件与统一账本现金/证券不一致')
                write_json(case/'ledger-bridge.json',state);cases[strategy]['ledger_bridge']=state
            finally:book.close()
    proof={'status':'PASSED','data_type':'synthetic_mechanical_fixture','engine':'LEAN','engine_commit':commit,'sdk':sdk,
           'templates':sorted(selected),'minimum_spread_width':minimum_spread_width,
           'execution_method':'market_on_close' if market_on_close else 'market_at_15_46',
           'adapter_source':source,'adapter_dll_sha256':hashlib.sha256(dll.read_bytes()).hexdigest(),
           'snapshot_id':snapshot_id,'entry_session':str(entry.date()),'exit_session':str(exit.date()),'cases':cases,
           'lifecycle_validation':{'explicit_itm_protective_put_exercise':exercise_case,
                                   'covered_call_default_model_assignment':exercise_case,
                                   'cash_put_default_model_assignment':exercise_case,
                                   'long_put_worthless_expiry':exercise_case,
                                   'cash_put_worthless_expiry':exercise_case,
                                   'covered_call_worthless_expiry':exercise_case,
                                   'protective_put_worthless_expiry':exercise_case,
                                   'long_call_worthless_expiry':exercise_case,
                                   'long_call_funded_exercise':exercise_case,
                                   'collar_worthless_expiry':exercise_case,
                                   'bull_call_worthless_expiry':exercise_case,
                                   'bear_put_worthless_expiry':exercise_case,
                                   'long_put_itm_exit':exercise_case,
                                   'bull_call_partial_assignment_and_protection':exercise_case,
                                   'bear_put_partial_assignment_and_protection':exercise_case,
                                   'collar_call_assignment_and_put_expiry':exercise_case,
                                   'collar_call_close_before_put_exercise':exercise_case,
                                   'exercise_and_delivery_fees':0 if exercise_case else None,
                                   'assignment_prior_expiration_days':10 if exercise_case else None,
                                   'unvalidated':['other_multi_leg_assignment_paths','discrete_dividend_actions','monthly_schedule']},
           'generated_at':now_utc(),'no_account_writes':not exercise_case,'no_user_account_writes':True,
           'limitations':['标准100股美式合约的合成开平仓机械验证；固定价格用于独立费用/价差现金桥接，不是历史策略收益',
                          '生命周期覆盖报告所列模板的指定开平仓/行权/指派/到期分支；不证明实际概率、分红路径或全部现实异常',
                          '已指定模板和股票/现金控制组使用共同区间；生命周期诊断有独立结束时点，不拿其净值/年化混作公平策略比较',
                          '不验证真实历史链、离散公司行动、未知调整合约或实盘多腿执行；计划保持不可执行',
                          '尚未验证非零滑点；bid/ask及每张费用由LEAN处理，ETF与期权比较使用同一引擎/资本/区间']}
    write_json(destination/'verification.json',proof);return proof
