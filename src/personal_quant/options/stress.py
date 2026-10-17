"""Explicit model scenarios; remaining time value is priced by QuantLib."""
from datetime import date
import copy
from decimal import getcontext
import hashlib
import importlib.metadata
from pathlib import Path
from ..common import QuantError, decimal, digest,finite_float
from .contracts import Leg
from .pricing import price

GREEK_UNITS={'delta':'组合价值对标的价格增加1 USD的变化（USD/USD）',
    'gamma':'组合价值对标的价格的二阶敏感度（USD/USD²）',
    'theta_per_calendar_day':'每经过1自然日的价值变化（USD/日）',
    'vega_per_vol_point':'波动率增加1个百分点的价值变化（USD）',
    'rho_per_rate_point':'利率增加1个百分点的价值变化（USD）'}


def model_identity():
    root=Path(__file__).parent
    sources={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in ['stress.py','pricing.py','contracts.py','risk_lab.py']}
    sources['common.py']=hashlib.sha256((root.parent/'common.py').read_bytes()).hexdigest()
    try:version=importlib.metadata.version('QuantLib')
    except importlib.metadata.PackageNotFoundError:version=None
    return {'profile':'option-stress/1.95.1','sources':sources,'QuantLib':version,
        'decimal_precision':getcontext().prec,'decimal_rounding':getcontext().rounding}


def evaluate(request):
    identity=model_identity()
    fields={'legs','valuation_date','horizon_date','underlying_prices','volatility_multipliers','models'}
    if not isinstance(request,dict) or set(request)!=fields:
        raise QuantError('INVALID_OPTION_STRESS','压力请求字段缺失或未知')
    request=copy.deepcopy(request)
    if not isinstance(request['legs'],list):raise QuantError('INVALID_OPTION_STRESS','组合腿须为列表')
    legs=[Leg.from_dict(body) for body in request['legs']]
    if not legs:raise QuantError('INVALID_OPTION_STRESS','组合不能为空')
    for leg in legs:
        for value in (leg.quantity,leg.entry_price,leg.strike,leg.multiplier,leg.fee):finite_float(value)
    try:start=date.fromisoformat(request['valuation_date']);horizon=date.fromisoformat(request['horizon_date'])
    except (TypeError,ValueError) as exc:raise QuantError('INVALID_OPTION_STRESS','估值日/压力时点须为有效YYYY-MM-DD') from exc
    if horizon<start:raise QuantError('INVALID_OPTION_STRESS','压力时点不得早于估值日')
    if not isinstance(request['underlying_prices'],list) or not isinstance(request['volatility_multipliers'],list):
        raise QuantError('INVALID_OPTION_STRESS','压力价格与波动率倍率须为列表')
    prices=[decimal(v) for v in request['underlying_prices']]
    scales=[decimal(v) for v in request['volatility_multipliers']]
    for value in prices+scales:finite_float(value)
    if (not prices or not scales or any(v<=0 for v in prices+scales) or len(prices)!=len(set(prices))
            or len(scales)!=len(set(scales)) or len(prices)*len(scales)*len(legs)>1500):
        raise QuantError('INVALID_OPTION_STRESS','价格/波动率倍率须为正，单请求计算规模不能超过1500条腿')
    models=request['models']
    if not isinstance(models,dict) or set(models)!={str(i) for i,leg in enumerate(legs) if leg.kind!='STOCK'}:
        raise QuantError('INVALID_OPTION_STRESS','每条期权腿需明确模型，不能默认缺失波动率为零')
    for i,leg in enumerate(legs):
        if leg.kind=='STOCK':continue
        m=models[str(i)]
        if isinstance(m,dict) and 'discrete_dividends' in m:
            if decimal(m.get('dividend_yield',0))!=0:raise QuantError('DIVIDEND_DOUBLE_COUNT','不能同时计连续与离散分红')
            raise QuantError('UNSUPPORTED_STRESS_DIVIDENDS','组合压力尚未处理估值日至压力时点的离散分红现金路径；单腿定价可单独指定离散分红')
        if not isinstance(m,dict) or set(m)!={'style','volatility','rate','dividend_yield'}:
            raise QuantError('INVALID_OPTION_STRESS','模型需明确行权方式、波动率、利率、连续分红率')
        if (not isinstance(m['style'],str) or m['style'] not in {'EUROPEAN','AMERICAN'} or not 0<decimal(m['volatility'])<=4
                or not -1<decimal(m['rate'])<1 or not 0<=decimal(m['dividend_yield'])<1):
            raise QuantError('INVALID_OPTION_STRESS','行权方式/波动率/利率/连续分红率超出允许范围')
        if date.fromisoformat(leg.expiry)<horizon:
            raise QuantError('UNOBSERVED_EXPIRY_PATH','不假设此前到期腿的交割价；请把压力时点设为最近到期日或更早')
    rows=[]
    initial=sum((leg.quantity*leg.entry_price*leg.multiplier+leg.fee for leg in legs),decimal(0))
    for spot in prices:
        for scale in scales:
            value=decimal(0);greeks={};values=[]
            for i,leg in enumerate(legs):
                if leg.kind=='STOCK':
                    amount=leg.quantity*spot;g={name:0. for name in GREEK_UNITS};g['delta']=float(leg.quantity);basis='stock_scenario';model=None
                elif date.fromisoformat(leg.expiry)==horizon:
                    intrinsic=max(spot-leg.strike,decimal(0)) if leg.kind=='CALL' else max(leg.strike-spot,decimal(0))
                    amount=leg.quantity*leg.multiplier*intrinsic;g={name:None for name in GREEK_UNITS};basis='expiry_intrinsic_scenario';model=None
                else:
                    m=models[str(i)]
                    theoretical=price(right=leg.kind,spot=spot,strike=leg.strike,valuation_date=str(horizon),expiry=leg.expiry,
                        style=m['style'],volatility=decimal(m['volatility'])*scale,rate=m['rate'],
                        dividend_yield=m['dividend_yield'],multiplier=leg.multiplier,contracts=leg.quantity)
                    amount=decimal(theoretical['position_value']);g=theoretical['greeks'];basis='QuantLib_remaining_time_value'
                    model={key:theoretical[key] for key in ('model','engine','model_version')}
                value+=amount
                values.append({'leg_index':i,'value':str(amount),'basis':basis,'kind':leg.kind,
                    'quantity':str(leg.quantity),'multiplier':str(leg.multiplier),'greeks':g,'model':model,
                    'greeks_complete':all(g.get(name) is not None for name in GREEK_UNITS),
                    'missing_reason':'到期边界Greeks未求值，不填零' if basis=='expiry_intrinsic_scenario' else None})
            for name in GREEK_UNITS:
                greeks[name]=None if any(leg['greeks'].get(name) is None for leg in values) else sum(leg['greeks'][name] for leg in values)
                if greeks[name] is not None:finite_float(greeks[name])
            finite_float(value);finite_float(value-initial)
            rows.append({'underlying_price':str(spot),'volatility_multiplier':str(scale),'value':str(value),
                         'pnl':str(value-initial),'greeks':greeks,'leg_values':values,
                         'greeks_complete':all(leg['greeks_complete'] for leg in values)})
    if identity!=model_identity():raise QuantError('SCENARIO_MODEL_CHANGED','计算期间模型/依赖变化，请在锁定环境重新计算')
    return {'data_type':'scenario_only','request_hash':digest(request),'request':request,'points':rows,'model_identity':identity,
            'worst_sample_loss':str(max(decimal(0),-min(decimal(r['pnl']) for r in rows))),
            'maximum_loss':'NOT_INFERRED_FROM_FINITE_GRID','executable':False,'model_profile':'option-stress/1.95.1',
            'greek_units':GREEK_UNITS,'greek_scope':'指定压力时点、数量及乘数的组合金额敏感度；不是每份合约Greek或历史盈利归因',
            'limitations':['多到期组合在近月到期时保留远月QuantLib理论时间价值；模型结果不是可成交报价',
                           '有限压力网格不能证明最大亏损；未模拟离散分红、提前指派和真实多腿成交路径',
                           '到期腿为指定情景的内在价值，未自动生成行权、现金或账户事件']}
