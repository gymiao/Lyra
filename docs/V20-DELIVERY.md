# LyraX v2.0 交付说明

2026-10-17，Asia/Shanghai。**v2.0本地P0–P8编码及验收完成，版本2.0.0。** 真实账号继续暂缓，E1/E2/E3与原GOAL券商自动交易独立未验证。

## 1. 已实现

- 可靠任务：先持久提交、owner握手/子组清理、稳定请求、并发幂等、总预算/阶段、错误/最后检查点、分页索引、显式核实和重试。
- 输入贯通：逐用途/逐日冻结清单、实际输入比较、旧证据不足阻断、CSV映射导入、分页重试/修订、本地前向追加契约。
- 通用模拟：固定种子多月价格/IV、完整链与时点/缺价/公司行动检查；14月度期权模板、跨月持股滚动和实际前缀决定分支的Wheel。
- 研究：预声明参数/开发评估窗口/成本压力、股票/现金同资本基准、失败覆盖率及独立结果，不自动选参或拼接收益。
- 铁鹰/铁蝶完整四腿模拟：选约、资格、保守履约资金、公共计划、端点、双向指派/到期、两周期及持仓中备份恢复。
- 四页中文工作台、新实验/独立窗口、异步维护/比较；多策略资金与股份仅只读预演。
- 运维：一致备份/新目录恢复、cron只读预检、普通wheel、完整分组门禁、成功组校验归档后释放临时空间、可核验发布包。

## 2. 启动与复现

本机已装独立Conda `.conda/v20-clean-install`；从仓库运行：

```bash
conda activate /mnt/c/quant/project/lyra/.conda/v20-clean-install
python -I -m personal_quant ui --workspace /mnt/c/quant/project/lyra/reports/v20-validation/installed-classic-r4/etf --port 8501
```

打开http://localhost:8501，Ctrl+C退出。工作区是已完成的合成ETF模拟，不是真实账户。首次新建、安装锁、源/费用及完整三周期演示见[README](../README.md)和[操作说明](V20-USAGE.md)。数据包/工作区/验证目标用新目录，避免覆盖历史。

三周期期权公开CLI：`python -I scripts/verify_v20_quarter.py --destination /新目录 --engine-root '/LEAN路径' --dotnet '/dotnet路径'`。实际使用官方LEAN提交80e7843f645673bcbeaab963049f76f20f6785e1、SDK10.0.100；工具另行准备，不捆绑SDK/LEAN或修改第三方核心。[支持矩阵](V20-SUPPORT-MATRIX.md)；[升级/备份/恢复](V20-MIGRATION.md)。

## 3. 实际验证

| 项目 | 结果及本地证据（均在reports/v20-validation） |
|---|---|
| 完整回归 | release-r8/verification.json：1110节点/3330阶段、无skip/xfail、484输入未变，终态0；release-audit-r8.json独立重新计数及归档SHA核对 |
| 安装 | installed-final-r8：独立Conda、pip check、185 Python逐文件/C#来源、仓库外CLI通过 |
| 公开CLI | installed-classic-r4的12条+installed-quarter-r4的8条；当前193随包应用/资源逐字节一致，wheel-code-equivalence-r4-r8.json证明，原wheel SHA均保留 |
| 只读原生 | readonly-binding/quarter-r4：Linux拒绝写入应用/适配，8原生CLI/三周期通过；补充venv依赖取自独立Conda |
| 在线 | online-r4：真实ETF2853行截至2026-10-16、9CSV/指标固定快照复现；研究评估到2026-10-15，历史可用时间假设明确保留 |
| 离线 | offline-r4-receipt.json：原独立手算回执及SHA保留，不把规范化包装当新金融操作 |
| 实际浏览器 | browser-final-r8：四页/Wheel/滚动/记录的T+1结算/重复/坏任务核实/后台备份/手机390×844；所有自有服务STOPPED |
| 完整恢复 | backup-r4：11CLI、4类财务表一致、7事件、重复不增；归档在途任务显式按原始哈希核实，不改事实，调度未装 |
| 快速组 | fast-r4：60项28.05秒，门禁37.62秒，仅快速阶段证据，不代替全量 |

完整通过阶段合计6587.67秒（含归档，跨续跑累计），最后续跑墙钟4104.57秒；不是原失败/取消命令的连续耗时。UI同52用例观测WSL447.43秒、Linux182.38秒，非独占严格基准。247次30秒采样中，测试目录最大3,011,465,746字节、卷占用最大5,664,243,712字节（含其他进程），不是精确峰值。旧整套产物10.34GB，分组校验归档后释放避免一次占满/tmp。

### 原始失败与完整续跑

失败并未隐藏：Wheel日期比较/未知异常无回执已修；浏览器控件/日期脚本错误保留；WSL chmod无效、旧-11根因未知保留。两项旧测试分别是版本筛选硬编码1.95.2（新冻结规则2.0.0）和新增四腿遗漏显式翼宽；只修隔离测试函数/helper，不改金融逻辑、不降低金额/幂等/链完整性断言。

最终完整收集始终1110。对已通过完整进程核验实际业务/C#、测试/共享fixture作用域、collection/日志阶段和档案SHA后复用；AST证明未涉及变更的其他定义/导入/483输入不变，变更模块不能被复用阶段选择或导入，受影响整个进程全部重跑。旧失败/取消整轮仍FAILED，旧失败组局部结果不计入完整覆盖。最终3330阶段全部核对；驱动、先前测试文本、新旧SHA/作用域及原始回执纳入验证包，不声称原取消命令成功。

实际命令：`check_v20.py --scope release --integration-groups 8 --archive-temp-to …`创建完整分组；完成阶段按上述条件由保留的lyrax-resume-release-r8.py续跑，最终终态0。新机器可直接用仓库check_v20命令从头跑全部测试，无需旧阶段缓存。

## 4. 报告与发布包

- 真实ETF研究与固定回放：online-r4/verification.json的research_report/replay_report，9个CSV和manifest；市场行情真实，研究结果非真实账户收益。
- 三周期模型模拟：installed-quarter-r4/workspace/runtime/demo/reports，7事件/99633USD。
- 实际滚动模型：browser-rolling-r6及browser-rolling-settle-r6-third，研究终点卖股后结算，9事件/100283USD/应收应付0。金额仅工程样例。
- 最终发布目录：`reports/v20-validation/release-final/`：source.tar.gz、wheel/普通wheel、validation.tar.gz、validation-files.json、六类evidence回执、operator-scripts、manifest.json、SHA256SUMS。
- 详细验证包551文件，其中264个当前原生机械证据文件；逐成员读回，未打包SDK、SQLite或批量原始行情。原始测试临时档案按阶段回执路径另存，可能含SDK副本，不对外分发。原v1.95 release-final不覆盖。

业务源码：`8397988c7915bbc131a14559200a9535e3c879ce93cc6153e0109244873595cc`。wheel SHA256：`3932d870f48673b5acee5101689915fc73bd324655928c8e66c2ed4840c1649c`。发布核验命令：`python scripts/release_v20.py verify --destination reports/v20-validation/release-final`及`sha256sum -c SHA256SUMS`；最终原始回执在release-final-verification.json。源码/wheel与详细证据均按SHA绑定，不虚构Git提交号；build.json仅标构建状态，最终本地验收以release.json为准。

## 5. 限制与下一阶段

- E1真实期权来源/权利及证券原价/公司行动资格未验；实际Yahoo Close不直接计算真实证券份额。模型报价、历史快进和测试账单不作为真实行情/前向/实账。
- E2自然前向及实际调度未验；E3同账户多策略执行未验，预算预演不写入资金或预留。旧单进程pytest -11根因未定。
- 标准100股美式实物合约、全额履约资金；不假定券商组合保证金。跨期/非标准产品/卖空/多币种/盘中执行不从当前成功推断。
- 原始市场快照单独保存在online-r4的数据目录，重新下载可能修订；精确重现需保留原快照及对应使用权，普通源码包不再分发批量行情。
- 单机同一账户/进程环境的本地工作台，不提供共享多容器账户或公网多用户服务。
- 没有真实账号自动下单、调度安装、外部通知/上传、购买服务或Git提交。模型/API/工具用量与费用未获取，套餐/API费用分开，不编造。

v2.0限定P0–P8已完成，整体路线仍有未开发功能，见[未完成能力清单](UNFINISHED-FEATURES.md)。启动E1需供应商/凭据/使用权/覆盖与费用；E2需合格数据、实际机器与调度授权及真实时间观察；E3需归属、冲突优先级和收益分摊规则。券商自动交易另需用户明确授权、券商和API条件。本地使用不需要提供真实账号。
