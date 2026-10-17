# LyraX 当前进度

更新：2026-10-17，Asia/Shanghai。用户授权完成v2.0本地P0–P8；P0–P7已编码，P8最终完整验收续跑中，**未完成整版交付**。单Agent、不自动交易/购买/调度安装/Git动作，真实账号暂缓。

## 冻结身份

- 应用2.0.0，Python3.11.15，账本schema5；业务源码`8397988c7915bbc131a14559200a9535e3c879ce93cc6153e0109244873595cc`。
- 候选`reports/v20-validation/release-candidate-r7/`，普通wheel SHA256`1f0d85669b9e12730524c26c781f5cf06ef888f20fcf9cdf4d5a0a4d111a1129`；独立Conda `.conda/v20-clean-install`安装/依赖/185 Python文件/C#资源/仓库外CLI身份均通过，installed-final-r7。
- r4/r5/r6/r7的193个应用/资源文件逐字节全等；仅门禁/测试和发行元数据变化，原CLI/浏览器/在线/恢复证据保留真实原wheel，不假称重跑。
- 当前业务/脚本/测试/配置/484个受保护输入冻结。完整收集1110节点（原1107+3归档自测），所有setup/call/teardown精确计数，无跳过/xfail才通过。

## 当前活动与已核实结果

| 句柄 | 状态/动作 | 证据 |
|---|---|---|
| 29398 | r7完整门禁续跑，复用UI52/int01的133/int02的133；失败的int03及后续全部执行 | /tmp/lyrax-v20-release-r7；release-r7.log |
| 20583 | 30秒空间抽样（非精确峰值） | /tmp/lyrax-v20-release-r7/resource-samples.jsonl |
| 22476 | 已终态0，COMPLETED/9事件/100283USD/应收应付0，服务STOPPED | browser-rolling-settle-r6-third |

- 原r6 UI52通过182.38秒、归档4170成员读回；integration-01共133通过813.68秒、25942成员/约1.7GB归档读回后释放。原完整门禁因误判浏览器失败而取消（72283终态1），**原overall仍FAILED，不把局部成功转成原整轮通过**。
- 新续跑驱动`/tmp/lyrax-resume-release-r6.py`重新完整收集1110，与原expected/484输入/源码逐项相同；对UI及integration-01逐日志/collection及归档SHA重新核验后复用，原部分integration-02不复用。最终仍须全部1110逐阶段完整，通过只属于新完整汇总。驱动源码随最终证据保存；原取消/错误全部保留。
- 当前同业务源码：fast60通过28.05秒；offline-r4独立账务；installed-classic-r4为12CLI；installed-quarter-r4为8CLI/3周期/7事件/99633USD；readonly-binding/quarter-r4为实际Linux只读应用+8原生CLI；online-r4真实ETF2853行截至10-16、9CSV复现；backup-r4为11CLI/4表一致/7事件、恢复重复不增事件，调度未装。最终安装以r6独立回执为准。
- Chromium主流程11记录动作及手机390×844补验通过，原服务STOPPED；最终r6补充三周期covered_call/retain_stock表单、推进、刷新，93915终态0、9事件；到市场末日PAUSED有9998应收，不冒充结算完成，22476结算回执已PASSED，COMPLETED/9事件/100283USD/应收应付0，重复不增事件；服务STOPPED。

## 最新误判与修正（未修改业务代码）

操作者先错把市场末日当结算完成；又误用setup hint（UNKNOWN）代替成交中已记录的settlement_at。第二次日期脚本实际提交2024-01-01，任务6d346ed…正确以INVALID_SIMULATION_DAY拒绝。初步误判为日历缺陷后已复核原job.through及batch源码：后端本来支持市场末日后10天结算，**没有改scenarios/calendar/账本**，源码仍8397988c。旧9事实完整保留。第三次脚本先设日再设月并校验实际日期，使用原SELL的settlement_at=2024-11-01；原错误日志保留，不重新成交。

## 下一具体动作

1. 核实29398完整终态（22476结算终态0已通过）；不再新增功能/改源码。若失败只修实际证据支持的问题，先查看原请求。
2. 最终门禁PASSED后等监控结束，将小型证明目录从/tmp逐文件复制到reports/v20-validation/release-r6，保留所有阶段日志/collection/inputs/原取消引用；已验证测试临时目录归档位于release-r6-test-artifacts及release-r6-resumed-test-artifacts，不分发其中SDK。
3. 运行`/tmp/lyrax-package-validation-r6.py`（待补滚动证据目录）；六回执使用release-r7/verification.json、installed-final-r7、browser-final-r6、offline-r4-receipt、online-r4、backup-r4。完整测试原生四腿证据从已校验分组归档流式提取，普通源码/验证包不含SDK/数据库/批量行情。
4. 更新README/计划勾选/支持/迁移/交付/agents/PROGRESS最终实际终态，再release_v20 refresh-source→finalize→verify；复制同一产物到release-final并核验SHA256。不提前写完成。

## 保留边界

E1真实期权源/权利、E2自然前向/实际调度、E3同账户多策略执行未验，多策略仅只读预演。真实账号/自动交易未启动，模型/合成与实账分开。旧pytest -11根因未知，分进程通过不证明根因修复。依赖锁/GOAL未改，Git无HEAD，未提交/推送。模型/API/工具用量与费用未获取。

历史及所有取消/初次失败：[前批历史](PROGRESS-HISTORY-V20-R6-RESUME.md)。原v1.95最终归档保持原样。

## r7实际失败修复

12898终态1：integration-02的133项通过576.91秒并37976成员归档，integration-03因旧测试硬编码monthly-selection/1.95.2而1失败2通过（未完整覆盖）。实际新冻结规则为2.0.0。仅修tests/test_comparison_package_v195.py中的失败函数：读冻结版本并验证当前发布2.0.0，临时改当前模块版本后索引仍只匹配冻结记录，保留3实验/观察区间/错误版本空集断言；未改业务源。40679终态0，该测试用已真实生成的3个原生账户7.19秒通过；最终int03全部重新生成/执行，不用该定向代替完整。

50800候选r7构建终态0，55814安装终态0，应用仍8397988c、193随包文件与r4逐字节全等。续跑驱动/tmp/lyrax-resume-release-r7.py严格要求只有上述一个测试文件变动，AST验证其他顶层定义/导入不变，复用的完整进程不能选择/导入该模块或函数；其余483受保护输入与应用/共享fixtures全同。新1110节点完整重收集，修改的整个int03及后续重跑，所有最终阶段严格3330条setup/call/teardown且无跳过后才通过。原失败/取消整轮保留FAILED，复用范围及新旧SHA写isolated-test-fix.json，不把它们转写成功。


r7进度：前三完整阶段UI52/int01的133/int02的133同源/测试作用域校验复用；int03新生成132项全部通过545.81秒，17MB成员清单/176MB归档读回后释放约3GB临时目录。当前int04开始。68174最终r7安装身份终态0。全部1110尚未完成，不提前勾选交付。


## r8测试配置修正（业务仍未改变）

29398终态1：int03的132项通过545.81秒并59626成员归档；int04因旧setup helper只给credit_spread提供minimum_spread_width，新增铁蝶正式校验拒绝，1失败32通过。仅扩展该helper为iron_condor/iron_butterfly显式给5，保留全部冻结幂等/完整20候选/账户仅1入金等断言。54334终态0：整个配置模块17项通过36.03秒；26628候选r8构建终态0。

当前58510运行/tmp/lyrax-resume-release-r8.py，20583旧监控等旧终态后已停止/待核验，新监控8442。只允许tests/test_option_setup_v195.py的setup helper变化，AST证明其他定义/导入不变，复用进程没有选择或导入该模块，其余483输入及185应用/C#资源相同。已完整通过UI52/int01 133/int02 133/int03 132共450项作用域核验后复用，整个失败int04及后续660节点全部新跑。原失败整轮仍FAILED。最终完整1110节点和3330阶段未通过前不交付；最新候选release-candidate-r8，安装12197待终态，随后运行/tmp/lyrax-installed-final-r8.py。

最终归档脚本需由/tmp/lyrax-package-validation-r7.py适配r8并包含滚动/结算证明；所有普通wheel193应用/资源字节相同但保留每个真实wheelSHA。不要重跑未变金融操作，不改变旧账本/源hash。
