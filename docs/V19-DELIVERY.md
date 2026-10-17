# LyraX v1.9 工程交付

> **2026-10-14当前验收：** 源码c0a9dcee；804项全量无跳过（3118.10秒）、旧V1/V15/V18入口32/32/34、核心53/模型11/资格12 CLI及恢复通过，329冻结输入复核一致，原82379退出0。16方法目录/只读CLI、空账户4浏览器检查和普通wheel升级通过。7849的真实ETF、清洁环境与完整账户浏览器保留为历史证据；5项目录相关变更外资金/行情/策略/引擎模块哈希未变，当前普通wheel完整四页/重复导入/刷新7项也已通过；未再次在线下载。真实接入/自然周期和条件扩展仍独立列缺口。详见[PROGRESS](PROGRESS.md)。

2026-10-13。**核心编码与本地工程验收已通过；真实接入/自然观察未全部完成，整个计划/Goal仍未完成。**
版本1.9.0.dev0，源码 `7849da9a4ba1765879350d86a6b3bdf0433b8759e76230baf7080f48381f843b`。范围依据主/期权/对冲计划；逐要求结论见[V19-FINAL-AUDIT](V19-FINAL-AUDIT.md)。

## 已实现功能

- 数据用途和资格、窗口缺口诊断、失败/恢复提醒、声明式账单映射预检、版本化协议、备份轮换及独立恢复。
- 归因/滚动比较、双动量、隔离模拟汇总；历史研究与当前账户/资金回报分开。
- 14类期权目录、A8选约/计划/LEAN机械研究、QuantLib情景/定价/压力；标准合约/乘数、统一担保/部分成交/退出/生命周期/凭据审计和异常恢复。
- 股票及期权对冲风险/身份归档、股数或Beta目标、整数数量/预算、压力/同资本研究、父意图/共享预留、阶段计划/修订/关闭/daily和监测。
- 模型Delta逐项时点/年龄/原始文件资格及已锁QuantLib复算；前向初次/缓存冻结及激活重验原快照/来源，防止事后补造。
- 中文四页、账单预检/提交、计划生成/下载/复盘/人工在途管理；没有券商自动下单接口。

逐A/B/HX支持等级见[V19-SUPPORT-MATRIX](V19-SUPPORT-MATRIX.md)。泛用标准腿或目录不表示该策略完整执行能力；READY仅属于通过检查的具体账户和输入。

## 目录补齐前7849同源码验证证据（历史）

以下均绑定7849源码，路径以reports/v19-validation/为根。

| 范围 | 结果 | 证明 |
|---|---|---|
| 全量/依赖/输入 | 802项无跳过，3024.93秒；327代码/测试/配置/样本/锁输入未变 | full-final-20261013-second/verification.json |
| 旧入口兼容 | V1/V15/V18分别32/32/34CLI；旧手算、PIT/研究包/恢复通过 | 主门禁legacy_cli_proofs及三份独立证明 |
| 当前CLI | 核心52、模型11、资格关联12；恢复均通过 | 主门禁core_cli_proof、model-cli-workspace、qualification-cli-workspace |
| 安装 | 新26包Conda+78包wheel哈希依赖；普通wheel132个Python文件指纹一致；独立-I导入/pip check/CLI help/QuantLib通过 | clean-final-20261013-second/verification.json |
| 真实ETF | SPY/IEF/GLD2841行，截至10-12；实际增量同ce6c快照，两次研究指标/CSV完全相同，金融事件0 | online-final-20261013-second/verification.json |
| 完整四页 | 普通wheel实际Chromium完整渲染四页/刷新5检查；中文清晰、无异常/串账 | online-final-20261013-second/browser-complete-verification.json |
| 原生异常恢复 | 17CLI/完整恢复；独立中间-100股、最终5事件/现金100386 | native-final-20261013-second/verification.json |
| 重复账单提交 | 两次上传/预检/提交+完整四页/刷新7检查，5事件hash/现金不变 | native-final-20261013-second/restored/browser-verification.json |
| 实际计划操作 | UI三用途绑定SQL确认；重复同READY/预留9776.5463、JSON/复盘CSV、同步、在途取消阻断、确认后释放0、刷新；金融事件1不变 | plan-ui-final-20261013-second/verification.json |
| 最终交叉审计 | 全部证明同源，327当前文件哈希一致 | final-audit-20261013/verification.json |

实际ETF研究报告：reports/v19-validation/online-final-20261013-second/runtime/demo/reports/research/5b621a58047241d4be34aa090756356a/report.md。
研究资金10000 USD、佣金2bps/滑点5bps/现金利息0均为工程配置；月末收盘后信号、次交易日收盘成交，复权抽象份额不等于实际证券份额，不重复加分红。系统正确性通过不以示例收益高低为条件。

## 启动与复现

完整环境准备见[README](../README.md)和[V19-USAGE](V19-USAGE.md)。主要运行环境为源码checkout中的.conda/v19-clean，普通wheel独立安装证明前缀为.conda/v19-release-install。

```bash
# 项目根目录，完整源码/LEAN SDK及持久A8证据已准备
LYRAX_PYTHON=/mnt/c/quant/project/lyra/.conda/v19-clean/bin/python \
LYRAX_TEST_ENGINE_EVIDENCE=/mnt/c/quant/project/lyra/reports/v19-implementation/multi-native-engine-evidence-20261012/verification.json \
MPLCONFIGDIR=/tmp/lyrax-mpl PYTHONDONTWRITEBYTECODE=1 \
  bash scripts/check_v19.sh
```

此入口已实际执行；默认每次创建新报告目录，先旧入口，再全量/核心/模型/资格CLI。不重用成功目录。看板入口和独立CLI在USAGE/README；本次实际启动普通wheel Streamlit，8514/8515/8516临时服务已停。

完整LEAN工作流使用源码checkout/editable和隔离SDK；普通wheel额外验证覆盖Python安装/导入、理论定价与看板，未打包独立LEAN工程。不能把导入通过当成脱离源码的完整引擎部署。

## 修复及变更审阅

- src/personal_quant/cli.py：对冲两个history局部导入改独立名称，避免遮蔽默认策略signals；新增六个月双策略/12归档/重跑/零金融事件回归。
- hedging/model_greek.py、greek_evidence/service/option_sizing/stage_assessment：完整模型输入和重算资格、单位/原价绑定及必要CLOSE独立检查。
- options/forward.py、activation.py：初次/缓存原始前向快照和来源复核。
- scripts/check_v19.py/sh：持久门禁、输入哈希、零跳过、旧V1/V15/V18前置检查及Linux临时目录；三个旧验证脚本修同目录可写大小写别名。
- 其他已交付模块及详细分批证据保留在PROGRESS历史；本节不是已有用户文件的完整作者归属声明。

默认signals独立1失败后修复，28相关及802通过；旧脚本大写路径只读、样本缺用途绑定、React Aria未展开/未等重跑、Conda/准备目录失败均保留，未隐藏或放宽门禁。早期c9/801等为历史证据。

Git仍main、尚无提交；源码内容指纹及研究归档作为本地基线，未提交/推送/打标签。行情、账单、密钥、数据库、环境、引擎缓存及报告不提交Git。

## 未满足条件与具体输入

真实执行原价/公司行动、脱敏成交/资金/分红/费用/行权账单及同一时点账户快照；选定的合格期权历史/当前源和使用权；券商/账户类型/允许结构/权限、实际合约和履约费用/结算资料；真实月末和完整退出/到期前向周期。

Yahoo Close仍拆股调整口径；原生/模型/固定时钟例子是合成工程样本，不是实际权限或自然paper。缺输入时对应真实计划保持阻断。实际工资/奖金作为入金，真实账户从空账户开始，不采用示例资金。

B1–B5/HX1–HX4完整执行批次仍按条件实施。真实基本面、借券/保证金、期货/动态对冲、多市场/币种、0DTE及V2不在已实现执行能力中；未安装长期调度或上传备份。模型分项token/API/工具实际费用未获取，未购买服务。

自然周期不能通过回拨时钟提前完成。补齐外部条件前，不宣称整个计划或真实期权接入完成。

## 当前c0a9补齐验收（2026-10-14）

804项无跳过（3118.10秒）；旧32/32/34、核心53/模型11/资格12 CLI及恢复均通过，329冻结输入一致；原82379退出0。当前普通wheel目录4项检查及完整账户四页/重复导入/刷新7项检查通过，源码指纹相同，测试金融事件5/现金100386保持不变。浏览器87788退出0，8518服务已停。

证据：catalog-final-20261014/verification.json、catalog-install-20261014/verification.json、catalog-ui-20261014/verification.json、catalog-account-ui-20261014/workspace/browser-verification.json及catalog-audit-20261014/verification.json（均在reports/v19-validation/）。当前安装为原清洁前缀的普通wheel升级；实际ETF下载/干净依赖创建仍引用7849历史证据和精确模块差异。真实期权源/凭据与自然周期未验证，不宣称整个计划完成。

2026-10-14用户要求先跳过真实账号：现新增隔离demo合成历史账户演示，13测试事件/重复导入0、期末100642.7416、6项实际浏览器通过；[模拟操作](V19-SIMULATION-USAGE.md)。本次不修改真实源/权限门槛，不宣称自然前向或真实期权接入完成。
