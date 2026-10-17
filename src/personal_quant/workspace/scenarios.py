"""Seeded synthetic prices and American-option model quotes, never market evidence."""
import hashlib
import importlib.metadata
import math
from pathlib import Path
import random
import shutil
import tempfile
from decimal import ROUND_FLOOR,ROUND_CEILING,ROUND_HALF_EVEN,getcontext
import pandas as pd
from ..common import QuantError,decimal as D,digest,utc,now_utc
from ..data.calendar import Calendar
from ..data.store import DataStore
from ..options.contracts import OptionContract
from ..options.data import OptionDataStore
from ..options.pricing import price
from ..locks import publish_directory
from .packages import seal,verify

VERSION='synthetic-scenario/2.0.0'
FIELDS={'schema_version','start','end','initial_prices','price_nodes','daily_volatility','iv_nodes','option_underlying',
        'expiry_days','strike_step','spread','seed','missing_quotes','corporate_actions'}


def normalize(spec):
    if not isinstance(spec,dict) or set(spec)!=FIELDS or type(spec['schema_version']) is not int or spec['schema_version']!=1:
        raise QuantError('INVALID_SCENARIO','场景需schema1及完整参数，不隐式使用真实风险默认值')
    try:
        for key in ('start','end'):
            if pd.Timestamp(spec[key]).date().isoformat()!=spec[key]:raise ValueError('date')
        start,end=pd.Timestamp(spec['start']),pd.Timestamp(spec['end'])
        if start>=end or (end-start).days>3*366 or end.date()>=utc(now_utc()).date():raise ValueError('range')
        initial=spec['initial_prices'];nodes=spec['price_nodes']
        if (not isinstance(initial,dict) or not 1<=len(initial)<=10 or any(not isinstance(k,str) or not k or D(v)<=0 for k,v in initial.items())
                or not isinstance(nodes,dict) or set(nodes)!=set(initial) or spec['option_underlying'] not in initial):raise ValueError('symbols')
        for row in [*nodes.values(),spec['iv_nodes']]:
            if not isinstance(row,dict):raise ValueError('nodes')
            for day,value in row.items():
                if pd.Timestamp(day).date().isoformat()!=day or not start<=pd.Timestamp(day)<=end or D(value)<=0:raise ValueError('node')
        if spec['start'] not in spec['iv_nodes'] or any(D(v)>4 for v in spec['iv_nodes'].values()):raise ValueError('volatility')
        if not 0<=D(spec['daily_volatility'])<=D('.2') or D(spec['strike_step'])<=0 or D(spec['spread'])<D('.01'):raise ValueError('model')
        if type(spec['seed']) is not int or type(spec['expiry_days']) is not int or not 7<=spec['expiry_days']<=90:raise ValueError('seed/dte')
        if not isinstance(spec['missing_quotes'],list) or any(pd.Timestamp(d).date().isoformat()!=d or not start<=pd.Timestamp(d)<=end for d in spec['missing_quotes']):raise ValueError('missing days')
        if not isinstance(spec['corporate_actions'],list):raise ValueError('actions')
    except (TypeError,ValueError,KeyError) as exc:
        raise QuantError('INVALID_SCENARIO','场景日期、价格/IV节点、种子或数量边界无效') from exc
    return spec


def generate(spec,destination):
    spec=normalize(spec);destination=Path(destination).absolute()
    if destination.exists():raise QuantError('NONEMPTY_DESTINATION','场景输出需新的独立目录')
    destination.parent.mkdir(parents=True,exist_ok=True)
    pending=Path(tempfile.mkdtemp(prefix='.pending-scenario-',dir=destination.parent))
    try:
        calendar=Calendar.market(str((pd.Timestamp(spec['start'])-pd.Timedelta(days=230)).date()),
                                 str((pd.Timestamp(spec['end'])+pd.Timedelta(days=150)).date()))
        days=calendar.sessions[(calendar.sessions>=spec['start'])&(calendar.sessions<=spec['end'])]
        if len(days)<2 or len(days)>756:raise QuantError('SCENARIO_TOO_LARGE','场景需2至756个交易日')
        declared=[spec['start'],spec['end'],*spec['iv_nodes'],*spec['missing_quotes'],
                  *(day for nodes in spec['price_nodes'].values() for day in nodes)]
        if any(pd.Timestamp(day) not in days for day in declared):
            raise QuantError('NON_SESSION','场景边界、价格/IV节点和缺价日期须是已核验交易日')
        sources={str(p.name):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),Path(__file__).parents[1]/'options/pricing.py']}
        model={'generator':VERSION,'sources':sources,'QuantLib':importlib.metadata.version('QuantLib'),
               'stock_price_tick':'0.0001','stock_rounding':'ROUND_HALF_EVEN','decimal_precision':getcontext().prec}
        source=VERSION+'/'+digest(model)[:16];stock_rows=[];paths={};ivs={};iv=D(spec['iv_nodes'][spec['start']])
        for day in calendar.sessions[calendar.sessions<=spec['end']]:
            key=str(day.date())
            if key in spec['iv_nodes']:iv=D(spec['iv_nodes'][key])
            ivs[key]=iv
        for symbol,initial in sorted(spec['initial_prices'].items()):
            rng=random.Random(int(digest({'seed':spec['seed'],'symbol':symbol})[:16],16));value=D(initial);path={}
            for day in calendar.sessions[calendar.sessions<=spec['end']]:
                key=str(day.date())
                if key in spec['price_nodes'][symbol]:value=D(spec['price_nodes'][symbol][key])
                elif day>pd.Timestamp(spec['start']) and D(spec['daily_volatility']):
                    value*=D(str(math.exp(rng.gauss(0,float(spec['daily_volatility'])))))
                value=value.quantize(D('.0001'),rounding=ROUND_HALF_EVEN)
                if value<=0:raise QuantError('INVALID_SCENARIO','价格低于场景声明的万分单位')
                path[key]=str(value)
                stock_rows.append({'symbol':symbol,'session_date':key,'market':'XNYS','currency':'USD','source':source,
                    'data_type':'synthetic','price_basis':'unadjusted','open':float(value),'high':float(value),'low':float(value),
                    'close':float(value),'adj_close':float(value),'volume':100000,'dividends':0,'split_ratio':1,
                    'available_at':(calendar.close(day)+pd.Timedelta(minutes=30)).isoformat()})
            paths[symbol]=path
        observed=Calendar(calendar.schedule.loc[:spec['end']],calendar.kind)
        stock=DataStore(pending/'data').save(pd.DataFrame(stock_rows),observed)
        chain=OptionDataStore(pending/'chains');snapshots=[];cycles=[];world={}
        underlying=spec['option_underlying'];step=D(spec['strike_step']);spread=D(spec['spread']);tick=D('.01')
        metadata={'schema_version':1,'source':source,'data_type':'synthetic','license_terms':'locally generated model scenario',
                  'unit_evidence':'fictional standard American physical 100-share terms, not actual contract evidence',
                  'available_time_basis':'synthetic node prices held constant intraday; model quote at minute before decision close'}
        for decision in calendar.month_ends():
            if decision not in days or calendar.next(decision)>pd.Timestamp(spec['end']):continue
            decision_key=str(decision.date());spot=D(paths[underlying][decision_key]);center=(spot/step).to_integral_value()*step
            expiry=next(d for d in calendar.sessions if d>=decision+pd.Timedelta(days=spec['expiry_days']))
            at=calendar.close(decision)-pd.Timedelta(minutes=1);contracts=[];quotes=[]
            for right in ('PUT','CALL'):
                for strike in [center+step*k for k in range(-3,4) if center+step*k>0]:
                    contract=OptionContract.from_dict({'contract_id':f'SYNTHETIC-{underlying}-{expiry.date()}-{right}-{strike}',
                        'revision':VERSION,'underlying':underlying,'currency':'USD','market_timezone':'America/New_York','right':right,'strike':str(strike),
                        'expiry':str(expiry.date()),'listed_at':calendar.close(decision-pd.offsets.BDay(20)).isoformat() if decision-pd.offsets.BDay(20) in calendar.sessions else calendar.close(calendar.sessions[0]).isoformat(),
                        'last_trade_at':calendar.close(expiry).isoformat(),'exercise_cutoff_at':(calendar.close(expiry)+pd.Timedelta(minutes=90)).isoformat(),
                        'quote_multiplier':'100','deliverable_shares':'100','deliverable_cash':'0','exercise_cash':str(strike*100),
                        'settlement':'PHYSICAL','style':'AMERICAN','tick_size':str(tick),'evidence_hash':'synthetic_model_terms_not_actual_evidence'})
                    contracts.append(contract.content());values={}
                    for day in days[(days>=decision)&(days<=expiry)]:
                        key=str(day.date())
                        if key in spec['missing_quotes']:continue
                        current=D(paths[underlying][key])
                        mid=(D(max(0,float(current-strike if right=='CALL' else strike-current))) if day==expiry else
                             D(str(price(right=right,style='AMERICAN',spot=current,strike=strike,valuation_date=key,expiry=str(expiry.date()),
                                         volatility=ivs[key],include_greeks=False)['unit_price'])))
                        bid=max(tick,((mid-spread/2)/tick).to_integral_value(rounding=ROUND_FLOOR)*tick)
                        ask=max(bid+tick,((mid+spread/2)/tick).to_integral_value(rounding=ROUND_CEILING)*tick)
                        values[key]={'bid':str(bid),'ask':str(ask)}
                        if day==decision:
                            row={'contract_id':contract.contract_id,'contract_version':contract.version_hash,'source':source,
                                 'bid':str(bid),'ask':str(ask),'last':str(mid),'underlying_price':str(current),'bid_size':'100','ask_size':'100','volume':'1000','open_interest':'1000'}
                            for name in ('exchange_timestamp','available_at','received_at','last_timestamp','underlying_timestamp','open_interest_available_at'):row[name]=at.isoformat()
                            quotes.append(row)
                    world[contract.contract_id]=values
            if not quotes:raise QuantError('SCENARIO_DECISION_QUOTES_MISSING','决策日缺报价；场景未发布为可执行输入')
            saved=chain.save(contracts,pd.DataFrame(quotes),metadata);snapshots.append(saved['snapshot_id'])
            cycles.append({'decision_session':decision_key,'snapshot_id':saved['snapshot_id'],'expiry':str(expiry.date())})
        if not cycles:raise QuantError('NO_MONTHLY_DECISIONS','场景须覆盖至少一次月末及下一交易日')
        from ..common import write_json
        write_json(pending/'scenario.json',{'schema_version':1,'spec':spec,'model':model,'cycles':cycles,
                    'execution_path':{'schema_version':1,'data_type':'synthetic','stocks':{s:{str(d.date()):p[str(d.date())] for d in days} for s,p in paths.items()},'options':world},
                    'meaning':'QuantLib模型生成的合成路径，非历史行情/可成交报价；公司行动非空时暂停配置'})
        checks=['CORPORATE_ACTION_REQUIRES_QUALIFIED_INPUT'] if spec['corporate_actions'] else []
        body=seal(pending,roles={k:stock['snapshot_id'] for k in ('signal','execution','valuation')},chain_snapshots=snapshots,spec=spec,checks=checks)
        verify(pending);publish_directory(pending,destination)
        return {'status':'GENERATED','check_status':'BLOCKED' if checks else 'PASSED','directory':str(destination),'input_bundle_id':body['input_bundle_id'],
                'data_type':'synthetic','model':model,'cycles':len(cycles),'market_sessions':len(days),'checks':checks,'executable':False,'source_qualification':'UNVERIFIED'}
    finally:
        if pending.exists():shutil.rmtree(pending)
