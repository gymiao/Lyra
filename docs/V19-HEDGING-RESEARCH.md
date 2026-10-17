# LyraX v1.9：股票组合对冲调研

日期：2026-10-11（Asia/Shanghai）。范围：股票及股票ETF组合的主要对冲方法，默认美股/USD。本文是技术选型和范围依据，不是个人投资建议；实施安排见[股票对冲计划](V19-HEDGING-PLAN.md)。资料公开可读不等于行情、指数、因子或借券数据可免费商用。本次只完成调研和规划，未新增运行能力。

R2.1：[计划复核](V19-HEDGING-REVIEW.md)补充成熟引擎适配、筹资后敞口、撤保护风险及执行时点等10项缺口；实现以修订后的H计划为准，本文方法目录保持原研究范围。

## 1. 结论与当前项目的关系

应把“对冲”作为附加于已有持仓/策略的风险管理层，先计算风险敞口，再选择工具和数量，并将它与基础调仓放入同一个资金/股份检查事务。仅在策略目录加入一个Put名称，不能解决组合对冲比例、成本、交割和退出问题。

当前源码已有保护Put、Collar及单独Long Put的情景、选约、合成研究与开仓演示；统一账本可处理乘数、担保和生命周期事实。尚缺账户风险敞口报告、跨标的对冲比例、对冲前后统一比较，以及完整退出/日常任务。ETF权重策略仍只做多；负股票持仓被视为异常，不能直接用负权重启用股票卖空。对应文件：`strategies/templates.py`、`options/plans.py`、`options/pricing.py`、`options/management.py`、`portfolio/ledger.py`。

## 2. 方法目录与适用边界

| 方法 | 对冲目标/结构 | 主要成本与失败方式 | 纳入方式 |
|---|---|---|---|
| 减仓持现金、趋势降仓、目标波动率降仓 | 直接减少股票风险；现金是比较基线 | 交易成本、错过反弹、跳空；不能保证止损成交价 | 首批风险预算及基线；复用现有只做多策略，不包装成衍生品保护 |
| 同标的保护Put | 已有股票/ETF + 买入同标的Put，在合约条件内保护对应股数 | 权利金、时间价值、到期空档、交割能力、调整条款 | 首批，复用A组保护Put [S1] |
| 同标的Collar | 持股 + 买Put + 卖覆盖Call | 放弃部分上涨、提前指派、股份占用；零净权利金也有价差与费用 | 首批，复用A组Collar [S2] |
| 指数/行业ETF Put代理对冲 | 用指数或行业ETF的负Delta抵消股票篮子的部分市场敞口 | Beta漂移、行业/个股残余、IV与期限、跨标的交割；没有组合确定损失底线 | 首批跨标的研究与受门禁计划，复用Long Put；比例算法是本项目设计 |
| Put价差保护 | 买高执行价Put、卖低执行价Put降低净保费 | 保护只在一定跌幅区间内增加；低于短Put执行价后组合仍可继续亏损，短腿另有指派义务 | 与期权A组熊Put价差联动，列条件覆盖层，不能把价差有限亏损当股票组合有限亏损 |
| 市场Beta对冲 | 多股票篮子 + 空指数ETF/期货，将市场Beta降到目标 | 借券/保证金/基差/估计误差；净名义为零不等于风险中性 | 必须研究公式/情景；股票空头与期货账户接入分别列条件扩展 [S3][S4] |
| 行业中性/风格因子中性 | 对行业、规模、价值等敞口加约束或建立相反敞口 | 因子重叠、估计不稳定、分类变化、数据许可/时点 | 目录与风险报告接口；多因子优化和交易扩展待独立数据验证 [S7] |
| 配对/统计套利 | 相对低估一腿做多、另一腿做空，控制共同因素 | 关系破裂、公司事件、做空成本、样本选择偏差；等金额不保证Beta中性 | 条件研究批次，独立形成期/交易期，不承诺无风险套利 [S6] |
| 反向ETF | 买入反向产品形成负市场敞口 | 重置与复利路径、跟踪偏差、费用；买入正数量不代表无衍生品风险 | 首批只做显式选择的-1倍日目标产品研究；逐日监测，不作为长期固定比例替代品 [S5] |
| 股指期货 | 卖出对应期限指数期货，调整市场名义敞口 | 每日盯市、保证金追缴、合约换月、期现基差、最后结算 | 条件扩展，使用成熟LEAN适配并新增账务契约，不能套股票现金账本 [S3][S9] |
| 动态Delta对冲/波动率策略 | 持续调整股票或衍生品抵消局部Delta | Gamma/跳跃风险、交易频率和成本、模型风险；日线不足以证明盘中效果 | 目录及后续独立扩展，不列本版实时执行 |
| 尾部保护/VIX工具 | 用凸性或波动率产品覆盖部分极端行情 | 长期持有成本、期限结构、保护错配；VIX指数本身不是可买证券 | Put尾部情景可复用；VIX期货/期权/ETP接入列条件扩展 [S8] |
| 债券/黄金分散配置 | 改变组合风险来源 | 相关性可能反转，股票下跌时也可能一起跌 | 保留为分散配置对照，不标成确定对冲或保证底线 |

备兑Call单独只提供有限权利金缓冲；现金担保Put本身承担股票下行相关风险。二者不能在看板上仅因包含“卖期权”就标为股票下跌保护。以上是组合结构分析，实施须对整体持仓作情景核对。

## 3. 会影响代码的关键区别

### 风险估计与交易事实

市场Beta描述历史样本下的线性联动，不是保证。采用截至决策时点可用的相同日历收益、明确窗口及样本量；未来数据、未来成分股、事后修订因子不能进入既有结果。当前持仓的风险投影不等于该持仓过去真实持有的收益。

多空等金额只约束净资金敞口；Beta中性约束市场敏感度；行业/风格中性需要额外因子。建议报告分别展示gross/net金额、Beta金额、行业集中度及残余风险，不能只显示一个“对冲率”。[S7]

保护股数、到期支付与当前Delta对冲是不同目标。一张标准Put覆盖100股交割单位，并不意味着任意时刻其Delta都是-1；不能为了局部Delta归零，自动买到超过实际可交割股份的数量。跨标的Put不能自动交割基础股票篮子。[S1]

### 工具与资金

卖空需要借券能力、借券成本、分红补偿、召回/强制回补等事实。引擎支持负持仓并不代表数据或账户支持；官方LEAN文档也单独要求模型化借券可得性和费用。[S4][S10]

期货保证金是履约资源，不是完整合约市值，也不是最大损失；每日盯市应与最终结算去重。连续期货价格用于分析，真实计划必须映射当时可交易的具体合约。[S3][S9]

反向产品必须按实际每日价格路径处理，不能将一个月指数收益直接乘-1。合成反向日收益只能做标明假设的算例，不能作为真实基金历史。产品目标、费用、拆并股及可用交易范围需按具体产品核验。[S5]

### 与当前系统最相关的两个保护缺口

1. 持有股票篮子，并不构成卖SPY Call的股份覆盖；相关性或Beta不能替代确切交割标的。首批代理对冲只买Put，跨标的Collar卖Call保持阻断。
2. 买入SPY Put对冲其他股票时，价内到期可能要求交付SPY股份。首批必须具备到期前退出规则、失联/停牌/缺报价分支和实际凭据处理；不能自动制造SPY空头，也不能宣称总能及时平仓。

## 4. 官方资料核对中的算术复核

CME教育文支持用组合价值、Beta及合约名义额确定指数期货数量，但该页面例子的“加权Beta”按股数加权，且方差/波动率比文字容易造成量纲误读。项目不能照抄示例算式：应使用市值权重，或在统一收益样本上以 `Cov(r_portfolio, r_hedge) / Var(r_hedge)` 估计金额对冲比例；二者对应的基准和分母需明确。这是本次对原页面的核对结论，独立反例列入实施计划，不是另一个模型的背书。[S3]

选择数据源时仍需核验原始价格、退市/历史成分、公司行动、报价和许可。French因子库可用于研究参考，当前下载的历史因子不能自动冒充当年的可获取版本；MSCI页面可作为风险建模参考，但不意味着已取得其商业模型或数据权限。[S7][S11]

## 5. 一手资料与访问记录

以下链接于2026-10-11检索/阅读；来源中的示例价格、费率和历史收益不进入LyraX默认参数。

| 编号 | 来源 | 本次用途 |
|---|---|---|
| S1 | [OIC：Protective Put](https://prd-web.optionseducation.org/strategies/all-strategies/protective-put-married-put)；[Fidelity：Protective Put](https://www.fidelity.com/learning-center/investment-products/options/options-strategy-guide/protective-put) | 股份保护、Delta和交割边界；OIC页面检索可读、直接打开曾失败，Fidelity补充核对 |
| S2 | [OIC：Collar](https://prd-web.optionseducation.org/strategies/all-strategies/collar-protective-collar) | 覆盖、保护与上行封顶 |
| S3 | [CME：Hedging with E-mini S&P 500 Futures](https://www.cmegroup.com/education/whitepapers/hedging-with-e-mini-sp-500-future) | 期货对冲、保证金/盯市及Beta示例；算术需按第4节独立复核 |
| S4 | [SEC：Key Points About Regulation SHO](https://www.sec.gov/investor/pubs/regsho.htm) | 卖空借券和分红补偿等机制；不是完整法律合规审查 |
| S5 | [FINRA：Leveraged and Inverse ETPs](https://www.finra.org/investors/insights/lowdown-leveraged-and-inverse-exchange-traded-products) | 每日重置、复利路径和产品差异 |
| S6 | [Gatev等原始论文，NBER W7032](https://www.nber.org/papers/w7032) | 配对研究形成期/交易期思路；不使用论文历史收益作为策略承诺 |
| S7 | [MSCI：Factor Investing](https://www.msci.com/data-and-analytics/factor-investing)；[MSCI：Factor Models at 50](https://www.msci.com/research-and-insights/blog-post/factor-models-at-50-innovation-that-changed-investing) | 因子及个股风险分解、因子敞口对冲 |
| S8 | [Cboe：Volatility Trading](https://www.cboe.com/tradable-products/volatility-trading/) | VIX工具的期限与持有边界 |
| S9 | [LEAN官方：Futures Handling Data](https://www.quantconnect.com/docs/v2/writing-algorithms/securities/asset-classes/futures/handling-data) | 连续序列、具体合约、映射/换月 |
| S10 | [LEAN官方：US Equity Shorting](https://www.quantconnect.com/docs/v2/writing-algorithms/securities/asset-classes/us-equity/shorting) | 借券可得性、借券费用及负持仓模型；未由此证明本项目接入 |
| S11 | [Kenneth French Data Library](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html) | 研究因子数据及版本约束 |

检索采用官方/研究机构页面和agent-reach技能的通用网页Jina读取路径，CME/SEC正文成功读取。初始OIC旧路径返回404，未据此推断资料不存在，改用检索定位的页面及另一机构资料。当前shell没有agent-reach/mcporter命令；版本检查返回command not found，没有安装工具或改用户环境。MCP历史搜索没有相关命中，本次以仓库和上述资料为依据。
