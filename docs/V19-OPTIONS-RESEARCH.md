# LyraX v1.9：期权策略调研与目录

查阅日期：2026-10-10（Asia/Shanghai）。状态：**调研及规划，尚未开发或接入期权数据**。对应[主计划](lyraX-v1.9.md)和[期权实施计划](V19-OPTIONS-PLAN.md)。默认研究对象沿用美股ETF，首个工程样例暂定SPY；市场偏好、账户及权限尚未确认。

## 1. “所有策略”的范围

期权可以按标的、Call/Put、方向、数量、执行价、期限和动态调整规则组合，没有有限且统一的“全部策略”清单。本目录覆盖主流场内标准期权，并列出专业及场外扩展；不会把名称别名、0DTE期限或一次滚仓都计算成独立收益机制。分类参考[OIC策略目录](https://www.optionseducation.org/strategies/all-strategies-en)、[CME期权结构手册](https://www.cmegroup.com/articles/brochures-and-handbooks/25-proven-strategies.html)，以下分类及LyraX实现顺序属于本项目的工程判断。

应区分三个层次：

1. **收益结构**：例如买Call、看涨价差、铁鹰，描述持仓腿及到期现金流。
2. **交易规则**：何时入场、选哪份合约、何时平仓/滚仓；“卖Put”本身还不是可复现策略。
3. **运行系统**：报价、成本、资金占用、行权、指派和结算决定能否回测或执行。

同名“Long/Short Iron Condor”“Ratio Spread”在资料中可能指不同腿方向；系统以明确腿表为准，不能根据名称猜收益图。OIC目录个别摘要与详情不一致时，以合约定义和逐腿现金流核对，不复制摘要当规则。

目录中的“有限损失”通常指指定腿完整、持有到约定期限的理论结构；提前指派、部分成交、交割资金、平仓失败及费用可能改变账户结果。ETF期权和指数期权的行权与交割不能互换：SPY ETF期权与SPX/XSP产品的规则差异见[Cboe产品比较](https://www.cboe.com/tradable_products/product_comparison/)。

## 2. 策略目录

记号：`+`为买入/持有，`−`为卖出；C为Call、P为Put、S为标的；K为执行价，T为到期。未写期限差异时假设同标的同到期，实际乘数和交割物必须来自合约主档。

纳入级别：**A**首批历史研究/模拟目标；**B**生命周期通过后分批扩展；**C**本版目录及适用的情景分析，暂不生成可执行计划；**D**单独专业项目。全部条目当前均未实施。收益方向是结构特征，不是收益保证。

### 2.1 单腿方向结构

| 策略 | 组成与主要用途 | 风险/实现级别 |
|---|---|---|
| 买入看涨 Long Call | +C，看涨或替代部分上涨敞口 | 期权腿可能损失全部权利金；实物行权另需资金；A |
| 买入看跌 Long Put | +P，看跌；与标的组合时可用于保护 | 期权腿可能损失全部权利金；没有标的时行权可能形成空头；A |
| 裸卖看涨 Naked Call | −C，卖出上涨保险 | 标的上涨方向理论损失无上限；C |
| 非现金担保卖Put Naked Put | −P，没有足额购股资金预留 | 下跌损失很大且有融资/保证金压力；并非无限损失；C |

来源：[Long Call](https://www.optionseducation.org/strategies/all-strategies/long-call)、[Long Put](https://www.optionseducation.org/strategies/all-strategies/long-put)、[裸卖Call](https://www.optionseducation.org/strategies/all-strategies/naked-call-uncovered-call-short-call)、[裸卖Put](https://www.optionseducation.org/strategies/all-strategies/naked-put-uncovered-put-short-put)。

### 2.2 标的、现金和期权组合

| 策略 | 组成与主要用途 | 风险/实现级别 |
|---|---|---|
| 备兑Call Covered Call / Buy-Write | +S−C，以部分上涨空间换权利金；已有持仓覆盖或同时购股 | 仍承担标的大幅下跌，可能被提前交割；A |
| 保护性Put Protective / Married Put | +S+P，给持仓设置期限内的下行保护 | 权利金持续成本、保护到期及覆盖比例；A |
| 领口 Collar | +S+P(较低K)−C(较高K) | 下行保护伴随上行封顶；“零成本”只指入场净权利金，不是零风险；A |
| 现金担保Put Cash-Secured Put | −P并预留全部履约购股现金 | 被指派后承担标的风险，不是买Put对冲；A |
| 现金支持买Call Cash-Backed Call | +C及可供行权的现金资产 | 与卖Call不同，保留上涨选择权；B |
| Covered Put / Protective Call | 前者−S−P，后者−S+C | 涉及标的卖空和借券，不能误作现金担保Put；C |
| Covered Strangle / Covered Combination | +S−C−P，同时有备兑股和Put履约现金 | Put指派还会增加持股，原有股份不能重复担保Put；B |
| Stock Repair / Covered Ratio Spread | 通常+S+1较低K的C−2较高K的C | 以放弃部分反弹收益调整回本形态，不消除原有亏损；B |

来源：[备兑](https://www.optionseducation.org/strategies/all-strategies/covered-call-buy-write)、[保护Put](https://www.optionseducation.org/strategies/all-strategies/protective-put-married-put)、[Collar](https://www.optionseducation.org/strategies/all-strategies/collar-protective-collar)、[现金担保Put](https://www.optionseducation.org/strategies/all-strategies/cash-secured-put)、[现金支持Call](https://www.optionseducation.org/strategies/all-strategies/cash-backed-call-cash-secured-call)、[Covered Put](https://www.optionseducation.org/strategies/all-strategies/covered-put)、[Stock Repair](https://www.optionseducation.org/strategies/all-strategies/stock-repair)。

### 2.3 同到期垂直价差

| 策略 | 腿结构 | 风险/实现级别 |
|---|---|---|
| 牛市Call价差 / Debit Call Spread | +低K C−高K C | 方向看涨，净支出、收益封顶；A |
| 熊市Put价差 / Debit Put Spread | +高K P−低K P | 方向看跌，净支出、收益封顶；A |
| 牛市Put价差 / Credit Put Spread | −高K P+低K P | 收权利金，承担下跌方向损失；B |
| 熊市Call价差 / Credit Call Spread | −低K C+高K C | 收权利金，承担上涨方向损失；B |

四种同到期等量结构有可计算的理论边界，但实物交割的单腿提前指派不能仅靠“价差最大损失”覆盖资金需求。来源：[牛Call](https://www.optionseducation.org/strategies/all-strategies/bull-call-spread-debit-call-spread)、[熊Put](https://www.optionseducation.org/strategies/all-strategies/bear-put-spread)、[牛Put](https://www.optionseducation.org/strategies/all-strategies/bull-put-spread-credit-put-spread)、[熊Call](https://www.optionseducation.org/strategies/all-strategies/bear-call-spread-credit-call-spread)。

### 2.4 跨式、宽跨式及偏向变体

| 策略 | 组成/意图 | 风险/实现级别 |
|---|---|---|
| 买跨式 Long Straddle | 同K同T，+C+P；希望出现足够大的变化 | 两份权利金、时间耗损及IV下降；B |
| 买宽跨式 Long Strangle | +较低K P+较高K C | 更依赖足够大的价格移动；B |
| 卖跨式 Short Straddle | −同K C−P | 承担双向尾部，上涨侧无限损失；C |
| 卖宽跨式 Short Strangle | −低K P−高K C | 区间收取权利金，仍有裸卖尾部；C |
| Strip / Strap | 买入Put较多 / Call较多的不对称跨式，例如1C+2P或2C+1P | 方向与波动率混合敞口；以腿表定义的B级变体 |
| Guts及反向结构 | 执行价交错的价内Call/Put组合 | 不能按普通宽跨式执行价顺序套公式；B情景、执行另验 |

主要结构来源：[买跨式](https://www.optionseducation.org/strategies/all-strategies/long-straddle)、[买宽跨式](https://www.optionseducation.org/strategies/all-strategies/long-strangle-long-combination)、[卖跨式](https://www.optionseducation.org/strategies/all-strategies/short-straddle)、[卖宽跨式](https://www.optionseducation.org/strategies/all-strategies/short-strangle)。最后两行作为通用腿组合的明确变体，不引入独立收益计算器。

### 2.5 日历与对角价差

| 策略族 | 组成/意图 | 风险/实现级别 |
|---|---|---|
| Call/Put正向日历 | 同K，买远月、卖近月 | 期限结构、近月衰减和标的路径共同作用；B |
| Call/Put反向日历 | 买近月、卖远月 | 近月到期后可能留下无保护远月空头；C |
| Call/Put对角及反向对角 | 不同K、不同T | 前月到期时远月仍有时间价值，不能用单个到期收益图表示；B/C按腿分类 |
| PMCC / Poor Man’s Covered Call | 常见为远月较深价内多Call+近月空Call | 属对角价差，不等于真实持股备兑；B，必须检查指派资金 |
| 双日历 / 双对角 | Call侧与Put侧期限结构组合 | 跨期限、两侧指派、IV曲面影响；B后批 |

来源：[正向日历](https://www.optionseducation.org/strategies/all-strategies/long-call-calendar-spread-call-horizontal)、[反向日历](https://www.optionseducation.org/strategies/all-strategies/short-call-calendar-spread-short-call-time-spread)、[Fidelity/Cboe对角价差](https://www.fidelity.com/learning-center/investment-products/options/options-strategy-guide/long-diagonal-spread-calls)、[OIC策略FAQ](https://www.optionseducation.org/referencelibrary/faq/strategies)。

### 2.6 蝶式及非对称翅膀

| 策略族 | 腿结构/意图 | 风险/实现级别 |
|---|---|---|
| Call/Put买蝶式 | 同类期权，+1低K−2中K+1高K，标准形为等距 | 期末靠近中间K有利；B |
| Call/Put卖蝶式 | 上述腿反向 | 更希望离开中间区间；B |
| 信用铁蝶 / Debit反向铁蝶 | 卖同K跨式并买两侧保护 / 全部反向 | 与普通蝶式买卖命名易混，展示净支出及腿方向；B |
| Broken-Wing Butterfly | 两翼宽度不同的蝶式 | 单侧风险边界改变，不能套等宽最大损失；B |
| Christmas Tree及比例蝶式 | 非等距或数量变化的翼形组合 | 逐腿检查尾部斜率，不能按名称一律认定有界；B/C |

来源：[Call蝶式](https://www.optionseducation.org/strategies/all-strategies/long-call-butterfly)、[铁蝶](https://www.optionseducation.org/strategies/all-strategies/short-iron-butterfly)、[OIC非对称结构课程](https://www.optionseducation.org/videolibrary/complex-spreads-ii-long-condors-and-broken-wing-bu)。

### 2.7 鹰式和铁鹰

| 策略族 | 腿结构/意图 | 风险/实现级别 |
|---|---|---|
| Call/Put买Condor | 四个递增K，同类期权+1−1−1+1 | 中间区间盈利，较蝶式平台更宽；B |
| Call/Put卖Condor | 上述腿反向 | 希望离开区间；B |
| 信用Iron Condor | 牛Put信用价差+熊Call信用价差 | 区间收权利金，需两翼、资金和指派检查；B |
| Debit反向Iron Condor | 信用铁鹰全部反向 | 双向大幅移动结构，收益仍受翼宽限制；B |

来源：[Call Condor](https://www.optionseducation.org/strategies/all-strategies/long-call-condor)、[OIC Iron Condor](https://www.optionseducation.org/strategies/all-strategies/short-condor)、[Fidelity铁鹰](https://www.fidelity.com/viewpoints/active-investor/iron-condor-strategy)。

### 2.8 比例与三腿混合结构

| 策略族 | 组成/意图 | 风险/实现级别 |
|---|---|---|
| Call/Put Front Ratio | 买少卖多，例如1:2 | 可能残留裸卖尾部；Call可无限损失；C |
| Call/Put Backspread | 卖少买多，例如1:2 | 希望大幅单向移动，中间价位存在损失区；B |
| Call/Put Ladder | 阶梯执行价、不同买卖数量 | 名称不能决定是否存在无限尾部；C或验证后的B |
| Jade Lizard | 卖Put+信用Call价差 | 足够净收入可覆盖上涨侧翼宽，但下跌风险仍大；B后批、Put需全额现金 |
| Reverse Jade / Twisted Sister | 卖Call+信用Put价差 | 可能保留无限上涨风险；C |
| Seagull、Double Bull/Bear Spread | 方向价差与第三腿或相反期权侧价差组合 | 零成本或较低成本不等于有保护，按实际腿判定；B/C |

来源：[买多比例](https://www.optionseducation.org/strategies/all-strategies/long-ratio-call-spread)、[卖多比例](https://www.optionseducation.org/strategies/all-strategies/short-ratio-call-spread)、[Jade Lizard](https://www.tastylive.com/concepts-strategies/jade-lizard)、[Twisted Sister](https://www.tastylive.com/definitions/twisted-sister)。名称较少统一的变体只收录腿定义，正式模板须单独算例验收。

### 2.9 合成头寸

| 策略族 | 组成/用途 | 风险/实现级别 |
|---|---|---|
| Synthetic Long / Short Stock | 同K同T的+C−P / −C+P | 经济敞口接近远期，不等于无需资金的股票；C |
| Synthetic Call / Put | 标的和期权结合，再考虑现金/融资腿 | 等价关系依赖利息、分红和行权条件；C |
| Risk Reversal / Combo | 常见看涨为买Call卖Put，看跌相反；不同K时改变形态 | 与同K合成头寸区分，可能有裸露风险；C |

来源：[合成多头](https://www.optionseducation.org/strategies/all-strategies/synthetic-long-stock)、[Put/Call平价](https://www.optionseducation.org/advancedconcepts/put-call-parity)。标准欧式平价不能不加条件用于美式、离散分红及有交易摩擦的套利结论。

### 2.10 相对定价与融资结构

| 策略族 | 机制 | 纳入方式 |
|---|---|---|
| Conversion / Reversal | 标的与同K Put/Call形成平价组合 | 融资、借券、分红、执行成本及指派均需处理；D |
| Long / Short Box | 看涨与看跌价差组合为约定到期金额 | 不能把美式提前指派忽略后宣称无风险利率交易；D |
| Jelly Roll | 不同期限的合成多空组合 | 期限融资/分红相对定价；D |
| Dividend Capture / Exercise Arbitrage | 围绕除息和提前行权安排持仓 | 分红不是免费收益，资格、税费、时间价值影响结果；D |

来源：[OIC平价](https://www.optionseducation.org/advancedconcepts/put-call-parity)、[OIC Box研究](https://www.optionseducation.org/getmedia/1dcd759e-d52b-4323-8095-c3a343cab824/Box-Spreads-Paper_2025.pdf)、[CME结构手册](https://www.cmegroup.com/articles/brochures-and-handbooks/25-proven-strategies.html)。

### 2.11 动态持仓规则

| 规则 | 定义 | 纳入方式 |
|---|---|---|
| Wheel | 现金担保Put→实际指派持股→备兑Call→交割后回现金 | 是状态转换策略，不是每月凭空卖两种期权；B |
| 滚动备兑 / Buy-Write | 周期性平旧Call、开新Call并检查覆盖 | 原腿平仓和新腿建仓分开核算；B |
| 滚动Put / Put Spread Collar | 持续购买保护，或以价差/卖Call调整成本 | 保护空档、预算耗用、尾部截断需展示；B |
| 规则化滚仓 / Laddered Expiries | 按到期、风险阈值及冻结规则调整期限 | 滚仓不抹去已实现亏损，增加交易与指派路径；B后批 |
| 趋势/波动率条件叠加 | 将已有月度规则作为是否建立某结构的条件 | 信号与选合约时点分别冻结，不按结果选规则；B |

来源：[OIC Wheel](https://www.optionseducation.org/videolibrary/the-wheel-strategy-explained)。其余为基于静态结构的项目规则族；具体触发、平仓、滚仓及预算需形成版本，不直接照名称运行。

### 2.12 波动率、偏斜及相关性

| 策略族 | 研究对象 | 纳入方式 |
|---|---|---|
| Delta-Hedged Long/Short Vol | 期权与动态标的对冲，比较隐含/实现波动 | 交易摩擦、跳空和离散对冲；C研究、D执行 |
| Gamma Scalping | 持有Gamma并持续调整Delta | 高频率数据/成交与Theta成本，日线系统不足；D |
| Volatility Risk Premium | 系统性卖波动及尾部风险管理 | 历史权利金收入不是无风险收益；C |
| Term Structure / Skew Relative Value | 期限、执行价两维的IV曲面相对定价 | 需要同步链、同一模型口径与期限风险；B情景、D完整执行 |
| Dispersion / Correlation | 指数期权与成分股期权篮子 | PIT成分、指数/个股多腿、公司行动及大量数据；D |
| Earnings/Event Volatility | 财报或事件前后买/卖波动、期限结构 | 事件时间须PIT；ETF缺单一公司财报事件；D |

来源：[Schwab Gamma Scalping](https://www.schwab.com/learn/story/gamma-scalping-primer)、[Cboe相关性资料](https://cdn.cboe.com/resources/indices/documents/Cboe_USO_ImpliedCorrelation_0421_v2.0.2.pdf)、[Cboe Dispersion方法](https://cdn.cboe.com/resources/indices/documents/methodology-the-dispersion-index.pdf)。本项目不会把日频拟合结果标成已验证的盘中对冲效果。

### 2.13 期限及产品包装

0DTE、周度、月度、LEAPS描述到期时间，不是独立的盈利结构；可以搭配Call、价差或铁鹰。0DTE接近平值时对标的变化非常敏感，[Cboe资料](https://www.cboe.com/tradable-products/0dte)说明其日内管理属性，本版日线执行不支持。

ETF、个股、指数、期货、VIX和外汇期权是不同产品族。期货期权可能行权后产生期货头寸；不能照搬ETF的购股现金模型。VIX现货也不能当普通可持有标的套现货期权公式。此类产品先列目录，具体产品规则另验；[CME期货期权](https://www.cmegroup.com/trading/equity-index/options-on-futures.html.html)、[Cboe产品比较](https://www.cboe.com/tradable_products/product_comparison/)。

### 2.14 奇异与结构化产品

障碍/敲入敲出、亚式平均价、回望、数字/二元、复合、多资产篮子、自动赎回等包含不同现金流或路径条件。它们不是给标准Call/Put多加几个执行价即可模拟；需条款、路径行情、定价和交易对手/结算适配。列D级范围说明，不承诺本版交易或精确估值。QuantLib可作为相应定价能力的评估对象，不能因此宣称系统已支持这些合约。

## 3. 历史数据调研

| 路径 | 官方文档确认的能力 | 本项目尚缺的证据 |
|---|---|---|
| Cboe DataShop Option EOD Summary | NBBO及数量，15:45和产品相关EOD快照，可选IV/Greeks | 使用权限、购买/样本、目标标的覆盖、历史合约及调整完整性、实际下载/适配 |
| ORATS Historical Data API | 历史日终合约字段及分析数据，需token | 授权、费用、字段定义、报价/模型值区分、实际样本及版本修订处理 |
| 券商行情/API | 适合在权限允许时取得当前链和账户记录 | 不可预设能取得完整过期合约历史；IBKR公开说明存在过期期权历史限制 |
| 标准CSV/Parquet | 可接收用户有权使用的链、主档和事件 | 单有CSV不等于数据真实，需来源和时间证据 |
| 合成链/理论定价 | 可验证收益图、时点、资金和生命周期算例 | 必须标scenario_only，不是历史市场回报 |

来源：[Cboe EOD产品](https://datashop.cboe.com/option-eod-summary)、[半日及字段FAQ](https://datashop.cboe.com/faqs)、[ORATS历史API](https://orats.com/docs/historical-data-api)、[IBKR行情限制说明](https://www.interactivebrokers.com/campus/trading-lessons/requesting-market-data/)。本轮只核对公开文档，没有获取付费样本、API token或验证任何期权历史数据源成功接入。

## 4. 开源能力与项目适配结论

| 组件 | 已核对定位 | LyraX采用方式 |
|---|---|---|
| bt/ffn | 现有组合权重研究与指标链路 | 保留ETF研究；当前适配层没有期权乘数、行权或指派，不能把期权价格列塞入即称支持 |
| QuantLib | 量化定价库，3-Clause BSD许可 | 评估情景价值、IV和Greeks；不是行情、成交或回测引擎；美式/分红模型需专门选择 |
| LEAN | Apache-2.0开源多资产引擎，有期权策略及行权/指派/成交扩展接口 | O0验证后作为期权及ETF混合研究的候选唯一生命周期引擎；通过适配接项目，不改第三方核心 |

依据：[bt官方文档](https://pmorissette.github.io/bt/)、[QuantLib](https://www.quantlib.org/index.shtml)、[许可证](https://www.quantlib.org/license.shtml)、[LEAN源码与许可](https://github.com/QuantConnect/Lean)、[期权策略接口](https://www.quantconnect.com/docs/v2/writing-algorithms/trading-and-orders/option-strategies)、[指派模型](https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/options-models/assignment)、[成交模型](https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/trade-fills/supported-models/immediate-model)。框架默认模型是模拟假设，需要核对，不能视为实际券商规则。

LEAN引擎开源与商业平台/工具条件分别评估。官方[CLI本地回测文档](https://www.quantconnect.com/docs/v2/lean-cli/backtesting/deployment)目前说明需要付费组织，并采用容器运行；因此O0必须验证直接运行开源引擎的安装/数据路径，不能把CLI、Docker、数据订阅或免费能力当作既成条件。本轮未安装LEAN/QuantLib，依赖版本在实际验证后再锁。

这会扩展原“bt唯一主框架”的范围：已有ETF业务仍用bt；新期权混合组合在一次实验内使用一个经过验证的引擎，包括同条件ETF基准。禁止拼接两个引擎各自的现金和收益，禁止为方便比较重复建设整套ETF功能。具体边界见[期权计划](V19-OPTIONS-PLAN.md)。

## 5. 结论与调研限制

首批A共8个模板目标：Long Call、Long Put、Protective Put、Covered Call、Cash-Secured Put、Collar、Bull Call Debit Spread、Bear Put Debit Spread。顺序按可验证的工程链路设计，不是对用户账户的投资建议。B按数据、生命周期、资金及组合执行验证逐批开启；C/D纳入目录并清楚标未支持。

本轮使用agent-reach规定的Jina网页读取成功取得OIC目录，结合内置网页工具核对官方页面；环境没有agent-reach/mcporter/gh命令，体检及更新检查无法运行，未安装工具或修改环境。部分页面索引/视频摘要不足以证明细节，正式实现仍需核对腿定义与独立算例。

没有声称穷举全部组合、证明策略盈利、完成历史数据接入、验证券商权限或启动自动交易。剩余具体输入为市场/产品、券商权限、资料来源/授权、费用/交割规则和用户显式风险预算；工程配置示例不能代替这些信息。
