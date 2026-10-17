# v1.95开发中入口

2026-10-14。当前为分阶段实现；完整v1.95尚未交付。进度见[PROGRESS](PROGRESS.md)，范围见[计划](lyraX-v1.95.md)。

## 已验证的ETF模拟流程

使用项目独立Conda Python。工作区必须是新目录；相同配置重复初始化安全，不同配置不会覆盖旧账户。示例100000 USD是模拟资金。

```bash
cd /mnt/c/quant/project/lyra
.conda/v19-clean/bin/python -m personal_quant --config configs/demo.toml workspace init --workspace /tmp/lyrax-demo --spec configs/v195-etf-workspace.json
.conda/v19-clean/bin/python -m personal_quant workspace status --workspace /tmp/lyrax-demo
.conda/v19-clean/bin/python -m personal_quant simulation start --workspace /tmp/lyrax-demo
```

将start返回的run_id填入下列命令：

```bash
.conda/v19-clean/bin/python -m personal_quant simulation step --workspace /tmp/lyrax-demo --run-id <run_id> --through 2024-08-02
.conda/v19-clean/bin/python -m personal_quant simulation pause --workspace /tmp/lyrax-demo --run-id <run_id>
.conda/v19-clean/bin/python -m personal_quant simulation resume --workspace /tmp/lyrax-demo --run-id <run_id> --through 2024-12-31
.conda/v19-clean/bin/python -m personal_quant ui --workspace /tmp/lyrax-demo --port 8501
```

创建、重复创建、开始、跨月推进、完成、重复推进及备份恢复已通过公开CLI，证据`reports/v195-validation/complete-etf-20261014/verification.json`；该批源码0595153d。看板四页、跨页保持、重复建立及窄屏7项实际浏览器通过；测试端口8519已停止。后续代码的相关回归单独记录，不能将本批结果冒充最终版本验收。

真实已验证输出工作区：`reports/v195-validation/complete-etf-20261014/workspace/`；账户报告在`runtime/demo/reports/account-latest/`。模拟结算及内部对账明确为工程假设，不是券商对账。

## 期权前缀入口的当前边界

工作区规格将kind设为options，其他字段与ETF模板一致。启动需提供明确的冻结合成请求、LEAN和SDK位置及每合约费用：

```text
lyra simulation start --workspace <期权工作区> --file <冻结请求.json> --engine-root <LEAN目录> --dotnet <SDK可执行文件> --fee-per-contract 2
lyra simulation step --workspace <期权工作区> --run-id <ID> --through 2024-11-04
```

已通过独立测试：SPY保护Put变化路径、200股SPY及50股IEF、2张Put；11月4日权益99994.5，账户4事件（含一次初始入金），同日重跑不新增事件。只向引擎传入截止日期前已知信号和执行价格，核对旧成交前缀后导入新增事实。

当前期权入口属于历史合成前缀模拟；显式plan_policy已接通公共开仓、预留、股票准备和冻结退出，逐日/月末及自然交割已分批验证。默认无plan_policy仍仅研究调度，全部新模板及异常路径的最终门禁尚未完成。本入口不授予实际来源或真实账户资格；期权工作区的旧ETF月度计划入口已阻断，避免混用其样本价格。完整期权工作台仍在开发。

期权引擎股票采用当前合成路径收盘价与配置佣金；期权买ask/卖bid、每张费用显式传入。股票滑点和现金利息在该原生机械模型为0；ETF模拟器继续使用配置的佣金/滑点，不拼接两种模拟的收益。

## 实验与风险图

新增experiment list/clone/compare入口。复制建立新工作区和一次新模拟入金；比较需要独立、完整、相同资金/数据/时间/执行口径及主引擎的运行，有额外资金流时拒绝按研究净值比较。ETF及期权各自主引擎的比较与完整比较包已分批通过，最终整体验收见PROGRESS。

策略研究页面新增“组合风险图：价格、波动率与期限”。标准腿和各腿模型必须显式输入，图形使用现有压力服务；到期Greeks缺失不补零，有限网格不会被称为最大亏损。期末Call样例与手算1800 USD一致；中文表单和便捷模板继续开发。

## 开发验证

`check_v195.py --scope core/native/release --destination <新目录>`保存日志、源码指纹及明确范围；发布组需要原生依赖，跳过测试不会被报告为成功。该入口的基础core范围与新增加的扩展回归分别记录；最终S7还需完整工程验收、安装和浏览器。

已有代码继续使用1.9.0.dev0版本号，最终发布时更新。查看日期与运行日期独立；重新运行旧工作区遇到源码变更会拒绝，应该创建新的独立实验并保留旧证据。

## 本轮扩大验证

feab3009源码：core-expanded-20261014-second为43项，native-expanded-20261014为16项，均无跳过并确认源码未变；首次core-expanded因错误测试文件名未执行，修正后重跑。新买跨式/宽跨式选约、终值情景与两月原生退出已经通过，[规则及边界](V195-OPTION-RULES.md)说明尚未验收的生命周期/计划。随后新增平仓后现金结算，验证证据另记，不包含在上述43/16中。

期权工作区结算新增验证：先step到2025-01-10平仓，再resume到2025-01-13处理已有T+1结算；COMPLETED后相同日期重复不新增财务事实。当前源码原生完整路径+暂停/失败状态2项通过（108.87s），见option-state-native-verification.json；完整v1.95仍未完成。暂停请求可在引擎运行时登记，当前原生计算结束后的账本提交边界停止，不强制中断LEAN进程。

## 新增期权研究报告

买跨式/宽跨式/牛Put信用价差/熊Call信用价差已接入选约和月度原生研究；信用价差额外要求minimum_spread_width。到期政策可显式选择natural_expiry_with_delivery_exit，规则见V195-OPTION-RULES.md。不是READY资格或真实权限。

本批当前C#原生到期21项通过；统一比较报告2项通过，包括牛Put恒价路径亏损56 USD、买跨式显式Put退出路径盈利746 USD，均与独立样本一致。原生引擎/每日账本净值、费用、股票/现金控制和归档重新加载核对通过；证据reports/v195-validation/extended-report-verification.json。报告示例在report-extended-tmp/test_extended_report_loads_and0/compare/report.md及test_extended_report_loads_and1/compare/report.md；这些是测试样本，不表示投资收益证据。

## 自然生命周期工作区

冻结请求可显式增加final_lifecycle=natural_expiry_with_delivery_exit。新options工作区不初始化ETF价格；一份工作区只接受一份冻结运行，修改输入/费用请复制独立实验。自然step截至交易日后的纽约本地午夜，保持事件原时间；截止后不下单，也不补入未来价格。

公开CLI已验11项：买跨式无价值到期到COMPLETED；实值Call在2025-01-17到期交股，2025-01-21按显式恢复政策卖股，2025-01-22按原事件结算到COMPLETED，重跑不新增事件。独立示例终值100871.8 USD，合成demo，证据natural-workspace-verification.json。统一READY计划/预留及逐日检查点仍未完成。

调仓计划/运行状态增加中文生命周期日历、上海截止时间及待结算凭据。没有退出凭据时，超过到期仍显示需核对持仓，不自动写入到账/交割；合约修订的旧零持仓不重复计为新持仓。期权空工作区四页AppTest通过，实际浏览器最终验收待S7。

## 信用价差公共计划（2026-10-15）

牛Put/熊Call已有独立当前原生生命周期资格。公共plan-draft/plan-activate/plan-review/plan-simulate仍使用原v1.9接口和全部来源/账户/资金/对账门禁，不能凭catalog名称激活。demo长腿成交后PARTIAL、短腿后FILLED；未完成预留归零，实际担保9500/11000 USD保留。原生模拟开仓资产99986 USD并可重复，不把信用权利金当利润。信用工作区的自动计划接入尚未完成。

fixture-replay扩展文件格式为selection（原选约请求）、templates（明确列表）、minimum_spread_width（正宽度），配合include-exercise生成完整病例。旧选约文件保持原A8入口。新包装的公开CLI完整验收待S7；已验证的函数/模拟证据见credit-plans-verification.json，不声称已执行全部新命令。

## 双腿买入计划与逐日记录（2026-10-15）

买跨式/宽跨式已有完整原生资格及公共demo计划证据，仍须原有资金/报价/对账门禁。示例预留434/234，双腿不足整包阻断；部分成交只释放对应部分，最终数量完成不表示到期关闭。原生报告导入后权益99986，重跑不会新增事件。

期权step/resume现在将引擎同一前缀的每个交易日独立净值归档为检查点和账户报告；示例48检查点/48报告/13事件。REPORT_PENDING时重跑会补齐缺失日报，再发布最终头，不能因历史日报更新而倒退当前运行。统一工作区的计划预留/退出接入仍在开发。证据vol-plans-daily-verification.json。

## 持续持股滚动研究（阶段实现）

monthly-replay/monthly-compare扩展请求可增加retain_stock=true（必须提供完整合成执行路径）。股票数量各月相同，换期仅平旧期权/T+1后开新；股票仅第一次建仓和最后清理。前缀函数还需rolling_end_session明确最终持股日期。早期本接口拒绝自然交割，现已扩展末期自然生命周期，见下节；完整公共CLI包装验收仍待S7。

三模板及前缀/报告6项分组通过：恒价Put和备兑Call终值99968，Collar99940；股票手续费4而非重复8。滚动Collar比较报告股票控制盈亏-4，策略-60，差额-56；纯现金0。证据rolling-verification.json，均合成机械样例。

## 滚动工作区与Wheel阶段（2026-10-15）

options冻结请求可增加retain_stock=true及rolling_end_session，结束日须和执行路径最后日相同；此时跨月保留股票，推进/恢复/结算使用现有simulation命令。普通平仓公开流程已验：Collar最终99940、11财务事件（资金1、股票2、期权8），重复不变。末期可另指定final_lifecycle=natural_expiry，实际行权/指派按行权价交换股份与现金；未交割的股份在冻结末期恢复日卖出。不再为第二周期重复扣股票买入成本；中间月份仍按平旧期权规则，不宣称覆盖中间提前指派。

已实跑的只读阶段接口：options --action wheel-state --account-id demo-account --as-of 2025-01-13T21:30:00Z --file <参数文件>；参数是underlying、packages、cash_buffer。必须指向已有正确工作区/config，不创建初始资金。CASH等阶段及候选template_id不等于可执行计划；后续原生周期证据见下节，统一计划仍未完成。证据rolling-workspace-wheel-state-verification.json。

## 滚动末期自然交割样例

持续持股末期自然交割的固定合成样例：初始100000 USD、持股100份、股票费用2 bps、期权费用每张2 USD。此前周期股票只买入一次；Put执行价95、Call执行价105。原生与账本核对结果如下，均不是实际投资回报：

| 模板 | 末期股票价格 | 末期处理 | 最终权益 USD |
|---|---:|---|---:|
| 保护Put | 90 | 行权交出100股 | 99372 |
| 备兑Call | 110 | 指派交出100股 | 100582 |
| Collar | 90 | Put行权，Call无价值到期 | 99456 |
| Collar | 110 | Call指派，Put无价值到期 | 100456 |
| Collar | 100 | 双腿无价值到期，恢复日卖股 | 99954 |

工作区Collar下跌样例在2025-01-17记录原生生命周期后保持PAUSED；2025-01-21才按明确T+1假设结算并完成，重复推进事件数不变。验证入口：`python -m pytest tests/test_rolling_natural_v195.py -q`。该入口包含原生引擎，需要已安装的隔离LEAN和dotnet资源。

## Wheel原生与工作区（阶段实现）

冻结单标的请求可指定wheel=true、wheel_end_session及明确每日期权/股票执行路径，固定包数并从CSP开始；原有signals/packages/stock_basket/execution_path字段保留（Wheel股票篮子为空）。期权可逐月CSP/CC切换，CC入口必须有此前真实指派股份。工作区继续用simulation start/step/resume，不自行下券商订单。monthly-replay也已接受该扩展，完整新CLI包装验收仍待S7。

## 工作区公共计划模式（分批集成）

模拟请求增加`plan_policy`可启用公共开仓计划检查。必须明确提供：

- `schema_version=1`，`chain_root`为原完整期权链归档根目录。
- `engine_evidence_files`为模板名到已通过当前C#源码资格的`verification.json`路径映射，包含本次每个模板。
- `risk`包含全部8项：premium_budget、maximum_loss_budget、maximum_notional、maximum_contracts、fee_per_contract、adverse_slippage_fraction、cash_buffer、early_assignment_cash_reserve。费用必须和原生费用一致。
- `reconciliation_max_days`为非负整数。

启动会复制完整链和资格，内容哈希绑定运行身份；推进只读取冻结副本。合成路径的第一报价在收盘前21分钟提供，公共计划在前20分钟激活，成交按收盘记录。该时点安排只描述合成样本，不代表真实日线价格在收盘前已知。内部模拟自检明确标为internal_simulation_check，不是券商对账凭据。

成交、到期、行权与指派按冻结周期及确切合约关联plan_id，复用公共预留和生命周期计算。旧模式名OPENING_PLANS_LINKED_EXIT_FACTS保留；实际退出进度以公共冻结/执行任务为准，详下节。没有plan_policy的旧请求仍标RESEARCH_SCHEDULE_ONLY，不能据旧研究流程宣称已经有公共计划。

未指定延期配置时，公共激活仍只允许首个适用交易日。模拟plan_policy可额外指定正整数execution_window_sessions，例如5；实际开仓日按当前周期明确写入execution_window审计，不改月末信号。窗口不能跨适用月份，每份计划valid_until仍为其当日收盘，报价必须重新核验；paper/real明确拒绝此扩展。

已验证的普通两周期CSP因T+1于2024-12-03开第二期，原冻结信号适用日仍为12-02；期末99972，2计划/5账本事件重复不变。窗口长度不是等待授权，超过时窗不能补造事前决定；所有时点为合成机械演示。股票公共计划和独立退出仍待接通，不能通过回填股票、放宽真实门禁或把激活移到成交之后绕过。

已验两月原生及工作区：11-04开Put前缀、11-25已接股前缀、12-19完成第二期指派、12-20按明确事件结算到COMPLETED；期末101196、5事件，重跑不变。未指派续Put例100196；错误CC候选与不足现金阻断。均合成样本，不代表真实收益。证据wheel-native-workspace-verification.json；统一计划/担保及未覆盖的异常/部分指派仍待实现。

## 首次股票准备（分阶段模拟）

原生回放、比较和工作区请求可增加prepare_stock=true，同时必须启用retain_stock=true并提供完整合成执行路径；不和Wheel混用。准备日在原适用交易日收盘按明确数量买股，首次期权开仓推迟到下一交易日。之后跨月保留股票，已有滚动现金等待规则继续适用。公共计划模式还须明确配置execution_window_sessions来允许延期。

原生引擎在期权提交前检查实际持股数量，没有足额股票则失败，不用计划数量替代实际覆盖。前缀推进到准备日只产生股票事实，尚无期权成交或公共期权计划。首次买股使用准备日价格及费用；股票/现金控制组使用相同准备日和观察区间。

固定样例100000 USD、100股、股票2 bps、期权每张2 USD：2024-11-01按99买股，11-04才开期权。准备日权益99998.02；两个正常滚动周期完整原生权益为保护Put/备兑Call100068.02、Collar100040.02。同政策股票控制组100096.02，现金100000。所有数值为合成机械核对，不能解释为真实策略收益。

股票准备与末期清理现使用独立simulation_stock公共计划，复用预留、部分成交和事实投影；检查配置中的现金缓冲、仓位上限、交易单位及占用。不得把它当作股票alpha信号，界面也不提供月末策略修订入口。

最新固定样例在2025-01-10关闭末期期权，01-13才清理股票，01-14结算到COMPLETED。保护Put/备兑Call各7条账本事实、Collar11条；各有2份股票计划，重跑不变。23项规则/原生/完整工作区/UI/备份/旧回归通过，证据stock-stages-verification.json。部分买入40股后恢复备份，剩余60股预留5944.158不变；重复导入不入第二次账。

自然交割组合下的分日清理及其余S6/S7仍待验证，不能把这些固定样例当作整个v1.95验收。

## 独立期权退出任务（已接入普通平仓）

公共计划模式在CLOSE前以当日合成参考报价调用现有退出预检/冻结接口；以实际原生成交逐条推进，核对确切月度信号、合约、订单事件、数量、方向、费用和成交时点，并验证归档源码与DLL。保护腿必须等待短腿实际关闭；部分退出只保存进度，担保依实际剩余持仓计算。显式取消后不能继续模拟未执行退出，已入账事实保留。

全部冻结数量关闭后，才写option-exit-simulation完成审计；它表示退出事实已确认，未结算应收应付继续显示。普通两周期Collar样例有2份退出冻结、2份完成审计，11条账本事实，01-14结算权益100040.02；重复推进不变。42项分组检查及完整备份恢复通过，证据option-prefix-exit-verification.json。归档校验同时覆盖运行内plan-chains和实际前缀凭据。

自然到期/行权/指派按生命周期事实处理，不虚构市场平仓；部分退出备份专项及剩余故障场景继续验证。没有任何券商订单提交。

## 自然交割后的分日清理（已验证组合）

prepare_stock、retain_stock、final_lifecycle=natural_expiry可组合；固定样例需把完整执行路径及rolling_end_session延长到2025-01-22，不能缺价后自动补齐。期权自然恢复日为01-21；只在实际仍有股票时于01-22卖出，卖出款按示例T+1于01-23结算。

5条原生及2条完整管理检查通过，见prepared-natural-verification.json。下跌Collar通过Put实际交出股票，最终99556.02，仅原买股计划；平价Collar双腿无价值到期，另有清股计划，最终100054.02。均只有前一周期普通平仓的1份市场退出完成任务，末期使用2条自然事实。重复推进不增加账目，所有金额为合成核对。

## 模拟源码与环境归档

新启动的ETF/options运行保存到runtime/demo/source-archives/<source_hash>，包含完整Python和5份依赖/发布锁；simulation-source审计绑定清单及实际Python、核心/可选包版本。继续运行前核对归档与环境，变化时拒绝执行，要求恢复原环境或建立独立实验。源码绑定与运行注册同事务，失败不会留下已登记却缺运行的审计。

备份恢复保留该引用；删除已绑定归档后备份会明确拒绝。历史数据读取不要求当前环境版本等于旧环境，继续执行仍须匹配。校验仅读取归档，不自动执行其中代码。

wheel包含share/lyrax/locks；归档器读取实际导入的package和安装前缀锁资源，支持仓库外启动。已验证最新wheel在新venv中实际从site-packages导入，仓库外创建/启动/推进ETF，合计9项分组检查见simulation-source-verification.json。本次venv共享base依赖，完整依赖清洁安装与期权适配器/工具资源部署仍待验证，不能据此宣称整个S5完成。

## 期权wheel资源（分批已验证）

wheel包含自有C#适配器项目和源码，安装资源位于`sys.prefix/share/lyrax/lean-adapter`。构建只写运行输出目录下的source/bin/obj，支持包资源只读和含空格的输出路径；资格核验读取同一资源版本。外部LEAN固定提交及.NET10.0.100须单独准备并显式指定，未随wheel分发。

仓库外新venv实际Collar回放与资格检查已通过，见`reports/v195-validation/native-wheel/verification.json`；该环境共享base依赖，因此不是全依赖清洁安装验收。最终发布前仍需重建当前源码wheel并完成完整安装门禁。

## 外部LEAN/SDK迁移（编码已接通，实际迁移验证中）

新期权运行保存工具内容清单。恢复到另一机器或目录后，首次向前推进同时显式传入两个新路径：

```text
lyra simulation resume --workspace <恢复工作区> --run-id <原ID> --through <下一交易日> --engine-root <新的LEAN源码目录> --dotnet <新SDK目录/dotnet>
```

工具内容、固定提交、SDK版本与原清单一致才保存新路径映射；以后推进使用该映射。不会改写原settings或run_id，也不会复制/重复初始入金。版本或任何被绑定文件改变需恢复原资源或建立新实验；只给一个新路径会明确报错。旧报告/备份核验只读取归档清单，不要求旧机器路径仍存在。工具扫描在本机约70秒，运行期间等待任务结果，勿重复提交。

该迁移命令是新编码接口，最终可复制验证状态以PROGRESS及原生日志为准；不将规则测试等同于实际机器搬迁成功。

## 实验索引、批注与完整导出（2026-10-15分批已验）

目录请求JSON示例（只读取显式目录，最多100项）：

```json
{"workspaces":["/tmp/lyrax-demo","/tmp/lyrax-options"],"filters":{"kind":"options","status":"COMPLETED"}}
```

可选筛选为kind、status、template_id、data_type；无效/不存在工作区逐项显示错误。统一公平compare支持ETF或含期权LEAN实验；同次比较不能混用两种引擎。期权需相同完整行情世界、版本/时点/成本；缺新资源绑定的旧报告不自动升级资格，目录也不是公平排名。

```text
lyra experiment list --file <目录请求.json>
lyra experiment annotate --workspace <工作区> --file <批注.json>
lyra experiment export --workspace <工作区> --run-id <ID> --destination <新的空目录>
```

批注JSON为`{"run_id":"<ID>","request_id":"研究目的-1","note":"机械验证目的及参数依据"}`。相同请求重跑不重复，不同内容沿用同ID会报错。批注不改变现金/成交/持仓。完整导出是经过验证的模拟账户备份，包含数据库、冻结规格、源码与引用，可用既有restore恢复；不是默认诊断包。公开annotate/export已实跑，见experiment-cli.json。

策略研究页面的“独立模拟实验目录”可读取和下载索引；已提交路径/筛选跨页保持。索引下载不含数据库或完整行情，不可当作备份恢复。后台继续任务主动勾选“更换外部引擎路径”才传递上方两条新路径，否则沿用已绑定路径。规则、导出恢复及AppTest已验，实际浏览器最终验收仍待。

## 统一期权比较与可恢复比较包（2026-10-15已分批验证）

比较清单为2至7个独立工作区：

```json
[{"name":"保护Put","workspace":"/tmp/protection","run_id":"<ID>"},{"name":"Collar","workspace":"/tmp/collar","run_id":"<ID>"}]
```

```text
lyra experiment compare --file <比较清单.json>
lyra experiment compare-export --file <比较清单.json> --destination <新比较包目录>
lyra experiment compare-verify --source <比较包目录>
lyra experiment compare-restore --source <比较包目录> --destination <新恢复目录>
lyra experiment compare --file <新恢复目录/request.json>
```

5条公开命令已实跑，记录`reports/v195-validation/comparison-cli/verification.json`，实际示例包在同目录package/。完整包带独立模拟账本、规格、源码和引用；恢复不重放初始入金。原路径改写为恢复后的工作区，曲线、费用和执行口径须一致。SDK/LEAN仍为外部工具，不随包分发，也不需要运行引擎来查看/校验比较。

保护Put/Collar同一完整链与价格世界的实际例子为100068.02/100040.02 USD，不是投资收益证据。不同模板的请求应共用全量价格世界；引擎只收到该时点可知且已选合约。相同资金下的不同包数可以比较，不同费用会明确拒绝公平比较。原生买卖价差已在净值中，bid_ask_cost只是解释，不能再扣一次。

目录新增strategy_version、source_hash、start_on_or_after及end_on_or_before筛选；日期为YYYY-MM-DD。已有检查点按实际观察区间，否则显示配置区间；未产生ETF信号时显示尚无规则记录。策略研究页提供中文权益/回撤图及费用表，显式点击才比较；下载JSON含曲线/口径/引用，完整恢复应使用compare-export包。AppTest已验，最终实际浏览器仍待S7。

## 同资本风险对照与逐腿Greeks（2026-10-15分批已验）

策略研究页有“同资本保护Put、Collar、持股与现金”中文表单。示例为纯理论工程假设，不读取实际行情，也不生成账户或调仓计划；每包100股，持股基准为同股数加余现金，非全仓股票。

```bash
.conda/v19-clean/bin/python -m personal_quant --config configs/demo.toml options --action risk-compare --file configs/v195-risk-scenario.json
```

命令已实际验证，输出示例`reports/v195-validation/risk-controls-cli-output.json`，CLI证据risk-cli-verification.json；当前测试还验证同一公开解析入口。

| 参数组 | 约定 |
|---|---|
| initial_cash、stock_price、packages | 共同资本、每股参考价、每包100股和1张期权 |
| put_premium、call_premium | 每报价单位USD，实际一张乘100，不是已经乘好的总额 |
| fee_per_contract、stock_commission_bps | 每张建仓费用与股票佣金bps；1bp=0.01% |
| maximum_premium_budget | 长Put权利金及全部期权费用预算，短Call收入不抵扣此预算 |
| style、volatility、rate、dividend_yield | 欧式/美式模型与比例参数；0.2表示20%，不自动推断实际合约条件 |
| valuation_date、expiry、horizon_date | 显式模型日期；压力时点不得越过未观察履约路径的到期日 |

初始示例资本20000、100股、Put95/Call105、权利金2/1及显式费用，在压力价80/100/120到期时：保护Put盈亏-704/-204/1796，Collar-606/-106/394，同股数股票-2002/-2/1998，现金0；均为假设情景，非回测收益。权利金/费用只扣一次；剩余现金利息0，不计期末真实成交/税费/滑点。连续分红率仅用于期权模型定价，未给股票/现金控制补造分红现金流；组合离散分红路径未支持会明确报错。

高级组合表单及对照均显示逐腿/组合Greeks、数量/乘数、完整性和单位；Vega/Rho为1个百分点，不是100%变化。到期未知Greeks不填零。有限网格最差结果不能作为理论最大亏损或风险保证。

结果带完整输入、源码/QuantLib版本与精度身份。无效提交清旧结果，跨页保留已提交参数；模型/依赖/缓存输入变化要求显式重算，不在刷新时运行模型。JSON下载保留当次身份，不冒充最新模型或真实报价。数值/缓存/AppTest已验，最终实际浏览器仍待S7。

## 中文合成期权配置向导（2026-10-16，公共原生恢复仍在验）

无需手写信号JSON，可先建立新的模拟期权工作区：

```bash
.conda/v19-clean/bin/python -m personal_quant --config configs/demo.toml workspace init --workspace /tmp/lyrax-options-demo --spec configs/v195-options-workspace.json
.conda/v19-clean/bin/python -m personal_quant simulation prepare --workspace /tmp/lyrax-options-demo --file configs/v195-option-setup.json
```

初始化+prepare已实际运行，记录`reports/v195-validation/option-setup-cli-flow/verification.json`。运行入口仍使用已验证的`ui --workspace`；进入“期权模拟配置”可选择12类月度模板、标的、包数、费用、DTE、价内外比例、报价质量与退出规则，明确区分仅研究调度/公共计划。

向导生成固定两月synthetic输入：2024-10/11月末决定、2024-12/2025-01到期，标的恒100和固定合成期权价格。NYSE日历是真实市场日历，报价和合约条款是虚构的，不证明实际合约、行情权限或投资表现。更改参数生成新配置，不改旧信号。已启动工作区若要更换运行规格，应复制新实验。

界面点击“后台冻结合成配置”，等任务成功后“核验并使用该配置”，再填写本地LEAN/SDK并“建立模拟运行”。准备和启动均走持久后台任务，状态只轮询回执，不在刷新时调用引擎。默认研究模式不生成公共计划；公共模式须该模板当前源码的合成生命周期资格、完整风险参数和至少2交易日窗口。资格不是券商/真实来源权限。

默认保护Put例先推进到显示的最后行情日2025-01-13，再到最后结算日2025-01-14；查看日期不会推进。研究模式当前原生重跑已到99978/7事实；公共模式备份恢复/周末截止的重跑尚未结束，以PROGRESS为准。冻结请求已绑定费用，不能在启动框悄改；文件修改或源码变化会明确拒绝。

状态页区分期权原生输入与不需要的ETF用途；ETF状态只展示登记元数据，未借此宣称实时行情/内容重新通过检查，实际执行仍运行完整质量/新鲜度/权限门禁。完整原生/发布测试默认将大型临时目录放在报告磁盘，可用`check_v195.py --temp-root <大容量目录>`显式选择，避免有限/tmp内存盘被写满。

## 原生部分指派故障场景（分组验证中）

冻结合成研究请求可加`assignment_scenarios`，每项包含`contract_id`、`session`（YYYY-MM-DD）和正整数`quantity`；只能是冻结空头，开仓后退出/到期前的交易日。仅支持原生前缀研究，不与`plan_policy`混用；公共计划资格不会因该故障场景自动放行。

发生部分指派时，应查看实际剩余期权、股票和结算。Wheel还有Put义务时不进入Call；覆盖不足或待核实行动会阻断后续执行。失败尝试的`engine-events.json`保留已发生的原生事件；它和最后成功检查点分开，失败输出不会自动冒充已记账事实。

当前新26项关联状态/资金/诊断回归通过（338.11s，assignment-associated.log）；原生恢复和异常场景以PROGRESS终态为准。所有合成资金/合约均非真实行情或账户权限。

## 构建缓存与脱敏诊断

可显式设置`LYRAX_ADAPTER_CACHE=<自己可写的缓存目录>`。每次核对C#、SDK版本/编译器、LEAN引用DLL和缓存产物哈希；相同输入复用构建产物，每次业务路径仍独立运行引擎。缓存损坏会明确失败；保留旧目录并指定新目录，不直接执行损坏产物。不设置时继续独立编译，普通wheel资源无需写入。

`lyra workspace diagnostic --workspace <工作区> --destination <新的运行目录外路径>`导出diagnostic.json及哈希清单。运行状态页可点击“准备脱敏诊断”下载JSON；显示准备时间，不自动重跑引擎。仅白名单版本、状态、数量和输入哈希，不包含原始账单、数据库、配置值、自由错误文本或密钥；它不替代可恢复备份。调度安装仍明确未核验。

当前已验证6项维护及11项界面/后台回归；实际浏览器和最终同源码验收独立进行。

## 完整备份核验与隔离恢复记录

```text
lyra workspace backup-review --workspace <模拟工作区> --source <完整备份目录>
lyra workspace recovery-drill --workspace <模拟工作区> --source <完整备份目录> --destination <新的隔离目录>
```

也可在“运行状态 → 备份核验与隔离恢复演练”显式操作。备份必须属于当前工作区；每次实际完整核验登记独立操作时间。恢复复制原有事实，不再入金。界面平时只读取历史记录和清单身份，明确标注“本次未重验全部内容”；引用缺失/变更会显示，不能沿用旧验证声称当前完整。

记录在runtime/demo/maintenance/receipts，随下一次完整备份保留。外部备份本体不递归打包；移机后历史记录仍保留，其引用可能需要重新核验。若恢复完成后记录落盘失败，返回VERIFIED_RECORD_PENDING，目标目录已经存在；请保留它并检查存储，不覆盖重做。调度安装状态独立为UNVERIFIED。

已有备份轮换继续用backup-maintenance的list/preview/create、keep和protect；只轮换显式目录的完整备份，行情/研究快照不按文件年龄自动删除。默认先预览，明确选择create及保留参数才执行轮换。
