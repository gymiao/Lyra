# LyraX 模拟账户使用（2026-10-14）

用户本轮要求：先跳过真实账号，使用模拟账号。真实账户接入暂缓；当前采用隔离demo中的合成历史模拟，不修改paper/real资格、不接券商，不把本次结果作为真实期权接入或自然前向验收。

## 已运行的模拟

- 账户：`demo-account`，USD；示例入金100000，不代表用户实际资金。
- 策略：SPY股票＋保护Put；两个冻结月度信号，次交易日收盘模拟，计划/信号见工作区simulation-plan.json。
- 行情：固定合成变化路径；2024-11-01至2025-01-10，最终结算截至2025-01-13T21:00:00Z。
- 原生LEAN成交、整张合约/100乘数、买ask/卖bid、期权每合约成交费2 USD、股票佣金2 bps；现金利息0。价差已包含在交易盈亏中，费用汇总中的价差解释不能再扣一次。
- 三组同初始资金/区间/费用条件。仅持股组采用与策略相同的股票股份，其余持现金，不是满仓SPY基准。

| 模拟组合 | 期末权益 USD | 模拟盈亏 USD |
|---|---:|---:|
| 股票＋保护Put | 100642.7416 | 642.7416 |
| 仅持股 | 100597.7416 | 597.7416 |
| 现金 | 100000 | 0 |

这是一条工程测试路径，不证明保护策略优于持股，也不能用于预测收益。47个收益观察点；初始入金计入净投入，不算盈利。账户13事件、重复导入新增0，最终股票/期权均平仓并结算，无预留或未结算余额。

## 打开看板

本次已启动：http://localhost:8501（服务器原句柄45823）。账户ID默认为demo-account。

1. 账户总览查看资产100642.7416、净投入100000和模拟盈亏642.7416。
2. 侧栏固定样本查看时点填写`2025-01-13T21:30:00Z`并回车，可查看完整已结算周期。
3. 策略研究展开“期权月度比较：合成机械验证报告”，查看三组净值、回撤、费用和交易记录。
4. 本演示未绑定ETF策略日线缓存，“尚无行情”提示指该缓存；期权比较使用独立冻结合成路径。没有当前可执行调仓计划；simulation-plan.json是历史冻结安排，不能当作当前READY计划。不要用此数据启动实时paper任务。

服务停止后执行：

```bash
cd /mnt/c/quant/project/lyra/reports/simulated-account/20261014-01/workspace
MPLCONFIGDIR=/tmp/lyrax-mpl PYTHONDONTWRITEBYTECODE=1 \
/mnt/c/quant/project/lyra/.conda/v19-clean/bin/python -m streamlit run \
/mnt/c/quant/project/lyra/src/personal_quant/ui/app.py \
--server.address 127.0.0.1 --server.port 8501 --server.fileWatcherType none \
--server.headless true --browser.gatherUsageStats false -- --config config.json
```

必须从上述隔离工作区启动，配置保持runtime_dir=runtime/demo；不要换成绝对路径。首次绝对路径配置被环境保护正确拒绝，修正后6项实际浏览器检查通过。Ctrl+C停止服务。

## 复现原生研究

在项目根目录运行（换一个尚未存在的新工作区，避免覆盖当前演示）：

```bash
cd /mnt/c/quant/project/lyra
MPLCONFIGDIR=/tmp/lyrax-mpl PYTHONDONTWRITEBYTECODE=1 \
.conda/v19-clean/bin/python scripts/verify_monthly_compare_path.py \
--workspace /mnt/c/quant/project/lyra/reports/simulated-account/replay-new \
--engine-root /mnt/c/quant/project/lyra/.tools/lean \
--dotnet /mnt/c/quant/project/lyra/.tools/dotnet/dotnet
```

此命令以20261014-01目标实际执行通过；新输出包含comparison/report.md、report.json、equity.csv、transactions.csv和各组bridge.sqlite/ledger-bridge.json。它生成研究与模拟账本，不自动复制用户看板工作区。

## 证据和报告

本批根目录：`reports/simulated-account/20261014-01/`。

- verification.json：公开月度比较CLI及独立资金预期通过。
- account-verification.json：同源13测试事件、标准账本重放、重复导入0、现金/持仓/净投入核对通过。
- browser-verification.json：当前源码6项实际浏览器检查、四页/刷新、13事件hash不变。
- dashboard-initial-failures.json、import-time.log和apptest-diagnostic.log：准备配置/页面失败、诊断及修复记录。
- comparison/report.md：三组研究报告。
- workspace/runtime/demo/reports/account-latest/account.md：模拟账户报告。
- workspace/simulation-plan.json：历史冻结模拟安排，executable=false。

业务源码、依赖锁及原runtime/demo没有修改；未使用真实账户，无券商订单。后续可明确模拟资金、标的及优先策略，再配置新的独立实验。真实来源和自然周期要求保留到后续阶段，原GOAL不修改。
