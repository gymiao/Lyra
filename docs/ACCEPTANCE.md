# V1 验收证据

2026-10-09（Asia/Shanghai）。V1工程验收通过：研究、模拟跟踪、人工执行建议及标准账单闭环。依据GOAL.md；真实账户、长期前向表现及自动交易没有以样例替代。

## V1交付时版本与环境（验收基线）

- 源码指纹 `d1467f33e8d1f84f8c82e6275ec00bd82e1dbafe7ffe985421b0d50bb080cc8b`。Git main尚无提交，文件未跟踪；未提交或推送。
- Python3.11.15、Linux x86_64 / WSL；最终清洁前缀.conda/readme-install。26包官方URL/MD5基础锁、77包wheel SHA256锁及项目安装通过，pip check通过。imports-final.json核对全部版本、主库实际导入位置、用户site关闭及无外部site-packages。
- 最终全量 `python -m pytest -q`：**180 passed / 0 skipped，60.50s**；日志reports/environment/clean-20261009/pytest-final.log。包含实际bt、ffn、pyxirr与Streamlit AppTest。
- `python scripts/verify_offline.py`：**32条CLI均退出0**，清单reports/offline-validation/e12c359d1422412f8b168597e126a571/verification.json，源码匹配。

## GOAL第11节逐项验收

| 验收项 | 状态 | 权威证据与范围 |
|---|---|---|
| 指定环境安装和启动 | 通过 | 第三个独立Conda前缀实际建立，77包哈希重装、安装/导入/激活/CLI/UI启动；readme-conda-create.json、readme-lock-install.log、readme-project-install.log、readme-pip-check.log，位于上述环境目录 |
| 在线接入实际验证 | 通过 | Yahoo真实SPY/IEF/GLD各512日、1536行，2023-01-03至2025-01-16；初次下载、增量及历史复权修订刷新实际记录，位于reports/online-validation/20261009/fetch-*.json与日志 |
| 离线无真实账户/密钥 | 通过 | 32CLI及完整demo含bt；测试账单test、合成行情synthetic、模拟成交simulated；没有密钥要求 |
| 基准/候选运行和复现 | 通过 | 实际bt固定/126日趋势，固定真实快照重复两次，核对实际文件SHA256、7份数值CSV、指标与决策；只排除run_id/实际generated_at |
| 费用/分红/资金/时点明确 | 通过V1支持范围 | DECISIONS、CSV与研究假设；bt手算、Decimal账本、结算、九节点分红/拆股/出金、XIRR；复杂行动保持待核实 |
| 调仓生成可追溯 | 通过 | SQLite信号归档，稳定意图/plan_id，配置/行情/账户依据、风险/资源、修订/部分/迟到和结算依赖；CLI/页面及相关测试 |
| 成交/资金导入且幂等 | 通过 | CSV预检/序号/哈希提交、同ID冲突、回滚与计划投影；浏览器提交、立即更新资产、重复新增0 |
| 样例账户可对账 | 通过 | 独立人工样本503.5现金/SPY10/权益998.5/净投入1000/盈亏-1.5；九节点350现金/IEF9/权益800/净投入900/盈亏-100；独立CSV快照 |
| 四页可使用 | 通过 | 当前Chromium四页切换/刷新、曲线/成本/交易、目标/原因/检查、失败/对账/重启；browser-*.json、截图与AppTest，业务时间Asia/Shanghai |
| 关键行为测试 | 通过 | 下表及最终180项，无主框架跳过；零量有独立失败前证据，修复后不生成有效信号或模拟成交 |
| README命令实际执行 | 通过 | 安装/激活/pip check/help、pytest/offline、manual-demo demo/status、manual-online fetch/research/incremental、lyra ui、daily/backup-bundle/verify-backup/restore，日志与路径见下文 |
| 限制/未覆盖明确 | 通过 | README、ENVIRONMENT、CONFIGURATION、CSV、OPERATIONS、DEPENDENCIES及DELIVERY；原价/行动凭据、券商映射、前向长期证据与平台边界明确 |
| 模拟不冒充真实 | 通过 | demo/paper/real分库分目录；真实零账户拒绝test/simulated；复权虚拟份额与证券数量分开；页面用途与来源独立标注 |

## 功能子要求与独立预期

| GOAL章节 / 关键行为 | 实现与检查 |
|---|---|
| 4.1 在线/CSV/缓存/增量/版本/去重/检查/重试 | data模块及test_data_strategy/online_update/quality；内容ID不含获取时间，采集日志另存；真实字段口径齐全；不填缺价/非交易日，零量保留且阻断 |
| 4.2 策略输入/权重/时间/版本/原因/不足 | monthly、archive与test_data_strategy/signal_archive/research_config；规则事先固定，共享函数，账户状态不得晚于决策，数据不足不执行 |
| 4.3 bt/公平比较/费用/滑点/旧持仓收益/明细/复现 | 唯一bt、ffn指标；test_backtest四个独立样例验证次日跳涨不提前获利、固定费用、首日损失、当日调仓前权益换手；冻结配置/源/输入/依赖 |
| 4.4 跟踪/计划/单位/资金/预留/幂等 | plans、simulator、daily及32CLI；证券数量仅用unadjusted，事前冻结数量，缺价/资金不足整批不记模拟成交，无复杂撮合 |
| 4.5 SQLite事实/快照/导入/对账 | 事件、账户、计划、导入、独立对账含现金持仓快照、任务与daily；快照由事件重建；test_ledger/imports/reconciliation_rules/lifecycle |
| 4.6 权重/上限/资金/数据/重复/差异风险 | test_plans/simulator/quality/revisions；新差异阻断已有READY/PARTIAL，保留占用；过期对账不成交，历史研究仍可读 |
| 4.7 四页/截至/类型/指标/XIRR | ui、backtest、report，实际浏览器及test_ui；固定研究资金隔离外部流，个人投入/XIRR单列，无解/多次变号显示原因 |
| 平价新增入金不是盈利 | test_ledger及pyxirr样例：1000+500平价权益1500，盈亏/XIRR均0；365日1000到1100的XIRR为10% |
| 分红/拆股不重复资产 | test_corporate/ledger与九节点；应收到支付只转换；真实凭据不由行情自动入账，复权研究不再加分红 |
| 未来数据/未发布信号 | test_data_strategy/signal_archive/research_config；未来adj_close扰动不改旧信号；盘中行不缓存成随时钟自动升级的完整日线 |
| 重复下载/重跑/账单 | 内容ID/增量版本测试、32CLI、实际浏览器重复新增0；实际供应商修订产生新版本，不称重复请求必然内容不变 |
| 缺失/过期/资金不足/零量 | test_plans/simulator/quality/daily；零量即使缺前价也阻断，READY遇零量现金持仓不变、整批不记账 |
| 手算现金与持仓 | 上述503.5/10/998.5及350/9/800；模拟1000入金买4SPY/9IEF，费用2、权益998 |

## 实际报告与命令位置

- 真实研究快照db11f596b146a165c3507dc0f0e35d45379936680025585f04fa1229a9655775；run_id dd67d9d071a0471c891564fcf52f6a95 / 6a747b8f5fad42ef9974dcda202e4e9c。首份runtime/demo/reports/research/dd67d9d071a0471c891564fcf52f6a95/report.md，核对reports/online-validation/20261009/verification.json。
- 实际XNYS库核对冬/夏21/20UTC、7月3日17UTC提前收市、7月4日休市、发布29/30分钟边界。真实来源SPY8/IEF24分红、GLD0、无拆股；真实拆股未声称观察，行动CSV/独立样例承担单位验证。
- README完整演示：reports/manual-demo，环境目录readme-demo-final.json、readme-status-final.json；blocked_batches=0，包含当前源码实际bt。在线README独立目录reports/manual-online已获取/研究/增量成功；最后根目录固定真实快照在最终源码上复现通过。
- README最后4条恢复命令绑定上述e12c359目录daily-restored；readme-daily.json、readme-backup.json、readme-verify.json、readme-restore.json退出0，恢复逻辑哈希/行数相同、事实仍3。
- 四页证据reports/ui-validation/20261009/current/browser-verification.json、browser-write-verification.json、browser-recovery-verification.json。读页不改8事实/6计划/9归档；预检不写、单次1USD测试费用只增加1、立即刷新、重复新增0；重启现金保留，独立差异到PASSED、事实仍8。最后UI/数据改动后复验读页/对账，未改写入逻辑，相关回归全量通过。临时服务已停止。
- status递归膨胀已修复；成功查询只读，最近20条任务摘要保留错误；100KB旧嵌套记录样例反复查询小于2KB、账务和任务不变，status-before.log/status-regression.log保存失败前/后证据。

## 限制与历史失败

旧socket errno1已解决。普通Conda YAML索引ReadTimeout不算安装；推荐显式锁实际安装成功。QA首轮localhost健康检查经代理返回502，设置本次测试NO_PROXY后成功。浏览器缺动态库/字体仅在/tmp配置，不改系统或分发字体。

Yahoo Close为provider_split_adjusted，仅作为已验证研究来源；真实数量需核验原价CSV。历史available_at由日历/延迟推定，不是当时实采；支付日/实际税费需凭据。没有交易所停牌状态源，零量是不合格诊断而非确认停牌。

无用户原始券商账单映射、实际投资金额、月末真实前向周期或长期cron证据；GOAL允许测试账单且不要求等待完整市场周期。cron只提供示例，未安装实际crontab。V2需券商/API/明确要求后另行启动；跨平台锁、复杂行动/税务、多市场/多币种不在验收范围。详细模型/输入/缓存/输出/推理token及API费用未获取。

## 后续真实行情更新（2026-10-09）

用户追加执行已更新至2026-10-08，共2835行；当前研究报告与UI源码使用新指纹，单独证据见reports/live-research/20261009/verification.json和browser-verification.json。3项UI回归、实际真实行情研究页面及刷新通过；原180项/42份文件的清单保留为V1交付时证据，后续文档或UI变更不冒充该基线的同版本全量测试。
