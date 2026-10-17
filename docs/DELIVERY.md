# LyraX V1 交付

2026-10-09。M0–M3工程验收完成；研究、模拟跟踪与人工执行版可用，未启用自动交易。

## 1. 已实现

在线Yahoo/标准CSV、版本化Parquet增量缓存、XNYS日历及数据检查；固定权重基准和126日趋势；bt/ffn扣费回测、净值/回撤/费用/换手/成交/持仓报告。

SQLite事件账本、独立信号归档、稳定调仓计划、现金/份额预留、模拟成交/结算/行动、账单预检及幂等提交、资金流与对账、不可变账户报告、XIRR、日常任务恢复及完整备份恢复。四页中文Streamlit看板，业务时间Asia/Shanghai；demo/paper/real明确隔离。

## 2. 启动与复现

完整清洁安装见[README](../README.md)和[环境说明](ENVIRONMENT.md)。已安装本机环境可在项目根目录激活：

```bash
conda activate "$PWD/.conda/lyra"
python -m pytest -q
python scripts/verify_offline.py
```

已有完整离线演示可直接查看：

```bash
cd reports/manual-demo
lyra ui
```

服务前台运行，按Ctrl+C停止。新建演示与在线目录的完整命令见README；不要跨来源混用已有缓存。真实使用显式选择本地配置，字段及必填条件见[配置说明](CONFIGURATION.md)，账单见[CSV说明](CSV.md)。

## 3. 验证证据

- 第三个独立Conda前缀Python3.11.15，26基础包显式锁、77包SHA256锁重装；pip check、导入及隔离通过。
- 全量**180项通过、无跳过**；32条离线CLI成功，实际bt/ffn/pyxirr与Streamlit均运行。
- 实际在线1536行，增量修订保存版本；固定真实快照两次回测的7份数值CSV、指标、信号决策一致。
- 小样本手算503.5现金、SPY10、权益998.5；九节点行动/结算/出金期末350现金、IEF9、权益800、净投入900。
- 实际Chromium四页、预检/提交/重复、异常/对账/重启；当前模拟8事实不因刷新或重启重复。README备份/恢复命令实测，完整恢复保留逻辑哈希。

逐项要求、命令、退出结果、源码与范围见[ACCEPTANCE](ACCEPTANCE.md)。最终汇总为reports/final-validation/20261009/verification.json。Git尚无提交，全部源码和文档本地交付，未推送。

## 4. 示例报告

- **真实行情 / 历史研究**：[双策略报告](../runtime/demo/reports/research/dd67d9d071a0471c891564fcf52f6a95/report.md)。同目录有manifest、净值、回撤、持仓、权重、信号和交易。
- **测试账单 / 模拟账户**：[手算账单报告](../reports/offline-validation/e12c359d1422412f8b168597e126a571/statement/runtime/demo/reports/account-latest/account.md)、[九节点生命周期](../reports/offline-validation/e12c359d1422412f8b168597e126a571/lifecycle/runtime/demo/reports/lifecycle/account.md)。
- 演示看板截图与操作证据：reports/ui-validation/20261009/current/。报告/行情/账单和环境缓存受Git忽略；重新运行会产生新run_id。

## 5. 已知限制

仅Linux x86_64 / Python3.11验证锁文件；单市场XNYS/USD、日线、月度、只做多。Yahoo Close为供应商拆股调整口径，真实买卖数量需核验原价CSV；历史available_at是推定，非历史实采凭据。支付日/实际税费需账单。

无交易所停牌状态接入，零量/缺价保守阻断；不支持复杂合并/分拆/实物转移和复杂税务。没有用户券商原始账单映射、真实投资业绩、月末前向周期或长期cron证据；调度仅示例，未安装crontab。普通YAML索引超时，已验证显式锁安装；旧socket失败已解决。详细模型token/工具/API费用未获取。

## 6. 下一阶段输入

真实使用需确定市场/标的、账户费用、交易单位、结算约束、风险条件及标准化实际成交/资金/行动和独立账户快照；真实账户仍从零开始，没有默认真实金额。

V2须用户明确要求，提供券商、账户/API权限及适配器条件，先做券商模拟和故障恢复。当前开发授权没有包含真实自动下单；优先评估LEAN/vn.py，不重写交易引擎。
