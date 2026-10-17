# 最终验收前进度归档（历史，不代表当前状态）

# LyraX 当前进度

2026-10-16，Asia/Shanghai。当前授权：完成v1.95 S0–S7编码/验收，模拟账户优先，真实账号暂缓。Goal active，整版未完成。单Agent，不改GOAL、不自动交易、不付费、不提交Git。

## 当前业务与发布身份（未改）

- 版本1.95.0，业务源码`3a057618cbe19480abeddba7f3292db263800833cf4e49a91da25f1cbb6ac18d`。
- 普通wheel在`reports/v195-validation/release-wheel-3a05/`，SHA256 `e776195007a493ecc22b8fe09136efe8989446016d98e4713194fa58858ef335`。
- 独立Conda `.conda/v195-clean-install`：Python3.11.15、26包基础+78个哈希依赖，当前wheel -I指纹/pip check通过，自有C#资源只读，不共享base。
- 当前只修测试/验证入口，业务源码和上述wheel未改。**不要重做仍有效的六类当前工作流。**

## 已终态成功的当前业务验证

证据根`reports/v195-validation/`：installed-3a05（12公开CLI）、browser-3a05（14实际Chromium含安全暂停/恢复和无ETF误报）、online-3a05（2850行真实Yahoo截至10-15、双策略/增量及7CSV/指标复现）、operator-3a05-cwd（3CLI完整备份/核验/隔离恢复，7事实/99978且快照/事实/检查点全等）、compatibility-3a05（旧32/32/34/53CLI）、paths-3a05（clone→换模板→冻结→状态/诊断，无执行）。

core-195-3a05-all：145项通过（906.59s）、无跳过、439输入不变；后来仅验证基础设施改变，因此新核心门禁重验。8522服务42607及旧服务均已明确停止130；GOAL哈希与旧基线一致。

## 最近完整失败与已修项

- `release-195-3a05-all`/13465已终态失败：pytest退出码**-11**，2026-10-16T07:10:28Z；源/439输入不变，无跳过，但未生成正常全量汇总。长测试栈不能当成功；本次真正是段错误，根因未定。
- 事后完整收集1039个原节点，按进度记录映射804项已结束，其中3失败：507后台prepare UI；703/704两种原生部分指派恢复。映射在observed-outcomes.json；原始日志全部保留。
- 原生恢复测试仍直接要求LYRAX_TEST_ENGINE_EVIDENCE；已改导入真实engine_evidence fixture，默认可自建，当前复用并重新核验本轮真实凭据的目标2项通过（110.23s），native-recovery-fixture.log。
- 后台prepare UI单独31.91s通过，组合复现后逐项JSONL抓到IndexError：前一个UI测试在mock jobs.launch时首次导入ui.option_setup，模块缓存了临时函数，后续点击仍调用旧mock且没有真实任务。已在测试mock前加载无关模块，避免泄漏；业务代码不变。按原顺序连续目标2项通过（35.86s），ui-import-leak.log，未延长超时/降低断言。
- 崩溃附近prefix-exit备份用例82403独立进程已终态0：1项通过（852.34s），crash-prefix-isolated.log；本次没有复现段错误，不据此宣称已知旧崩溃根因。
- 验证入口现将UI与其他测试放在两个独立pytest进程，**保留全部原1039节点**，新增6个门禁自身用例。先完整收集再逐项核对节点/阶段/结果，漏测、重复、跳过/xfail、失败或进程崩溃均不能通过。逐setup/call/teardown结果即时写JSONL，防止以后崩溃丢失前面失败详情。6项门禁独立测试通过（0.38s）。

## 当前活跃句柄（恢复先poll，不重启）

| 任务 | exec | 证据 |
|---|---:|---|
| 当前完整分进程门禁 | **84862** | release-195-isolated-fixed/：collection.log、expected-nodeids.json、ui/integration-pytest.log、对应results.jsonl、phases.json、最终verification.json |
| 当前核心及逐项日志门禁 | 已终态0 | core-195-journal-fixed/verification.json：151通过（949.02s），无跳过、440输入未变、完整逐阶段覆盖 |
| 原崩溃附近用例单独复现 | 已终态0 | crash-prefix-isolated.log：1通过（852.34s），使用重新核验的真实covered-policy证据 |

完整门禁UI子组已51项通过（490.59s），phases.json=PASSED；剩余994项在新integration进程运行，逐项证据不能遗漏。目标46298/26534/39012/77015/82403已终态0。第一次隔离36089及core12397因已复现mock泄漏而主动中止130，保留ui-results.jsonl完整失败栈；不是通过。新门禁源码/测试/脚本/锁已重新冻结（输入数以inputs.json为准，当前实际440）；**运行期间不改这些输入。** 日志可读但不要把观察超时当停止。新验证不用定时栈打印，已有逐项持久日志；只依据句柄/阶段终态判断。

## 下一具体动作

1. Poll84862（68567已终态成功），检查results.jsonl中即时失败；先保留完整诊断再判断原因。全量必须所有原节点和新门禁用例均有且仅有全部passed阶段、无跳过/xfail、源及输入未变。
2. 发现实际错误先核验其根因；不把旧工作流成功代替当前完整门禁，不缩减S6，不伪造原生凭据，不为快速通过删除测试。
3. 两门禁及崩溃附近复现完成后，做S7逐项审计、支持矩阵/README/DELIVERY/计划状态、最终源码归档及提交准备清单，完成后才标本地v1.95范围完成。

## 边界与历史

真实期权数据/使用权、证券原价资格、真实账号/账单及自然前向未验；用户暂缓真实账号，合成快进不替代。调度未安装，无自动交易。模型/API/工具费用分项未获取，不编造。

旧GUI预算断言115/77失败已修并目标3通过；暂停竞态/预算/状态目标14通过。错误cwd备份被拒，改cwd后当前操作已成功。/tmp曾满，旧7目录360281590字节校验迁移保留及兼容别名不得删；大组临时产物在项目磁盘。详细旧句柄/失败/证据见[段错误前归档](PROGRESS-HISTORY-V195-20261016-SEGFAULT.md)、[审计历史](PROGRESS-HISTORY-V195-20261016-AUDIT.md)。
