"""Fully funded, equal-capital theoretical controls; no quotes or account writes."""
import copy
from ..common import QuantError,decimal as D,digest,finite_float
from .stress import evaluate,GREEK_UNITS,model_identity


def compare(request):
    identity=model_identity()
    fields={'schema_version','initial_cash','stock_price','packages','put_strike','call_strike','put_premium','call_premium',
        'fee_per_contract','stock_commission_bps','maximum_premium_budget','style','volatility','rate','dividend_yield',
        'valuation_date','expiry','horizon_date','underlying_prices','volatility_multipliers'}
    if not isinstance(request,dict) or set(request)!=fields or type(request['schema_version']) is not int or request['schema_version']!=1:
        raise QuantError('INVALID_RISK_COMPARISON','同资本风险比较需完整schema1、资金/报价假设/费用/模型及压力网格')
    r=copy.deepcopy(request);n=D(r['packages']);capital=D(r['initial_cash']);spot=D(r['stock_price'])
    if n<=0 or n!=n.to_integral_value() or n>100 or capital<=0 or spot<=0:
        raise QuantError('INVALID_RISK_COMPARISON','资金/标的价格须正，包数为1至100整数，每包100股')
    values={key:D(r[key]) for key in ['put_strike','call_strike','put_premium','call_premium','fee_per_contract','stock_commission_bps','maximum_premium_budget']}
    for value in [n,capital,spot,*values.values()]:finite_float(value)
    if (any(v<0 for v in values.values()) or values['put_strike']<=0 or values['call_strike']<=values['put_strike']):
        raise QuantError('INVALID_RISK_COMPARISON','权利金/费用/预算须非负，行权价须为正且Put低于Call')
    shares=n*100;option_fee=n*values['fee_per_contract'];stock_fee=shares*spot*values['stock_commission_bps']/10000
    stock={'kind':'STOCK','quantity':str(shares),'entry_price':str(spot),'fee':str(stock_fee)}
    put={'kind':'PUT','quantity':str(n),'entry_price':str(values['put_premium']),'strike':str(values['put_strike']),
        'multiplier':'100','expiry':r['expiry'],'fee':str(option_fee)}
    call={'kind':'CALL','quantity':str(-n),'entry_price':str(values['call_premium']),'strike':str(values['call_strike']),
        'multiplier':'100','expiry':r['expiry'],'fee':str(option_fee)}
    model={key:r[key] for key in ('style','volatility','rate','dividend_yield')}
    controls={};grid=None
    for name,legs in [('protective_put',[stock,put]),('collar',[stock,put,call]),('stock',[stock])]:
        fees=stock_fee+(option_fee*(len(legs)-1));premium=sum((D(leg['quantity'])*D(leg['entry_price'])*D(leg.get('multiplier',1)) for leg in legs[1:]),D(0))
        long_budget=(n*values['put_premium']*100+option_fee*(len(legs)-1)) if len(legs)>1 else D(0)
        if long_budget>values['maximum_premium_budget']:
            raise QuantError('SCENARIO_PREMIUM_BUDGET','权利金预算不足：'+name+'；短Call收入不抵扣长期权及费用预算')
        invested=shares*spot+premium+fees;cash=capital-invested
        finite_float(invested);finite_float(cash)
        if cash<0:raise QuantError('SCENARIO_CAPITAL_INSUFFICIENT','同资本比较资金不足：'+name+'；不借款或默默减少份额')
        scenario=evaluate({'legs':legs,'models':{str(i):model for i in range(1,len(legs))},
            **{key:r[key] for key in ['valuation_date','horizon_date','underlying_prices','volatility_multipliers']}})
        for point in scenario['points']:
            equity=cash+D(point['value']);finite_float(equity);point['equity']=str(equity)
        controls[name]={**scenario,'initial_cash':str(capital),'stock_shares':str(shares),'uninvested_cash':str(cash),
            'net_option_premium':str(premium),'long_premium_budget_used':str(long_budget),'entry_fees':str(fees),
            'covered_call_shares':str(shares) if name=='collar' else '0'}
        grid=scenario['points']
    controls['cash']={'initial_cash':str(capital),'stock_shares':'0','uninvested_cash':str(capital),'entry_fees':'0',
        'covered_call_shares':'0','worst_sample_loss':'0',
        'net_option_premium':'0','long_premium_budget_used':'0','points':[{'underlying_price':p['underlying_price'],
            'volatility_multiplier':p['volatility_multiplier'],'equity':str(capital),'pnl':'0',
            'greeks':{key:0. for key in GREEK_UNITS},'greeks_complete':True,'leg_values':[]} for p in grid]}
    if identity!=model_identity():raise QuantError('SCENARIO_MODEL_CHANGED','计算期间模型/依赖变化，请在锁定环境重新计算')
    return {'schema_version':1,'data_type':'scenario_only','executable':False,'request_hash':digest(r),'request':r,'model_identity':identity,
        'controls':controls,'greek_units':GREEK_UNITS,'maximum_loss':'NOT_INFERRED_FROM_FINITE_GRID',
        'assumptions':['相同初始资本、每包100股，剩余现金利息0；理论压力而非历史回测/真实报价',
            '仅计显式建仓佣金和期权费用；期末理论估值不另扣平仓费用/税费/滑点',
            '短Call权利金同时对应负债，不作为即时利润；覆盖股数与长期权预算明确',
            '仅连续分红率定价，未模拟期间离散分红现金/实际提前指派或部分成交；不生成计划或账户事件']}
