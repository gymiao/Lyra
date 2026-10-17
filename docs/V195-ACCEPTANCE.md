# v1.95 验收追踪（本地模拟范围通过）

2026-10-17，版本1.95.0，源码3a057618cbe19480abeddba7f3292db263800833cf4e49a91da25f1cbb6ac18d；wheel SHA256 e776195007a493ecc22b8fe09136efe8989446016d98e4713194fa58858ef335。本文件检查用户授权的模拟账户S0–S7范围；真实账户已暂缓。

证据目录以下以reports/v195-validation为根。旧候选成功及主动中止均保留历史，不当作当前最终通过。

| 要求 | 当前源码证据/回归覆盖 | 当前结论 |
|---|---|---|
| S0报告缺失/超前/落后/修订及共享上下文 | test_report_state_v195、test_ui_v195；pause-race-fixed关联UI已通过 | 完整回归覆盖通过 |
| S1普通安装、空目录初始化 | release-wheel-3a05/build.json和installed.json；installed-3a05/verification.json | 独立完整Conda、-I仓库外普通wheel、12条公开CLI通过 |
| S2一次入金、批次预算、暂停/恢复/重复 | test_batch_v195、test_batch_native_v195、workspace/worker/source组；浏览器实际暂停→恢复 | 关联14项、实际安全暂停和完整回归均通过 |
| S3四页/配置/状态/时点 | browser-3a05/browser-verification.json，14项真实Chromium操作；page-3.png实际目视 | 操作、中文、窄屏、刷新、诊断下载、无ETF误阻断通过 |
| S3生命周期日历/未知日期 | test_lifecycle_calendar_v195、test_calendar_diagnostic_v195及原生batch | 决策/适用/分红凭据、未来隔离、未知不推造，完整回归覆盖通过 |
| S4实验独立/比较/归档/风险 | experiments/comparison_package/risk组；浏览器风险图不改账；paths-3a05/verification.json | 实际clone→新模板冻结及只读风险图通过；完整数值组通过 |
| S5路径、环境、资源、构建缓存 | portable_tools/adapter_resources/source_archive/adapter_cache组；清洁安装只读C#资源 | 普通安装通过；完整路径/故障回归通过 |
| S5备份、恢复、容量、脱敏诊断 | operator-3a05-cwd/verification.json；batch/maintenance/diagnostic/backup组 | operator-3a05-cwd已成功：7事实/99978，快照/事实/检查点全等；完整故障组通过 |
| S6全部12模板、滚动、Wheel及异常 | qualification/activation/delivery/rolling/wheel/assignment/prefix/backup组 | 当前逐模板资格/执行/生命周期/恢复及滚动/Wheel完整回归通过；实际来源独立未验 |
| 资金/费用/分红/拆股/时间/幂等 | 独立ledger/strategies/backtest/plans/reconciliation测试 | 当前完整门禁及独立手算预期断言通过 |
| 真实行情研究 | online-3a05/verification.json，2850行真实Yahoo ETF截至2026-10-15 | 当前包实际增量下载/双策略扣费/固定快照7CSV字节和指标复现通过 |
| 旧CLI兼容 | compatibility-3a05/verification.json，四组脚本终态0且源不变 | V1/V15/V18/V19分别32/32/34/53条通过 |
| 最终完整回归 | release-195-isolated-fixed/verification.json；完整逐项JSONL，绑定440输入 | 1045通过（UI51+integration994），全部阶段恰好一次；零跳过/xfail，源及440输入未变 |
| 五条操作路径/发布准备/服务停止 | V195-USAGE、V195-RELEASE、最终DELIVERY与归档清单 | 五条路径已验；旧备份cwd说明已补；8522服务42607停止130；文档及发布清单完成 |

## 保留的失败与修复

- 旧完整第二轮338通过/1失败：测试直接读取缺失资格环境变量；改为实际原生fixture后目标2项通过（1463.10s）。
- 27768/84311/78924完整批次及77006兼容批次因审计缺口/具体复现主动中止130，均非成功。
- 审计补批次预算/决策分红日历/白名单错误码；截图发现通用诊断与专用期权面板状态矛盾，已修，10项关联及当前浏览器无误报通过。
- pause-race-audit独立复现启动窗口暂停被忽略；传递原始提交时间后pause-race-fixed14项通过（229.27s），当前实际浏览器暂停→恢复通过。
- operator-3a05首次验证脚本cwd错误，backup-bundle因数据库不存在拒绝，未更改账户。修正为从工作区目录调用，结果另存operator-3a05-cwd；文档明确旧命令的相对路径语义。
- 字体/日期控件早期验证失败、/tmp容量失败和旧诊断错误均保留日志，不与当前成功混记。

真实期权数据/使用权、核验执行原价、真实账户权限/账单和自然前向未验证；历史合成回放不替代这些证据。本地S0–S7验收完成，不宣称上述外部条件已完成。

## 最终门禁交叉检查

核心151项通过（949.02秒），core-195-journal-fixed/verification.json。完整1045项，release-195-isolated-fixed/verification.json及expected-nodeids.json；UI51项490.59秒，integration994项，最终逐阶段结果与完整收集逐项一致。6个独立门禁用例拒绝漏测、重复阶段、跳过、xfail及失败teardown。源码/锁/测试等440项输入完全未变。

旧单进程release-195-3a05-all确实退出-11，根因未定，不能记成成功。其两项凭据环境依赖及UI mock导入泄漏均转为正式回归；当前完整分进程不删原1039节点，并包含新增6个门禁用例。原崩溃附近prefix-exit备份单项独立通过852.34秒，在当前完整组亦通过。完整成功不代表已经确定旧底层崩溃原因。

最终源码/证据归档及wheel读回核验、SHA256清单见[V195-RELEASE](V195-RELEASE.md)。不执行Git提交、标签或推送。
