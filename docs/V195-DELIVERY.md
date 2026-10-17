# LyraX v1.95 交付说明

**当前状态：v1.95本地模拟范围S0–S7编码及验收完成。** 2026-10-17；用户授权范围为模拟账户优先的S0–S7，真实账号暂缓。

## 已实现

- 报告新鲜度/历史版本检查、跨页共享账户和查看时钟。
- ETF和期权隔离工作区、一次模拟入金、冻结配置、后台任务、日检查点、重复请求与恢复。
- 批次交易日/子任务时间/剩余磁盘预算；安全暂停及启动窗口竞态修复，不撤销已记事实。
- 12种月度期权模板、中文参数向导、LEAN原生成交、统一账本、公共开仓/退出计划、预留/部分成交与结算。
- 持续持股滚动、Wheel、部分指派/单位/资金/覆盖异常阻断及凭据保留。
- 决策/适用/到期/结算及有凭据的分红日历；未知日期不估造。期权工作区不误报未使用ETF用途。
- 独立实验、严格公平比较、批注、完整可恢复比较包、同资本风险对照、逐腿/组合Greeks及缺失状态。
- 源码/锁/外部工具内容身份、普通wheel自有C#资源、哈希验证构建缓存、脱敏错误诊断、备份核验和隔离恢复记录。

## 启动与复现

已安装独立Conda：`.conda/v195-clean-install`，Python3.11.15；26包显式基础锁、78个哈希依赖，不共享base。安装和首次运行命令见[README](../README.md)，五条短路径见[操作说明](V195-USAGE.md)。

```bash
conda activate /mnt/c/quant/project/lyra/.conda/v195-clean-install
python -I -m personal_quant ui --workspace /mnt/c/quant/project/lyra/reports/v195-validation/browser-3a05/workspace --port 8501
```

上面工作区为本机已完成的合成历史示例；CLI入口/实际四页启动已经验证，8501是用户启动时的端口选择，不表示服务已安装。需要新实验时按README创建新路径，不重置已有账本。所有验收临时8522服务已停止。

## 当前发布身份

- 业务源码：`3a057618cbe19480abeddba7f3292db263800833cf4e49a91da25f1cbb6ac18d`；版本1.95.0。
- wheel：`reports/v195-validation/release-wheel-3a05/wheels/lyra_personal_quant-1.95.0-py3-none-any.whl`。
- SHA256：`e776195007a493ecc22b8fe09136efe8989446016d98e4713194fa58858ef335`；build.json/installed.json记录构建来源及-I导入、pip check结果。
- 完整发布门禁保存440项源码/测试/配置/脚本/锁输入；逐文件未漂移、无跳过/xfail、每个节点全部阶段恰好通过一次。
- 最终源码归档、验证证据归档、wheel及逐文件清单位于`reports/v195-validation/release-final/`；Git仍无HEAD，无提交/标签/推送。[提交准备](V195-RELEASE.md)只列审阅范围。

## 当前已终态的验证

证据以下均在`reports/v195-validation/`，均绑定当前3a05源码：

| 验证 | 证据 | 实际结果 |
|---|---|---|
| 普通wheel仓库外完整CLI | installed-3a05/verification.json | 12条成功；ETF完整/重复、期权冻结→开平→结算/重复，7事实/99978 |
| 真实Chromium | browser-3a05/browser-verification.json | 14项成功，实际安全暂停/恢复、四页/诊断下载/风险/窄屏/刷新；查看不增加事实，中文已目视 |
| Yahoo真实ETF | online-3a05/verification.json | 2850行，截至2026-10-15；实际增量下载、两策略扣费研究、固定快照7CSV字节及指标复现 |
| 完整备份/核验/隔离恢复 | operator-3a05-cwd/verification.json | 3条实际CLI；7事实/99978，快照、事实哈希及全部检查点前后全等 |
| 独立新策略路径 | paths-3a05/verification.json | clone→切换long_strangle→prepare→status/diagnostic，一次入金，不冒充该克隆已执行 |
| 旧CLI兼容 | compatibility-3a05/verification.json | V1/V15/V18/V19四脚本终态0，32/32/34/53条，源未变 |

最新暂停/预算/任务/诊断/UI目标14项通过（229.27s）；更早新增关联13+独立3+原生1、诊断一致性10项均通过，旧候选记录保留。它们不代替当前最终完整回归。

## 最终门禁与失败处理

- `release-195-isolated-fixed/verification.json`：完整**1045项通过**，UI51与integration994两个进程退出0，原1039节点及新增6个门禁自身用例全部覆盖。每个setup/call/teardown恰好一次且passed，无跳过/xfail，440项输入未变。
- `core-195-journal-fixed/verification.json`：**151项通过**（949.02秒）、无跳过，逐阶段覆盖及输入不变通过。
- 原单进程完整运行曾退出-11，根因未定，失败记录保留；不宣称已定位底层段错误。改为完整收集后的两个进程和即时逐阶段日志，当前相同业务源码完整通过；原崩溃附近备份用例亦在独立进程及当前完整组通过。
- 发现并修复的测试问题包括手工凭据环境依赖、UI预算旧断言及mock导入缓存泄漏，未降低业务检查。原生资格fixture实际生成或重新核验LEAN凭据；没有伪造凭据或删减原测试范围。
- [逐项验收](V195-ACCEPTANCE.md)、[支持矩阵](V195-SUPPORT-MATRIX.md)及计划阶段已核对；发布包逐文件哈希、wheel资源匹配和归档读回核验见[发布清单](V195-RELEASE.md)。

## 示例报告

- 真实ETF：[双策略研究报告](../reports/v195-validation/online-3a05/runtime/demo/reports/research/e001d647901d4e518449e5ce15b3792a/report.md)。真实行情、历史重建，非真实账户收益。
- 合成期权：`browser-3a05/workspace/runtime/demo/reports/account-latest/`；7条事实、99978 USD仅作费用和重复操作核对，非投资表现证据。
- 各CLI的JSON/错误日志、截图、配置/快照引用与完整核验清单保留在对应证据目录，reports不提交Git；新环境通过验证入口重建。

## 限制和下一阶段输入

- WSL挂载盘的完整恢复与发布回归逐文件核验源码/锁/引用，耗时较长；状态刷新只读轻量元数据，不重复完整核验。
- 批次时间预算约束子进程执行，另有最多5秒结束宽限，不保证全部源码/工具预检在该时间内完成。
- 旧backup-bundle按当前工作目录解析runtime_dir，须先cd到工作区；错误cwd会拒绝，不猜测其他账户目录。
- 期权模拟采用明确合成标准合约/日线/月度规则；非常规交割、复杂盘口、跨期/PMCC等仍按支持矩阵的条件范围，不能由目录名称推断执行资格。
- 真实期权行情/使用权、核验证券原价/单位、券商权限/真实账单、自然前向周期均未验证；用户已暂缓真实账号。合成快进不替代真实/自然前向。调度未安装，无自动下单。
- 下一阶段若启用真实记录/前向或V2，需明确市场/券商/账户及API权限、数据来源和使用权、合格合约/证券原价、费用/风险参数与真实凭据；另行授权自动交易开发。当前不要求真实资金或收益目标。
- 模型、API及工具实际费用未获取，不编造；没有购买数据、升级套餐或开通收费服务。
