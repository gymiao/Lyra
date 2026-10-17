# 标准 CSV 与资金口径

UTF-8，可带 BOM；时间为带时区 ISO 8601。资金/数量按 Decimal 解析，拒绝 NaN/Inf、负的成交数量或价格。模板只有表头，不代表有效账单。

## 事件模板

`templates/events.csv` 可混合资金、成交和公司行动；至少需要 event_id、kind、effective_at、source、evidence_type。account_id/currency 可显式填写，导入时与所选账户核对；真实环境不能接收 test/simulated。

| kind | 必填业务内容 | 口径 |
|---|---|---|
| DEPOSIT / WITHDRAWAL | amount | 正金额，方向由类型决定；工资及奖金属于入金 |
| BUY / SELL | symbol、quantity、price；实际 fee；settlement_at | 成交生效即改变持仓，结算现金/应收应付另算；结算未知记录异常 |
| FEE | amount | 独立费用；已包含在成交 fee 的同一笔费用不能再次导入 |
| DIVIDEND_ACCRUAL | amount、可提供 symbol | 有凭据的应收，不等于可花现金 |
| DIVIDEND_PAYMENT | amount、fee；有关联应收时 reference_event_id | amount 为总额，fee 为扣税/费用，净到账为两者之差；关联应收转现金不重复确认收益 |
| SPLIT | symbol、ratio | 新份额/旧份额，2:1 填 2；保留零碎实际数量 |
| REVERSAL | reference_event_id | 生效时间等于原事件，重建受影响历史；原事实保留，不覆盖 |

kind 可由 side 或 event_type 别名表达，多字段同时提供必须一致。plan_id 有明确关联时才填；必须属于同账户。不猜测关联关系。事件 ID 在账户内全局唯一；不同来源推荐 `来源:外部ID`，更正引用同样的完整 ID。来源更改不允许以重复事件覆盖事实。

导入流程：预检 → 展示现金持仓及新增/重复 → 提交预检序号与哈希 → 整批事务入账并更新关联计划 → 独立对账。错误包含字段或行号；失败批次不部分入账。格式有效的计划外或超计划实际事实仍需记账并显示异常。

## 独立账户快照

`templates/account_snapshot.csv` 每行一个标的，共同字段重复且必须一致：account_id、as_of、currency、cash_basis、cash、source；quantity 为该标的实际数量。空持仓须一行明确的空 symbol/quantity，而非省略文件。重复标的拒绝，不能默默相加。

cash_basis：settled 为已结算现金；trade_date 为已结算现金加应收减应付。若提供 equity，必须使用对应时点价格；缺价不会视为零资产。真实来源需提供 evidence_hash（独立账单凭据内容哈希）；内部快照自检不能替代券商对账。快照只比较，不直接写入余额或持仓。

对账容差分别配置现金、数量及权益，0为精确比较，规则内容与哈希保留在结果中。容差改变后重新核对，不沿用旧基线；账本不因容差改写。

基线之后的实际导入若要推进对账资格，提交时可显式提供 `--coverage-through` 和 `--coverage-source`，声明完整账单覆盖时点并关联导入内容哈希；不能从最后一行事件时间推断无漏单。缺声明、覆盖不足、未关联成交、迟到或更正事件仍阻断计划，需补独立快照/凭据。

先导入含后续日期事件的账单、再对账较早快照时，后续事件仍需核查，不因已包含在账本序号中漏掉。真实基线之后的新参考时点，即使没有新导入，也需明确完整覆盖，不能推断券商没有发生交易。

## 模拟公司行动模板

`templates/corporate_actions.csv` 与测试 `examples/test_actions.csv` 用于 `simulate-actions`，禁止写入真实账户。
共同字段：action_id、kind、symbol、source、data_type、effective_at、available_at。

- CASH_DIVIDEND：qualification_at、amount_per_share、withholding_per_share（无税也明确填0）；已知支付日填payment_at，否则留空。资格时点之前的实际持仓确定应收，除息后新买入没有资格；支付时只转现金一次。
- SPLIT：ratio为新份额/旧份额；按生效时点转换实际持仓，已有成交及剩余计划数量同步考虑单位变化。
- 行动尚未可用或尚未生效不记账；未知支付日不制造现金；同ID冲突需核对，不覆盖已确认行动。同标的同时间多行动缺顺序依据时拒绝猜测。

真实公司行动使用前述事件模板及 actual 凭据，不由行情或模拟行动自动记账。行情覆盖与行动资格/支付覆盖分别核验。

## 行情 CSV

必需字段：symbol、session_date、market、currency、source、data_type、price_basis、open/high/low/close、adj_close、volume、dividends、split_ratio、available_at。具体例子见 `examples/statement_prices.csv`。

session_date 是市场日期；available_at 带时区，不能早于收盘。无拆股为 1、明确无现金分红为 0；未知值不可填成无行动。synthetic 与 real_market 不混用。price_basis 为 unadjusted 或 provider_split_adjusted；后者不能直接用于证券单位执行。日历必须显式提供可信 schedule 或用真实日历依赖获取，不能用工作日近似真实市场。

volume 为 0 的原始记录会保留，但标记 NONPOSITIVE_VOLUME，不能据此认定可成交。零成交量并非已确认的停牌证据，也可能来自数据源缺失；需补核验后的新版本。信号所需回看窗口、计划参考日及模拟成交日都检查该条件，不以旧价格向前填充。负成交量或非有限数值在导入时拒绝。
