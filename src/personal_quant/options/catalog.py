"""Capability statuses are evidence based, independently of strategy names."""
FAMILIES = [
    ('single','单腿方向',['long_call','long_put','short_call','short_put']),
    ('covered','覆盖与保护',['protective_put','covered_call','cash_secured_put','collar','covered_strangle']),
    ('vertical','垂直价差',['bull_call_debit_spread','bear_put_debit_spread','bull_put_credit_spread','bear_call_credit_spread']),
    ('straddle','跨式与宽跨式',['long_straddle','long_strangle','short_straddle','short_strangle']),
    ('calendar','日历与对角',['calendar','diagonal','poor_mans_covered_call','double_calendar','reverse_calendar']),
    ('butterfly','蝶式',['butterfly','iron_butterfly','broken_wing_butterfly']),
    ('condor','鹰式',['condor','iron_condor']),
    ('ratio','比例与反向比例',['ratio_spread','backspread','stock_repair']),
    ('synthetic','合成与转换',['synthetic_stock','conversion','reversal','box']),
    ('relative','相对定价',['put_call_parity','volatility_spread','dispersion']),
    ('dynamic','动态规则',['wheel','rolling_call','rolling_put','rolling_collar','delta_hedging']),
    ('volatility','波动率与尾部',['gamma_scalping','tail_hedge','variance_replication','0dte']),
    ('product','产品期限边界',['spx_cash_settlement','vix_options','futures_options','fx_options']),
    ('exotic','奇异与路径依赖',['barrier','asian','lookback','digital'])]
A8 = {'protective_put','covered_call','cash_secured_put','collar','long_call','long_put','bull_call_debit_spread','bear_put_debit_spread'}
# Research extension membership never grants the A8 lifecycle qualification.
FOUR_LEG = {'iron_condor','iron_butterfly'}
FUNDED_CALL_PROTECTION = {'bull_call_debit_spread','bear_call_credit_spread'} | FOUR_LEG
MONTHLY_RESEARCH = A8 | {'long_straddle','long_strangle','bull_put_credit_spread','bear_call_credit_spread'} | FOUR_LEG


def catalog():
    return [{'family_id':key,'name':name,'strategies':[{'template_id':strategy,'catalog':'AVAILABLE',
             'scenario':'TEMPLATE' if strategy in MONTHLY_RESEARCH else 'STANDARD_LEGS' if key not in {'product','exotic'} else 'CATALOG_ONLY',
             'historical':'NOT_VALIDATED','paper':'NOT_VALIDATED','real':'NOT_VALIDATED',
             'priority':'A' if strategy in A8 else 'CONDITIONAL'} for strategy in strategies]} for key,name,strategies in FAMILIES]


def template(identifier, *, spot=100, multiplier=100, expiry='2026-12-18', premium=2, second_premium=1, fee=0):
    from ..common import QuantError, decimal
    if identifier not in MONTHLY_RESEARCH: raise QuantError('UNKNOWN_OPTION_TEMPLATE','情景模板不包含此规则；可输入标准腿研究')
    spot,multiplier,premium,second_premium,fee=map(decimal,(spot,multiplier,premium,second_premium,fee))
    if spot<=0 or multiplier<=0 or premium<0 or second_premium<0 or fee<0:raise QuantError('INVALID_SCENARIO','价格、乘数或费用无效')
    def option(right,strike,quantity=1,price=premium):
        return {'kind':right,'quantity':str(quantity),'entry_price':str(price),'strike':str(strike),
                'multiplier':str(multiplier),'expiry':expiry,'fee':str(fee)}
    stock={'kind':'STOCK','quantity':str(multiplier),'entry_price':str(spot)}
    put,call=option('PUT',spot*decimal('.95')),option('CALL',spot*decimal('1.05'),-1)
    return {'iron_condor':[option('PUT',spot*decimal('.90'),1,second_premium),option('CALL',spot*decimal('1.10'),1,second_premium),option('PUT',spot*decimal('.95'),-1),option('CALL',spot*decimal('1.05'),-1)],
            'iron_butterfly':[option('PUT',spot*decimal('.95'),1,second_premium),option('CALL',spot*decimal('1.05'),1,second_premium),option('PUT',spot,-1),option('CALL',spot,-1)],
            'long_call':[option('CALL',spot)],'long_put':[option('PUT',spot)],
            'protective_put':[stock,put],'covered_call':[stock,call],
            'cash_secured_put':[option('PUT',spot*decimal('.95'),-1)],'collar':[stock,put,call],
            'long_straddle':[option('CALL',spot),option('PUT',spot,1,second_premium)],
            'long_strangle':[option('PUT',spot*decimal('.95')),option('CALL',spot*decimal('1.05'),1,second_premium)],
            'bull_put_credit_spread':[option('PUT',spot*decimal('.90'),1,second_premium),option('PUT',spot*decimal('.95'),-1)],
            'bear_call_credit_spread':[option('CALL',spot*decimal('1.10'),1,second_premium),option('CALL',spot*decimal('1.05'),-1)],
            'bull_call_debit_spread':[option('CALL',spot),option('CALL',spot*decimal('1.05'),-1,second_premium)],
            'bear_put_debit_spread':[option('PUT',spot),option('PUT',spot*decimal('.95'),-1,second_premium)]}[identifier]
