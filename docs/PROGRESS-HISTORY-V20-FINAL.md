# LyraX 当前进度

2026-10-17，Asia/Shanghai。最新授权：完成v2.0本地P0–P8。P0–P7已实现，P8完整验收仍在运行；**未宣布整版完成**。默认单Agent，不自动交易/购买/安装调度/Git提交。真实账号暂缓。

## 当前冻结身份

- Python3.11.15；应用2.0.0、账本schema5。业务源码`8397988c7915bbc131a14559200a9535e3c879ce93cc6153e0109244873595cc`。
- 候选`reports/v20-validation/release-candidate-r8/`，wheel SHA256`3932d870f48673b5acee5101689915fc73bd324655928c8e66c2ed4840c1649c`。26628构建终态0，12197独立Conda安装终态0；7914最终安装身份检查待核验。Conda前缀`.conda/v20-clean-install`。
- r4至r8的193个应用及随包资源文件逐字节一致，185 Python/C#业务不变；仅门禁/测试/文档/发行元数据变化。原20CLI、只读原生、在线、离线、恢复与浏览器回执准确保留各自原wheel SHA。
- 484受保护输入冻结，完整收集1110节点，最终要求3330个setup/call/teardown均passed、无skip/xfail且当前输入未变。

## 当前运行

| 句柄 | 内容 | 日志/目录 |
|---|---|---|
| 58510 | r8完整门禁续跑，当前int04；已通过450项按作用域/SHA核验复用，其余660全部执行 | /tmp/lyrax-v20-release-r8；reports/v20-validation/release-r8.log |
| 8442 | 30秒空间抽样（非精确峰值） | /tmp/lyrax-v20-release-r8/resource-samples.jsonl |
| 7914 | 已安装普通r8 wheel身份/依赖/仓库外CLI核验 | installed-final-r8.log |

完整阶段：UI52通过182.38秒；int01的133通过813.68秒；int02的133通过576.91秒；int03的132通过545.81秒。各阶段临时目录完整tar读回/成员SHA与链接元数据核验后才释放；原始已验档案在release-r6-test-artifacts、release-r6-resumed-test-artifacts、release-r7-test-artifacts；新阶段放release-r8-test-artifacts。原旧完整产物10.34GB，当前/tmp总7.73GB，分组使临时空间可容纳；含SDK的原始测试归档只本地保存，不分发。

续跑驱动/tmp/lyrax-resume-release-r8.py重新完整收集1110，严格核验当前484输入与候选r8一致。每次仅允许已失败测试模块的隔离函数/helper修改，AST验证其他定义/导入不变、其他483输入与业务全部一致，已验阶段不得选择/导入变更模块；被影响的整个失败进程全部重跑。逐阶段collection/日志/档案SHA核验，原失败/取消整轮保持FAILED；不拿部分失败组充完整成功。所有驱动及新旧SHA/作用域说明随最终证据保存。源码业务一旦变化则不能这样复用。

## 已核实的同业务源码证据

- fast-r4：60通过28.05秒（门禁37.62秒），仅阶段证据，不代替完整回归。
- offline-r4：独立入出金/费用/行动/幂等手算通过，原PASSED_OFFLINE_ACCOUNTING由offline-r4-receipt.json保留原JSON与SHA规范化。
- installed-classic-r4：12公开CLI；installed-quarter-r4：8CLI/3周期/7事件/99633USD；readonly-binding/quarter-r4：Linux真实只读应用/自有适配，8原生CLI通过。补充venv依赖来自独立Conda，不冒充第二完整Conda。
- online-r4：真实Yahoo ETF2853行截至10-16，9CSV固定快照复现；提供商修订新旧快照都保留。
- backup-r4：11CLI，4类财务表一致/7事件，恢复重复不增事件；调度未安装。
- browser主流程11记录动作+窄屏补验；r6实际三周期备兑滚动/终点退出/2024-11-01按已记录SELL结算/重复，COMPLETED、9事件、应收应付0、权益100283；所有临时服务STOPPED。browser-final-r6/r7及滚动结算原始回执均保留，最终需生成r8同源汇总。

## 已修复/保留失败

- Wheel Timestamp/日期字符串比较、未知异常无结构化回执：业务已修，8项164.01秒通过；源码8397988c在此后未改。原traceback、失败setup及最后检查点保留。
- 浏览器下拉选中值实际为input.value，脚本已修；手机过渡帧另补静止窄屏。滚动补验误填2024-01-01被正确拒绝；初步误判业务日历后按原job.through纠正，未改业务日历/账本；正确结算补验已终态0。
- 旧工具搬迁测试残留ROOT/.tools两处已改外部工具；3门禁归档自测+原生搬迁4项93.34秒通过。WSL chmod未实际只读的失败保留，Linux实际只读补验通过。
- int03旧测试硬编码monthly-selection/1.95.2已改为读取冻结2.0.0，并临时篡改当前模块版本证明索引不依赖当前值；保留3实验/观察区间/错误版本断言。40679定向1通过7.19秒；新int03完整132通过。原29398失败保持FAILED。
- int04旧setup helper没给新增铁蝶翼宽参数，被正式校验正确拒绝。仅为铁鹰/铁蝶显式加5；54334整个模块17项36.03秒通过，不弱化完整20候选/幂等/不入账断言。原29398(int03前失败)及r7(int04失败)均保留，不改写成功。

## 下一具体动作

1. 等58510完整终态，任何实际失败先查原请求/输入；不新增功能/改业务。核验7914与监控终态。
2. 全部1110通过后将/tmp/lyrax-v20-release-r8的证明目录逐文件哈希复制到reports/v20-validation/release-r8，保留复用/隔离测试修改作用域、原失败引用。
3. 从/tmp/lyrax-package-validation-r7.py适配r8，打包详细逐阶段日志、CLI回执、截图、报告和从分组档案流式选取的当前四腿证据；不含SDK/数据库/批量行情。源码/wheel及六回执按最终r8绑定，原始同字节payload证明保留。
4. 更新README/计划勾选/支持/迁移/交付/agents/PROGRESS最终真实终态；release_v20 refresh-source→finalize→verify；复制同一产物到release-final并核对SHA256。Git只读检查，不commit/tag/push。

E1真实期权源/权利、E2自然前向/调度安装、E3同账户多策略执行独立未验；多策略仅只读预演。旧pytest -11根因未知，拆进程通过不等于定位根因。GOAL/依赖锁未改，无HEAD。模型/API/工具实际用量与费用未获取。详细历史：[r8前记录](PROGRESS-HISTORY-V20-R8-START.md)。
