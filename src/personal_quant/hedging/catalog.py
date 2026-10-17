"""Read-only method capabilities; a catalogue never grants account permission."""
from .spec import TOOLS


METHODS = (
    ('reduce_stock','减持股票/增加现金','H2','降低持仓金额及市场敞口','机会成本、结算前卖款不可重复使用','核验原价、单位、持仓、费用及结算'),
    ('inverse_etf','购买反向ETF','H2/H3','有资金来源的负Beta工具对照','每日重置和复利路径、跟踪误差、Beta变化','产品身份/日目标、价格路径、估计Beta和交易权限'),
    ('protective_put','同标的保护Put','H2','按股数或目标Beta制定保护','保费、保护期限、整张尾差及履约/退出风险','标准合约/原价/同步报价、Greek、股数、费用和权限'),
    ('collar','同标的Collar','H2','Put保护与有股份覆盖的短Call','上行封顶、提前指派、部分成交及保护空档','同标的股份/配对腿/报价、担保、履约和账户权限'),
    ('proxy_put','指数/行业ETF代理Put','H2','组合Beta的局部保护','基差/相关性变化，不提供股票篮子的到期价值底线','共同收益窗口、代理身份/Beta、报价、Greek及退出失败处置'),
    ('covered_call','备兑Call收益叠加','O4','A8期权模板；不是HedgeSpec对冲工具','保费不构成完整下跌保护，上行封顶和指派','同标的覆盖股份、标准合约、报价和期权权限'),
    ('put_spread','Put价差保护','HX3','条件扩展：有界多腿保护','保护下限、短腿义务、提前指派和单腿风险','对应B批次、同步多腿、整组压力/担保和完整生命周期'),
    ('rolling_protection','连续滚动保护/Collar','HX3/B3','条件扩展：退出/结算后重新建立保护','保护空档、滚动费用、失败及重启后的义务','滚动规则、成交/结算证据、窗口和新意图'),
    ('short_etf','指数/行业ETF卖空','HX1','条件扩展：负股票持仓','借券费、召回、分红补偿、保证金及无界上行风险','PIT借券/费率/召回、保证金、负持仓账本和权限'),
    ('stock_long_short','股票多空组合','HX1','条件扩展：市场/行业敞口对照','等金额不等于Beta中性，个股和借券风险','股票身份/行动、共同窗口、借券/保证金和独立账务'),
    ('pairs_trading','配对策略','HX1','条件扩展：相对价格研究','相关性/均值回复失效、个股事件及换手','PIT形成/交易期、借券、成本及样本外规则'),
    ('factor_neutral','因子中性对冲','HX1','条件扩展：多因子敞口管理','模型误差、因子漂移和残余风险','可用时点明确的因子/成分、风险模型、借券与权限'),
    ('index_futures','股指/微型股指期货','HX2','条件扩展：名义额/换月管理','保证金、盯市、基差和换月风险','具体合约/日历、逐日结算、保证金、换月及权限'),
    ('dynamic_delta','动态Delta/Gamma','HX4','条件扩展：更高频率风险管理','跳空、Gamma、流动性及频繁交易成本','足够频率的报价/Greek、模型、成本及权限；自动执行另属V2'),
    ('volatility_tail','VIX/波动率尾部工具','HX4','条件扩展：产品特定风险对照','期限结构、持有损耗、基差及非线性','具体产品/期限数据、独立模型、账户与成本'),
    ('cross_asset','跨资产/多币种对冲','HX4','条件扩展：不同风险来源对照','相关性反转、汇率、流动性及不同结算','多市场/币种、产品模型、汇率及账务/权限扩展'),
)


def catalog():
    rows=[]
    for method,name,phase,purpose,risks,inputs in METHODS:
        core=method in TOOLS
        rows.append(dict(method_id=method,name=name,phase=phase,purpose=purpose,risks=risks,
            required_inputs=inputs,hedge_spec_tool=core,
            support='CORE_ENGINEERING' if core else 'OPTION_TEMPLATE_ONLY' if method=='covered_call' else 'CONDITIONAL_NOT_IMPLEMENTED',
            research='QUALIFIED_INPUTS_REQUIRED' if core or method=='covered_call' else 'CATALOG_ONLY',
            paper='ACCOUNT_CHECKS_REQUIRED' if core or method=='covered_call' else 'UNSUPPORTED',
            real='ACCOUNT_CHECKS_REQUIRED' if core or method=='covered_call' else 'UNSUPPORTED',executable=False))
    return dict(schema_version=1,status='CATALOG',methods=rows,executable=False,
        meaning='工程能力/条件目录，不是账户资格、具体交易建议或真实历史/自然前向验证')
