# 配置说明

配置为 UTF-8 TOML、schema_version=1。CLI 默认读取当前工作目录的 configs/demo.toml；用全局参数 `--config` 显式选另一个文件。不会自动合并 local 文件或环境变量中的投资参数。最终解析值与哈希随计划、信号和研究清单保存。未知键、无效日期、布尔资金/风险参数、非有限数值会拒绝。

## 研究与资金

| 字段 | 含义与约束 |
|---|---|
| environment / runtime_dir | demo、paper 或 real，目录必须分别为 runtime/demo、runtime/paper、runtime/real；相对当前工作目录 |
| market / currency | 当前只支持 XNYS / USD |
| symbols / weights | 标的一一对应；非负权重，总和不超过1；不自动归一化，余额留现金 |
| active_strategy | fixed 或 trend；同一账户只启用一个策略 |
| lookback | 至少2个完整交易日，演示126；固定策略也使用共同预热窗口 |
| research_capital | 正的研究初始资金，只用于bt，不写真实账本 |
| demo_deposit | demo入金需显式正值；独立于research_capital，仅测试资金 |
| development_start/end | 成对填写，有序且完全早于evaluation_start；不自动搜索参数 |
| evaluation_start/end | YYYY-MM-DD，起点早于终点；研究报告列共同观察区间 |
| volatility_annual_factor | 正整数，演示252；CAGR仍按实际自然日观察期 |

真实账户资金仅从actual账单中的入出金产生。demo和真实模板都不代表用户的资金或风险偏好。更换策略/标的从下个合格月末生效；已经冻结的意图不因修改配置重新选规则。

## 执行前必填条件

下表15个字段必须明确；真实配置另须显式填写active_strategy。缺项可做研究和账单记录，不能生成可执行计划。0费用/0容差也需明确填写。

| 字段 | 单位 / 作用 |
|---|---|
| commission_bps / slippage_bps | 有限非负数，1bp=0.01%；预计佣金/滑点，研究滑点用等价费用扣减 |
| fixed_fee | 每笔固定费用，USD、非负；零数量不收固定费 |
| max_weight | 单标的目标及预计持仓上限，(0,1] |
| cash_buffer | 权益比例，[0,1)，不能作为购买力使用 |
| lot_size | 正的下单单位；建议向下取整，真实账本不截断零碎持仓 |
| execution_window_sessions | 正整数，月度意图窗口；不变成每日追踪权重 |
| settlement_lag_sessions | 非负整数，模拟结算假设；实际账单需settlement_at凭据 |
| publication_delay_minutes | 非负整数，超过实际收盘后等待完整日线的分钟数 |
| reference_deviation | 允许成交价相对计划参考价偏离比例，非负 |
| price_jump_threshold | 正比例，演示0.25；已知行动按明确单位解释，未知跳变阻断 |
| reconciliation_max_days | 正整数，对账基线期限 |
| reconciliation_cash_tolerance | 非负USD金额容差 |
| reconciliation_quantity_tolerance | 非负份额容差 |
| reconciliation_equity_tolerance | 非负USD权益容差 |

配置阈值不保证最大回撤。实际成交费用按账单金额入账，不用估计值替代。资金以Decimal文本保留原凭据精度，建议数量按lot_size向下取整；研究适配bt时使用浮点及可分割虚拟份额，两种份额不可混用。

## 数据与错误

download_attempts为1至5次，演示3；download_timeout为正整数秒，演示20。增量回看14个自然日；发现重叠复权修订或新行动会刷新历史并保留旧版本。字段契约不完整或日线尚未发布会立即返回，不重复下载。本适配器没有账户密钥或付费服务认证功能。

非交易日、缺价、尚未发布、非正成交量及未知证券单位不能产生可成交价格；原始零量行保留作诊断。Yahoo价格只用于当前已验证的研究口径，实际证券数量需核验原价CSV。参考 [CSV说明](CSV.md)、[运行维护](OPERATIONS.md) 和 [README](../README.md)。

用户配置保存为configs/local*.toml并受Git忽略。密钥与原始真实账单独立保管，不能放入示例或报告提交。
