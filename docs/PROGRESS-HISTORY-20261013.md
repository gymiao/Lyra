# LyraX 开发进度

## 恢复摘要（2026-10-12；v1.9仍进行中）

股票单位重规划已实现独立入口、行动双向核对、组所有未成交方向一起替换、已完成阶段的单位展示、原 native/历史切片、单次关闭义务及固定窗口。aad6016b983cfd54bab5030b562efdbc80dd7442eaed38e004fcceecdd580b3d源码44项单位/旧组（183.44秒，stock-unit-final-fifth-check.log）+33项股票计划/阶段（215.30秒，stock-unit-stage-final-check.log），共77项无跳过通过。公开40条CLI/完整备份恢复通过（stock-unit-rebase-cli-20261012-third/verification.json），其源码早于最后损坏时点诊断修复，独立保存，不声称最终全量。同资本往返最终持仓200、现金19393.70、权益31393.70；部分CLOSE后拆股现金19393.98独立验证。

通用CLI/看板/daily及options CSV逐凭据审计79项、原生17CLI及7浏览器为6af81084历史源码；当时demo原5笔事实/现金100386不变。旧8506服务已停。/tmp/lyrax-generic-csv-receipt-third-20261012已按已终止79回归记录清理，日志和CLI/浏览器证明保留。

多期权标的共享月度现金/身份键、自然生命周期及报告/UI已通过阶段验证。当前40c653f0f9b59ef4a6933bcfb40b8bf842ad93f0a07269817dfb5e5f3a58e42b源码42项无跳过（386.92秒，multi-option-final-check.log）及公开5CLI/完整恢复（multi-option-cli-20261012-third/verification.json）通过；SPY/GLD同规格Put、两期不同张数、IEF篮子，手算终值现金100518.834000，研究账户金融序号0。首轮兼容12通过/1失败定位独立指标只需最小合约描述却强制全条款，改为精确描述匹配；真实成交仍完整校验条款，歧义不得猜测。

修改C#后已实际重跑全套A8机械生命周期，8模板全部PASSED；multi-native-evidence-verification.json指向/tmp/lyrax-multi-native-20261012/engine/verification.json。旧A8证据保留为历史，不作当前适配资格。上述进程全部结束，无活跃任务。下一项证券/行动/来源/权限关联及分操作风险门禁，随后P5/O6/H5最终统一验收。真实来源/券商/自然前向条件独立受阻；Goal active，完整v1.9未完成。

## 来源关联与分操作资格（2026-10-12进行中）

2026-10-13隔离集成续验：独立复现激活缓存归档改变后仍返回旧BLOCKED审计（1失败/14.48秒，forward-cached-activation-before-tmp-20261013）。隔离options/forward.py新增verify_registered；首次及缓存激活重验同账户归档、原报价/采集清单和决策时点来源资格，自洽伪造来源的首次请求也保持BLOCKED。最新隔离c9ece734185cdd3410dd497325409fe7023f1695f34ffb170f9c2732dcde993e源码54相关无跳过通过（68.77秒，model-forward-staging-final-20261013.log；完整READY备份正向另验），新增正/负2张模型Delta独立2项通过；同源码11公开CLI/完整恢复通过（model-forward-staging-cli-20261013-second/verification.json），金融序号0/test仍UNQUALIFIED。两组已终止。原50回归93251仍活跃；新的隔离READY/完整备份正向2335正在运行（model-forward-staging-positive-20261013.log），隔离根仅复制当前3个C#/csproj文本以核对已有A8归档，未重跑LEAN。当前src仍b5a34f72，不宣称改动已交付。两组终态后待发布文件共7个：hedging的model_greek.py/greek_evidence.py/service.py/option_sizing.py/stage_assessment.py，加options的forward.py/activation.py；随后核对相同c9ece734指纹并运行必要专项及最终统一验收。

2026-10-13模型Greek隔离实现：原50回归句柄93251仍存活，原业务源码保持b5a34f72；在reports/v19-implementation/model-greek-staging-20261013/src副本中补完整模型输入资格。输入逐项保留值、来源、观察/发布/收到时点、显式最大年龄和原始文件；确切合约/整数张数/位置Delta只归一一次，核对QuantLib版本、engine和pricing.py哈希，固定相对容差1e-8重算；模型标的原价须等于当前冻结估值。复用Greek登记/核验及OPEN阶段，必要CLOSE保留既有完整估值/直接情景门禁。隔离源码a63a027d1867f6a9e51803c68fb8df45ce34e253c1427dd2fd0d266be7cafe4b的48项相关无跳过通过（65.61秒，model-greek-staging-fourth-20261013.log），11条公开CLI/完整恢复通过（model-greek-staging-cli-20261013-first/verification.json）；测试Greek为UNQUALIFIED、金融序号0。恢复样例前两次失败为测试误读恢复包数据库位置/元数据，修fixture后通过；未放宽业务门禁。当前只隔离副本已实现，尚未发布到src；等93251原50回归终态后复制5个已测hedging文件并验证指纹/专项，随后文档及统一P5/O6/H5继续。

2026-10-13恢复运行：暂停/恢复后准确句柄93251仍存活，最新50项前向/激活/退出/daily/阶段回归继续原进程（forward-regression-final-20261013.log），没有因等待或暂停另起重复回归。原核心离线CLI句柄38238已退出0，52条CLI全部PASSED；同b5a34f72源码证据reports/v19-validation/73e3b671be714bb9bd32a5a3fe1dab5c/verification.json，手算现金598、SPY4、权益998。50回归仍待终态。全仓实际收集785测试；统一P5/O6/H5还需对应最终源码完整证据。模型Greek的完整输入/模型/重算资格是下一项明确代码缺口，当前模型值仍供研究。

模型Greek新增7项独立验收样例，test_hedging_model_greek_v19.py：欧洲Call用解析Delta公式构造预期，并覆盖未来/缺失输入、错误乘数、模型源码哈希、伪造Delta和测试凭据不能授予实际资格。首项实际失败INVALID_GREEK_EVIDENCE（3.42秒，model-greek-before-tmp-20261013），确认当前接口仅接受供应商值；业务尚未补模型入口。为保持正在运行50回归的源码一致，此时只新增测试，不改业务源码。最新轮询93251仍活跃，日志17进度点；下一动作先等该原句柄终态，再实现完整输入时间/原始文件/模型版本及固定容差重算资格，复用现有Greek登记/核验和阶段门禁。

2026-10-13重跑冻结任务修复：已有月度归档过去只验内部哈希，同一任务重跑会返回重哈希伪造采集时间的旧文件。新独立样例先复现1失败（forward-cached-tamper-before-tmp-20261013），现在复用原期权链及决策时点来源资格复核后才返回缓存；伪造采集时间或资格均拒绝。最新b5a34f7290ce3e9ab237c39e14d99644b860018191a9502d879576d52ca7d312源码3项相关专项无跳过通过（10.32秒），公开CLI过期请求拒绝及金融序号0通过（forward-gate-cli-20261013-fourth/verification.json）。此前完整正向包的1519文件备份校验为修复前187b3ff8源码；新源码全量、浏览器和真实前向资料仍待。此修复不创建真实订单或补造历史信号。

2026-10-13前向归档补强：激活与备份均重开原期权链，核对清单真实采集时间、报价接收时间、所选合约条款及当时可用报价；不只信任已重哈希的信号字段。旧正向包1519文件按最新源码`verify-backup`为SUCCESS（option-forward-backup-reverify-second-check.log），重哈希伪造快照采集时间专项1项通过。当前源码指纹187b3ff8a7ff9f4f725f73ef884bc0f076c7b7c74f5f4bd0305a48d0dadb49e6，同源码公开CLI过期请求拒绝通过（forward-gate-cli-20261013-third/verification.json）。50项兼容回归进度5点后人工中断，退出130（forward-regression-20261013.log），未出最终汇总，不能计为完整通过；其单项备份较慢，后续验收需重跑。外部真实期权链、券商许可、自然月末周期和最终P5/O6/H5仍待；不标记v1.9完成。

期权前向schema2入口已编码：paper/real账户月末信号必须在真实市场日历收盘+发布延迟后的显式短窗口生成，链快照的采集时间不得早于其中任一报价收到时间，来源及合约单位须在决策时点取得实际资格。历史schema1不可作为前向激活；激活核对同账户本地冻结归档、之后生成的草案、次日新报价、引擎、期权来源/权限、对账及资金，READY仍仅为人工计划。隔离冻结时钟paper正向4项聚焦测试通过（含旧历史paper阻断；option-forward-activation-tmp-second-20261012）；前向READY与大体量引擎凭据完整备份/校验/恢复独立1项通过（399.04秒，option-forward-backup-first-check.log）。备份增加前向归档来源资格独立重算后，旧正向包按当前源码再校验SUCCESS（1519文件，option-forward-backup-reverify-check.log）；自洽重哈希但伪造来源资格的包被CORRUPT_FORWARD_SIGNAL拒绝（1项12.92秒）。公开CLI误过期请求按MISSED_FORWARD_WINDOW拒绝，账户金融序号0，forward-gate-cli-20261012-first/verification.json；该CLI为较早249f源码，末次7e0c27abb0791e9da425ad196d185649e8ff3abbf0233aced235487255d6b587源码仍需统一回归和CLI。自然月末前向周期及真实来源/券商凭据仍未取得；本批尚非最终P5/O6/H5验收。

逐笔供应商Greek资格已接入：新增greek-register/greek-assess、不可变观察值与供应商原始文件哈希、确切合约条款和知识截止内最新结论检查。风险归档携带每个已有期权头寸资格；非demo新增OPEN复核头寸与Beta目标候选逐腿Delta，冻结审计再核对凭据文件与当前适用决定。模型Greek继续研究专用，必要CLOSE不因缺Beta/Delta被伪装为OPEN。最新3cd387577c0b06b322311a87b98deebd54572da955f4949f5dd7a58369cb2d61源码36项Greek/阶段/压力/操作相关测试无跳过通过（55.38秒，greek-stage-third-check.log）；同源码12条公开CLI及完整备份/校验/恢复通过（qualification-links-cli-20261012-third/verification.json），demo账户金融序号0，测试来源/权限/Greek均按预期保持未获实际资格。隔离paper型实际凭据样本包含合约单位文件篡改拒绝，仅是工程fixture，不代表真实数据。最终全量P5/O6/H5未验。

新增security-assess只读关联：明确证券版本/稳定ID、原价快照、账本前缀及知识截止，解析不可变来源凭据和实际活动行动引用；最新已知撤销不能被旧合格引用绕过，未来登记不影响历史核验。非demo阶段须覆盖实际持仓和交易工具，父决定可显式增加tool_security_ids/tool_security_versions而不改变保护scope。

必要CLOSE允许Beta/Delta模型缺项降级，保留完整原价/期权估值、权益、资源、账务及情景检查。无Beta时只接受明确的逐标的价格情景（benchmark_return×beta_multiplier=0）；非零基准贡献仍须合格Beta，绝不补零。OPEN保持原风险门禁；非demo新增对冲使用期权Delta需独立Greek资格。

新增options permissions-register/permissions-assess：复用现有资格归档，限定账户/环境、A8模板、OPEN/CLOSE/EXERCISE/ASSIGNMENT、现金无保证金、张数/实物资金和退出期限。测试凭据不获实际资格；仅审閱证据，不授予券商下单权限。实际期权激活动态评估来源及权限，仍须合格前向信号；阶段审计/恢复重算冻结资格。

本批第一专项1失败（14.85秒）为新身份登记后测试仍用登记前截止；修正测试时钟，10项无跳过通过（10.65秒）。权限第一扩大9通过/1失败（14.45秒）为测试备份目录未遵循runtime/demo配置；修fixture为独立运行目录，74项相关无跳过通过（60.43秒），其源码早于最后阶段权限/CLOSE重规划复用。

961544449418271734409cbefd39348c312e83108850fc9ecceb5481240b6bda源码公开10CLI及完整备份恢复通过，qualification-links-cli-20261012-first/verification.json；全部synthetic/test，账户金融序号0，证券BLOCKED/权限UNQUALIFIED符合独立预期。第三扩大36通过后因/tmp Errno28失败（28.86秒），不是业务验收；仅清理已终止的本轮first/second/third测试目录，日志和引擎凭据保留。第四同源码扩大回归112项无跳过通过（1589.39秒，qualification-permissions-fourth-check.log），session76427已结束；basetemp改工作区reports/v19-implementation/qualification-permissions-fourth-tmp-20261012，避免/tmp容量不足。

H-T28新增独立完整组/账本/阶段审计/备份恢复1项通过（15.57秒，close-without-beta-first-check.log），与最新96154444源码及10CLI一致。原SELL40已结算，基准零方差导致Beta保持缺失；CLOSE用显式SPY -20%情景，检查所需现金4002.8和端点权益28800/27997.2，再导入BUY40/费2.8，最终股份100、现金19997.2、权益29997.2，序号4、组完成。原风险仍INCOMPLETE/beta_amount=null；恢复后原阶段审计重算通过，没有补零Beta或自动下单。第四扩大句柄76427仍活跃，NTFS引擎凭据/备份复制较慢；不用等待超时重启进程。

当前A8机械凭据已复制到持久报告目录并8模板重新评估PASSED：reports/v19-implementation/multi-native-engine-evidence-20261012/verification.json，校验multi-native-durable-evidence-verification.json。复制句柄18566已终止。112项通过后发现父决定额外对冲工具的身份/版本映射在输入类型错误时可能抛Python TypeError；已增加显式映射/键/版本对应检查与拒绝测试。来源凭据登记内容畸形现给稳定CORRUPT_SOURCE_EVIDENCE；保留SOURCE_NOT_KNOWN专门时点错误。最新3e927e79bfeb0de8971883b163a56a500ebc1efcc7fb972ac6a3711a7956d20e源码两文件20项无跳过通过（33.90秒）。首轮相对basetemp落入物理大写只读路径导致16项setup错误；单边工具映射预期码及QuantError继承ValueError引起的误包裹均由专项失败定位并修正，未发现账务写入。112项及10CLI属于修复前指纹，不能冒充最新全量。下一项Greek来源/模型资格，然后最终P5/O6/H5统一验收；真实资料和自然前向独立受阻，Goal active。

## 股票单位重规划批次记录（2026-10-12）

新增hedge-stock-unit-rebase独立入口：必须显式列已入账SPLIT事件/序号/内容哈希、当前风险及原组/资源版本；只生成DRAFT，不预留或写成交。纯股票组限制保留，不能缩放期权交割条款。逐笔成交按自身单位时点换算，原价公司行动与凭据比例/日期独立核对，零碎剩余不截断。

组修订需一次替换全部受影响未成交方向（含CLOSE），已完成阶段只转换展示单位、不重新开仓。native_lines保留原冻结数量，unit_basis明确修订时点/序号，历史事实切片与单次关闭义务共同守恒。共享progress按对应单位重建成交/结算依赖。

历史本批：首轮44.31秒失败定位后续普通报价修订误拒历史切片继承单位基准，已改为逐项核对原基准。第二轮1通过/1失败75.21秒为全成交fixture错误调用cancel，原系统正确FILLED_PLAN拒绝，修fixture。第三轮4通过/1失败116.39秒为来源行动缺失先触发数据质量门禁，改用能独立到达行动核对的样例。第四轮27项通过285.28秒（1条fixture pandas类型警告已修）；额外部分CLOSE后拆股1项通过49.56秒，stock-close-split-first-check.log。第一轮CLI完成财务序号6/现金19393.700/股份200.0，但脚本字符串200.0!=200误断言，改用Decimal；未完成备份，不能称完整CLI通过。

新增行情/账本行动集合双向核对后，扩大命令误写不存在test_hedging_stock_activation_v19.py，仅收集错误，无测试运行。第二扩大批进行中时，独立旧格式探针实际复现缺snapshot序号KeyError（1失败16.40秒）；主动停止扩大批和第二CLI（两者130终止），修为保留未知序号None、不虚构前缀，同一时点拆股仍拒绝不明顺序。

当前扩大回归stock-unit-final-third-check.log，session29953；第三轮实际公开CLI在独立demo新工作区验证，stock-unit-rebase-cli-third-check.log，session69702。两者正在运行、源码冻结，结束前不编辑src。早先27/1属于行动双向/旧格式兼容修复前源码，不称当前最终验收。后续多期权标的/资格联动及P5/O6/H5仍待。

## 当前批次：旧账本迁移、零现金模拟与股票审计（2026-10-12）

- 实际CLI第三轮暴露复制的旧schema1尚未显式升级；改用公开v19-init（包含完整备份）。第四轮暴露原风险缺少option_positions与升级后空字段不兼容；只接受独立重建为空的缺字段，显式null/非空仍拒绝。专项迁移1项通过（18.39秒），原归档保持不变。
- 第五轮脚本忘记hedge-exposure --archive，第六轮NTFS.resolve转成只读大写路径，均改脚本。第七轮实际复现模拟器零现金卖出被负买入预算误阻断，修复可买预算最低0，不使用待卖/未结算资金。
- 模拟审计现在按原阶段remaining和冻结execution_config独立核对每笔数量/费用，不仅比较审计与财务内容；完整集合/前后序号保持检查。共享监测验证股票草案、激活及模拟归档，损坏显示BLOCKED。重哈希审计与财务同时改数量/费用仍拒绝；正向及迟到/零现金/失败回滚/重跑共14专项通过（100.89秒），hedge-stock-cash-audit-check.log。
- 6实际CLI通过，hedge-stock-late-cli-eighth-check.log及hedge-stock-late-cli-20261012-eighth/verification.json。合成旧工作区初始序号3、SPY100/IEF100、现金0；Jan16原收盘IEF200的迟到数据Jan20处理，Jan17 IEF400被排除。只新增一次模拟卖出37，序号4、SPY100/IEF63、应收7394.82、权益29994.82；没有实际账户写入。
- 股票相关回归首次因漏配LYRAX_TEST_ENGINE_EVIDENCE前置证据而1失败/26通过，日志保留；补指定既有8模板实际引擎证据后重跑进行中。发现代理long_put+显式篮子的stock控制额外加入代理股票，已修为保留原篮子；纯期权无篮子仍显式比较100股/包。首次独立预期与LEAN摘要分精度差0.0026，使用约定0.01容差；报告8项回归无跳过通过（141.32秒），proxy-basket-control-final-check.log，包含实际LEAN三组、日净值/费用/换手、自然末期、备份及UI。
- 补证据后的股票/门禁/监测/daily/完整备份98相关回归无跳过通过（245.97秒），hedge-stock-cash-audit-regression-final-check.log。其源码与上述8报告回归一致；6CLI源码早于代理比较修复，按其独立指纹保留，不冒充最终全量。
- SPY60/IEF50篮子与GLD两期2/3包独立验证1项通过（38.52秒），proxy-two-stock-control-check.log；公开CLI1项通过，proxy-basket-compare-cli-20261012/verification.json，源码27b0f164…与98/8回归一致。股票盈亏173.130400、期权增量45.00；报告comparison/report.md，全为合成账务验证。两只股票加单一期权标的不等于多个期权标的支持。
- 下一项验证迟到风险日历与原成交收盘一致（拒绝把该日实际晚1小时价格视为原时点可用）。股票关闭/单位行动/多期权标的/原生异常恢复及最终P5/O6/H5仍待，Goal active。

独立将Jan16快照日历收盘从原21:00改为22:00，复现旧风险未拒绝（1失败，18.78秒，hedge-replay-calendar-before-check.log）。现在估值与收益两份快照日历均须等于原冻结成交时点，HEDGE_REPLAY_CALENDAR_MISMATCH明确拒绝。最新f77969dac4…源码正常/迟到/零现金/风险归档29相关回归无跳过通过（123.57秒），hedge-replay-calendar-final-check.log；公开迟到6CLI通过，hedge-stock-late-cli-20261012-calendar-final/verification.json。98/8及代理CLI证据属于27b0f164旧源码，不冒充最新全量。

本批全部进程已结束，无待轮询任务。下一具体开发是原生股票反向CLOSE草案/组引用/显式激活：在原决定时冻结退出数量与计划收盘，依赖原股票OPEN成交/结算；退出激活用当时完整风险而非旧金融前缀。不得用普通月末权重修订伪造退出，不把CLOSE误算新候选交易。随后继续期权原生迟到时钟/异常恢复、多期权标的、单位行动/资格联动和P5/O6/H5最终验收。真实来源/券商/自然前向边界保留，Goal active。

### 进行中：原生股票反向退出

stock-draft新增显式exit对象（opening_plan_id、execution_session），在原OPEN尚为草案/原决定窗口内冻结反向数量，退出日须晚于OPEN假设结算日；复用原plans/组，不创建月度Signal。激活按CLOSE检查原OPEN依赖/结算、最新账户风险和费用/预留，用明确execution_basis_sequence记录激活前缀，原冻结snapshot不覆盖。模拟与refresh共享该前缀。草案独立重算官方执行日历/原候选及反向数量。

首轮独立全链路测试实际发现OPEN/CLOSE共用intent_id且revision=1触发原SQLite唯一约束（1失败，16.18秒，hedge-stock-close-check.log）。退出intent现在显式加入CLOSE及原opening_plan_id，保留OPEN身份；第二轮验证进行中，不能宣称退出已完成。验证包含提前/未结算拒绝、实际原生模拟往返、费用、重跑、恢复持仓及组完成。最新源码已变化，f77969/27b0f164证据保留为历史。

第二轮提前门禁实际返回UNRESOLVED_HEDGE_EXECUTION而测试写成HEDGE_STAGE_BLOCKED（1失败，17.26秒）；核对现有契约后更正预期，业务门禁未放宽。第三轮完整往返1项通过（40.63秒），实际SPY100→60→100、现金20000→19994.4、权益29994.4、金融序号2→4，两笔费用各2.8，重跑无重复。补充官方日历独立核对、原执行前缀及完整恢复、全组单次退出检查后64相关回归无跳过通过（192.37秒），hedge-stock-close-regression-second-check.log；首条回归命令误写不存在test_plan_lifecycle.py，仅收集错误，不是业务失败。

重复反向义务预检和重哈希归档独立2项通过（9.88秒），hedge-stock-close-invariants-second-check.log；首轮测试误期望内部DUPLICATE_HEDGE_CLOSE直接外抛，实际外层正确包装CORRUPT_HEDGE_GROUP，现同时核对外层及原cause。当前新增Feb3退出晚于原父Jan30窗口的完整恢复测试进行中；随后实际公开CLI验证。退出仍冻结原参考价，报价变化须明确重规划，不承诺已实现任意价格修订/单位行动或全部持续管理。Goal active。

Feb3退出跨过原父Jan30窗口并完整恢复的独立1项通过（58.64秒），hedge-stock-close-window-check.log。退出前按Jan31独立预期现金23997.2/持仓60建立新的对账基线，未计新入金/未改金融序号；原stage CLOSE可继续按明确期限处理，禁止新增过期OPEN。公开CLI脚本verify_hedge_stock_close.py正在新synthetic工作区复验整条链路；当前仅该CLI活跃，不编辑源码。

公开18条CLI全部通过，hedge-stock-close-cli-check.log及hedge-stock-close-cli-20261012/verification.json；包括显式v19-init、父冻结/OPEN和CLOSE草案/原生绑定、提前及未结算拒绝、各次风险归档、两个模拟批次和重复NO_ACTION。共享真实代码的demo账本金融序号4、SPY100、结算现金19994.4/权益29994.4；无实际用户账户写入。64回归/2拒绝/跨窗口1及CLI为相同源码（指纹以verification为准）。本批无活跃进程，下一项期权原生迟到风险/阶段时钟及中间异常恢复，随后股票价格/单位行动重规划、多个期权标的/资格联动及最终P5/O6/H5；v1.9未完成。

### 进行中：组内期权OPEN迟到时钟

execution_replay开始接已绑定/事先激活的option OPEN，需唯一原激活审计/原组压力及原有效收盘，非绑定或改激活条件拒绝。plan-simulate JSON可显式state_as_of原收盘，本次阶段风险沿用原状态/实际知识截止，接收晚到但交易所观察不得晚于原收盘；未提供原时钟的迟到组阶段拒绝。正在实际LEAN报告+原账户Put一次入账/迟到报价/重复任务/完整恢复的独立正向测试，尚未验证成功。最新源码已变化，股票64/18为67a08127…历史证据；不能宣称本轮期权已验。

首条组内期权迟到正向1项通过（59.64秒），hedge-option-late-stage-check.log：实际LEAN三组报告、Put成交在Nov1收盘、报价接收Nov4、SPY100不重复买入、金融序号2→3/权益99993、重跑及原阶段审计/完整恢复通过。现补原激活/月度/前缀绑定、缺原时钟/错误时钟拒绝和option-simulation审计失败注入回滚，期权/股票/阶段/激活/daily相关回归进行中，尚非最终期权交付。当前活跃命令hedge-option-late-regression-check.log；股票价格/单位行动修订、期权CLOSE迟到/中间异常、多期权标的/资格联动及P5/O6/H5仍待。

首轮相关回归5通过/1失败（84.19秒），实际定位新模拟器把“尚未激活”检查提前，遮蔽原组计划必须先提供阶段检查的门禁错误（OPTION_PLAN_NOT_READY而非HEDGE_STAGE_CHECK_REQUIRED）。现保持原门禁优先顺序，冻结时钟仅在有原激活时取值，财务行为未放宽。第二轮同集正在验证，hedge-option-late-regression-second-check.log；当前仅该命令活跃，不修改源码。

第二轮53通过/1失败（303.05秒），失败为/tmp满，激活备份复制时Errno28，不隐瞒为通过。已确认命令终止后仅删除本轮pytest-231/232/233生成临时目录，保留已验证原生A8源证据及全部日志；/tmp从2MB恢复3.2GB可用。第三轮显式basetemp置reports/v19-implementation/option-late-regression-tmp-20261012，正在同源码重验。

公开CLI第一轮测试准备对已经v5的账本再次套旧升级被拒；仅修改setup测试样本对v5跳过重复升级，不改变业务迁移门禁。第二轮风险/父/原生组通过，激活脚本漏显式--commit，被正确拒绝。补demo激活/模拟--commit后第三轮新工作区运行，bound-option-late-cli-third-check.log。当前两个活跃命令为第三轮回归及该CLI，不编辑源码；最新完整交付仍待。

第三轮公开11条CLI全部通过，bound-option-late-cli-20261012-third/verification.json；真实运行LEAN比较和原生OPEN原阶段压力、Nov1成交/Nov4接收/处理、缺状态时钟拒绝、模拟及缓存重复。Demo金融序号3、原SPY100未重复买、权益99993。已结束CLI；当前仅第三轮相关回归仍运行（大型原生证据/完整备份在NTFS复制较慢），源代码保持冻结。该证据为合成账户机械流程，不是实际期权历史/交易许可。

2026-10-11（Asia/Shanghai；v1.9核心工程进行中）。恢复先读本文件顶部、agents当前任务和对应主计划；旧交付记录按版本保留。

## 最新批次：冻结股票阶段的迟到处理与原子审计（2026-10-12）

risk.exposure新增明确execution_replay契约（当前仅已事先激活的独立stock用途）：绑定原plan_id、execution_at及processing_at，原风险状态和股票/期权/Greek观察时点不得晚于原成交时点，接收/资格知识截止可以到实际处理时点。普通风险仍禁止知识截止晚于风险时点；未激活/计划外请求拒绝。股票估值及Beta回看显式截至冻结交易日，未来交易日价格不进入风险，ledger_view原限制保留。当前不宣称期权native及所有旧月度绑定已支持这一重放入口。

阶段门禁区分冻结状态时点与处理时点，原组/本次资源/账本/依赖仍检查，不能借 later修订。simulate增加--state-as-of，只允许原计划成交收盘；超过一天的独立股票阶段若未显式冻结状态则拒绝用处理日风险。普通已完成计划仍可返回NO_ACTION，不要求重建新建议。事件保持原假设成交时间，并标注实际处理及late_processing。

hedge-stock-simulation审计在财务/计划同一SQLite事务内保存完整原阶段请求/结果和实际模拟事件/前后序号。独立核对原金融凭据、价格、原压力/数量和时间；缓存及备份检查。审计失败注入证明成交和READY/预留均回滚，重跑只一次。阶段OPEN/CLOSE动作明确保存，但股票关闭完整生产/持续管理仍未交付。

首两时点回归1通过/1失败（24.45秒）暴露旧Beta接口禁止迟到知识；通过独立execution_replay开关允许接收晚到数据，回看交易日仍限定min(风险/知识时点)，并保留普通接口拒绝。随后2通过（22.01秒）。独立future Greek例实际复现未来Greek能穿过“迟到知识”比较，1失败（11.83秒），hedge-late-greek-before.log；现同时约束Greek观察<=风险/知识时点，未放宽任何模型单位/接收门禁。

审计加入前114相关回归无跳过通过（186.80秒），hedge-stock-late-final-regression-check.log。加入原子审计后23核心回归（61.42秒），补动作/即时核对及失败回滚后23通过（67.80秒）；最终同源码114相关回归无跳过通过（195.41秒），hedge-stock-late-final-audit-regression-check.log。包含Beta/风险归档/阶段/原计划/daily/UI/完整备份；不是系统最终全量或实际浏览器验收。

实际迟到CLI脚本验证进行中。首轮假设旧工作区序号2而实际3（DEPOSIT+两笔BUY）被拒，第二轮误传DataCatalog构造参数，均修脚本，业务未放宽；日志保留。此前90/9CLI及自然比较等证据属于上一源码，不冒充本批指纹。当前无活跃源码编辑，等待CLI；下一具体动作是最终CLI/备份的迟到证据，再继续股票关闭/反向持续管理、候选/单位行动重规划、多期权主标的及提前指派/净交割native异常恢复、证券/行动/权限联动及P5/O6/H5统一最终验收。真实来源/券商/自然前向仍独立受阻，Goal active，v1.9未完成。

## 最新批次：独立股票对冲草案/显式激活（2026-10-12）

hedge-stock-draft复用plans表及原PlanService/账本状态，按冻结父股票数量生成purpose=hedge_stage、hedge_context独立契约，不创建虚构月度Signal或策略绑定。明确原价/配置/交易单位、父及资源CAS/有效窗口；新参考价格或账务变化要求明确重规划。未来交易日只取XNYS官方日历，不补行情；参考收盘与市场不符则拒绝。草案不预留或生成财务事实；可通过hedge-native-plans绑定原生执行组。

hedge-stock-activate预检/显式提交必须本次完整阶段请求、同账户/资源/时点、对账、成本一致及当前现金/股份/预计仓位/保护检查；尚未到账卖出款不得用于买入。只更新原预留、READY及任务审计，不发订单或写成交。独立重算原草案数量/价格/费用、激活原现金/股份预留及阶段压力；读取、精确重跑、备份验证恢复均检查。阶段端点目前不含固定逐笔股票费用，因此此入口明确拒绝fixed_fee非0，不默算为0。

基础refresh、模拟、执行复盘、四页计划展示和daily已区分月度信号与独立对冲用途；对冲不能调用月末权重修订或被daily当成基础策略意图。部分实际事实继续按同一账本处理，完成不依赖策略信号。原激活资格保留但不覆盖后续检查/异常。

先6草案回归通过（14.09秒）；激活测试几次失败是新fixture漏填对账身份/现金口径及误用Config代替备份配置路径，已修正fixture，业务未放宽。7含部分事实/完整备份恢复通过（23.82秒）；原89相关回归通过（135.35秒），属于零现金修复前源码。

首次实际CLI发现真实缺陷：零现金纯卖出被负购买预算阻断。已将预算下限设0，仍不计未结算卖出应收；零现金测试首次因新增取款后风险前缀仍2而按约定STALE拒绝，修正fixture冻结最新序号后1通过（10.90秒）。最终同源码90相关回归无跳过（145.31秒），hedge-stock-native-final-regression-check.log；9实际CLI通过，hedge-stock-draft-cli-20261012-verified/verification.json，指纹再次一致。未把此前failed/旧source当新验收。

原样例SPY卖40、两次20事实，各费1.4；最终SPY60、结算现金23997.2、权益29997.2，模拟新增入金/保费未混入。CLI样例明确单独demo风险上限0.80、IEF卖37，生成/绑定/激活新增财务事件0；没有改用户配置/真实账户。独立用途下一交易日模拟正向补充1项通过（15.17秒），hedge-stock-simulation-check.log；冻结卖40股@100，费用2.8，实际应收3997.2、持股60、权益29997.2，重跑不新增序号，未虚构信号。该测试未改业务源码，90项/9CLI仍同指纹。股票CLOSE/reverse产品持续管理、单位行动/候选变更重规划、迟到阶段风险/知识时点、完整证券/行动/权限资格、多期权主标的及提前指派native恢复仍待；之后P5/O6/H5统一清洁/全量/CLI/浏览器验收。v1.9未完成。

## 最新批次：自然到期同资本比较（2026-10-11）

monthly-compare/API/CLI扩展文件接受final_lifecycle=natural_expiry；策略、股票与现金控制组使用同数据/资本/费用/终止日。股票控制组持有至共同终止日，下一交易日统一清理终值是明确工程假设。实物交割现金独立分解，不计市场换手或价差，不重复扣保费/佣金，不算外部资金流。

首轮6通过/1失败（93.96秒）实际发现LEAN午夜生命周期状态与原收盘账本相差10；没有放宽容差或改变事件时间。自然路径日终净值明确截至下一本地午夜、包括同点生命周期，与LEAN每日OHLC标记一致；账本daily-equity.csv保存确切as_of。普通到期前退出仍按收盘。修复后7项报告回归通过（107.70秒），monthly-natural-compare-second-check.log；10条自然原生路径及其他执行路径合计13项回归通过（117.93秒），monthly-natural-compare-regression-check.log。均无跳过，非系统最终全量。

实际monthly-compare CLI通过，reports/v19-implementation/monthly-natural-compare-cli-20261011/verification.json，源码0273284d…再次匹配。报告comparison/report.md；保护Put样例净差额-1246、股票-2011.6、现金0，交割现金19000，策略比股票765.6；这是合成两周期账务核对，不是实际投资收益或自然前向观察。用户账户未写入。接下来实现独立股票对冲草案及其原有账户流程衔接；其他v1.9未完项保留。

## 最新批次：原生期权草案生成及审计独立重算（2026-10-11）

用户已恢复并授权继续，Goal当前active；此前usageLimited是历史记录，不是本轮停止条件。阶段审计现在独立重建原财务快照和全部压力端点，精确激活/退出/模拟重跑先验证原引用。实际复现“篡改费用并重算哈希”与“同时篡改根执行组和native数量并重算哈希”两项漏洞，均已修复；原候选总数量必须独立匹配父冻结候选。

新增hedge-native-plans：只读预检、显式提交、稳定幂等任务、父版本/资源CAS/窗口和资金事件门禁；期权草案复用原options.plans.draft，不另建资金/成交逻辑，生成OPEN/CLOSE依赖组。原生风险/费用/滑点和选约必须与父候选匹配，已使用计划不得借用。读取、重跑及完整备份核验生成记录与原组/原期权计划。股票目前引用已有native格式草案，尚未实现独立股票对冲草案生产器，不宣称完整阶段执行闭环。

审计加固阶段61相关回归（106.94秒）、2真实LEAN机械daily恢复（44.31秒）与4实际CLI通过，属于生成入口加入前源码。生成入口最终54相关回归无跳过（87.60秒），hedge-native-generation-second-final-check.log；7实际CLI通过，hedge-native-plans-cli-20261011-final/verification.json。正向期权原生格式测试含从零草案预检/提交、激活现金预留122、完整备份恢复及篡改后精确重跑拒绝；没有新增财务事件。所有样例明确synthetic，未写真实账户，不是实际期权来源/券商订单。

下一项正在实施自然到期monthly-compare同资本控制组，之后仍需独立股票原生计划、迟到处理阶段时点、候选/单位行动重规划、多主标的及提前指派恢复，最后统一P5/O6/H5验收。v1.9尚未完成。

## 当前批次：阶段门禁接原生激活/模拟及daily（2026-10-11）

stage_gate.require_for_plan已接option activate/OPEN模拟、退出预检冻结/CLOSE模拟和基础股票simulate；当前执行组内计划必须显式传本次hedge_stage_check请求，再按同账户/同操作时点/当前组重新计算，不接受旧CHECKED结果替代。未绑定native计划沿原路径；不能拿另一计划/开平仓阶段请求冒充。daily期权请求沿option_tasks传入同字段；股票新增hedge_stage_checks的plan_id→请求映射，CLI simulate增加--hedge-stage-check，daily增加--hedge-stage-checks，日常步骤输入哈希记录映射。

共享监测只允许成功的本阶段检查解除其父自身的HEDGE_FORWARD_INTENT_PENDING，其他父、在途、原组异常/账务事故仍阻断；基础覆盖复核沿用相同已计算阶段结果。daily的OPEN粗门禁移入原生原子操作内，避免自己的未完成父永久阻止本阶段执行；实际凭据导入/风险退出不冒充新开仓授权。退出预检锁顺序改为发布锁后SQLite。原有真实权限/前向资格限制仍保留，无券商订单。

原检查请求、源码指纹/知识截止/确切剩余数量随阶段结果进入激活/模拟及退出审计。完整备份核验阶段哈希、原组/阶段/计划、原风险归档及账本前缀剩余数量；旧无组审计保持兼容。新备份检查复现只读Ledger.__new__未初始化_savepoint_sequence的实际缺陷，已初始化计数器，未迁移只读数据库或放松验证。

首轮59相关回归无跳过通过（84.97秒），hedge-stage-gate-check.log。此前源码20项八类A8原生激活及真实LEAN机械daily中断/失败恢复回归通过（53.46秒），hedge-stage-gate-native-check.log；该20项在后续备份修改前，不能宣称最终同源码原生全量。绑定真实native格式月度protective_put父/组及当前压力的正向激活1项通过（12.03秒），阶段CHECKED、原计划预留122、财务序号仍2、精确重跑无新增；合成历史demo和已独立核验的LEAN机械证据，不是实际期权行情或真实订单。

加入完整备份后，首次测试失败为配置runtime相对工作目录不符（23.71秒），hedge-stage-gate-second-check.log；修正隔离runtime/account.sqlite与工作目录后复现上述计数器实际缺陷（24.44秒），hedge-stage-gate-third-check.log。修复后最终同源码60项无跳过通过（91.88秒），hedge-stage-gate-fourth-check.log，含原生格式正向激活、阶段门禁/未来报价、基础计划/daily/估值/监测及完整备份验证恢复。没有系统最终全量、当前新增入口最终CLI或实际浏览器验收。旧4CLI阶段证据属于此前源码，不冒充本批指纹验证。

已确认/tmp/lyrax-stage-gate-native-20261011无活跃Python/dotnet引用，仅删除该已终止自有目录；报告日志保留。现存/tmp/lyrax-incident-native-20261011包含有效八类机械引擎资格，后续原生测试可显式LYRAX_TEST_ENGINE_EVIDENCE引用其daily-option-base0/runtime/demo/options/engine-evidence/b0bbf34f5d703a2e99f760395d65601efcab556c00b141a1dfea654c3821c93f/verification.json，使用前重新核验。

**当前自动执行限制：** get_goal实际返回status=usageLimited（tokensUsed=906338，未指定token_budget），不是用户暂停、外部数据阻塞或整个Goal已完成。工具不能自行解除/恢复该状态；本批所有运行句柄已确认终止。恢复执行前先读本节，不重复已验证且无变化步骤。

下一具体动作：阶段审计在精确重跑前也验证原引用；增强阶段压力归档的独立重算/篡改检查，补最终源码原生及CLI证据。随后原生阶段计划生成、迟到处理的风险状态/知识时点、单位行动/候选变更重规划、全可达交割分支、提前指派/净交割异常native恢复、多期权主标的/自然路径同资本报告及P5/O6/H5最终清洁安装/全量/CLI/实际浏览器/备份。真实来源/券商权限/自然前向独立条件不以合成替代，v1.9 coding仍未完成。

## 当前批次：执行阶段部分成交端点压力检查（2026-10-11）

stage_stress/stage_assessment及hedge-stage-check已实现只读当前组阶段检查。必须引用当前组记录哈希、资源CAS、同账户/时点/当前账本前缀的完整风险归档；原前缀哈希独立重验，归档后预留变化要求重新冻结风险。未完成成交/结算依赖、原组异常或人工在途拒绝；新增OPEN须在原未关闭父窗口。报价须有独立来源评估、确切条款、事前可用时间、新鲜度/价差/标的价时一致性及逐腿报价数量。合成来源只用于demo研究，不授予真实来源/权限。

对最多8腿的所有0/剩余数量端点（最多256）计算现金、短Put担保、备兑股份、费用和情景损失；总合约情景最多1500，不抽样省略中间分支。仅复用本阶段原native现金/股份预留，不释放或重复登记；其他计划股份不可重复备兑。未结算卖出应收不能用于买入。有限情景复用QuantLib/既有stress.evaluate，显式IV/利率/股息率、相关性敏感度/期限/损失阈值；不推断保证最大损失，也不模拟提前指派/交割。

初步11项通过（23.22秒）；扩大56项通过（73.18秒），hedge-stage-final-check.log。首次实际CLI暴露口径缺陷：零现金卖出筹资仍被要求预付卖出费用，和统一账本从应收净额扣费不同，脚本CHECKED断言失败，hedge-stage-cli-check.log。已修复：费用从卖出应收扣除，超过卖出额部分才占用当前现金；净应收仍不提供购买力。随后56项通过（71.27秒）；补逐腿报价数量/原价时点及预留检查后最终同源码57项无跳过通过（75.40秒），hedge-stage-third-final-check.log。补充期权服务/未来报价门禁6项通过（18.08秒），hedge-stage-option-service-check.log；和57项有5项重叠，不相加宣称63独立测试。

verify_hedge_stage_check.py实际4CLI通过（组绑定、检查、精确重复、旧资源拒绝）；最终证据reports/v19-implementation/hedge-stage-cli-20261011-verified/verification.json，源码再次匹配。明确合成样例IEF卖37股@200，费用7.4，仅是应收净额7392.6的压力分支；没有实际成交，新增财务事件0、检查不新增诊断任务/预留。CHECKED/execution_qualification=NOT_GRANTED，不等同阶段可执行。旧最终9CLI组修订证据保留为此前批次，不冒充本次源码验证。

下一具体动作：把阶段结果接入原生阶段计划生成/激活及daily、证券/行动/Greek/账户权限联动；检查多阶段可达交割分支，补提前指派/净交割异常官方native恢复、多期权主标的和自然路径同资本报告。候选变更/单位行动后的重规划、P5/O6/H5最终清洁安装/全量/CLI/实际浏览器/备份验收仍待。外部真实期权来源、券商权限与自然前向条件独立受阻；Goal active，v1.9 coding未完成。

## 当前批次：执行组未成交部分修订（2026-10-11）

hedge-group-revise已实现原父窗口内的不可变线性修订：原计划必须显式结束、无人工在途且释放原预留；新计划只接受相同方向/合约/单位的确切未成交数量。保留原成交切片，即使原成交为0也保留旧计划引用，以捕捉晚到旧成交；期权OPEN部分成交后，原持仓退出与新剩余计划退出分别保存依赖。修订不新增财务事件、预留或券商订单，不授予逐阶段执行资格。修订后的迟到事实若生效时点早于修订而在修订后才记账，明确阻断，不倒用新规则。

读取/重跑/完整备份校验原父与原计划、线性版本、阶段依赖、原候选OPEN总数量和内容哈希；监测/父关闭只采用当前有效头版本，所有旧版本在group_archive/计划页保留。历史时点及账本前缀读取不会提前使用后来修订。原组已有异常/在途不能通过修订掩盖，费用与实际持仓仍由原账本更新。

首轮失败为新测试误要求逻辑修订后资源CAS不变；CAS包含对冲任务审计，应改变，而现金/持仓/预留/财务序号不变。修正独立预期后41项通过（57.43秒）；增加期权切片、晚到事实和读取完整性后最终同源码95项无跳过通过（116.86秒），hedge-group-revision-final-source-check.log，含原计划/daily/监测/备份及异常核实回归。不是系统最终全量。

verify_hedge_group_revision.py实际9CLI通过：未结束拒绝、预检、旧版本拒绝、提交/精确重跑、历史/当前版本和剩余成交完成。最终证据reports/v19-implementation/hedge-group-revision-cli-20261011-final/verification.json，源码再次匹配。明确合成样例原SELL37，已成交18+新计划19，最终现金7400、IEF63；修订新增财务事件0。另一期权独立样例原2张，已开1张及新剩余1张分别退出，最终现金10200、SPY200、期权0，无重复保费/乘数。没有真实账户写入；新计划引用采用native格式DRAFT样例，本批不宣称原生引擎实际下单或完整阶段激活。

连续两次期权剩余修订补充验证2项无跳过通过（11.29秒），hedge-group-repeat-revision-check.log；第二次零成交替换仍保留原1张退出和空历史切片，新1张完成后现金10200/期权0，不重复记账。该测试未修改业务源码，95项/9CLI指纹仍对应当前源码。

下一具体动作：完成逐阶段来源/当前报价/覆盖/各可达中间压力资格、父候选变更/单位行动后的明确重规划及原生阶段计划生成。提前指派/多腿净交割异常恢复、多期权主标的/自然路径同资本报告与P5/O6/H5最终清洁安装/全量/CLI/实际浏览器/备份验收仍待；真实期权来源、券商权限及自然前向周期独立受阻。Goal active，v1.9未完成。

## 当前批次：异常前缀的明确核实/恢复（2026-10-11）

options.incidents从标准批次/解决的冻结前缀派生稳定异常身份，实际现金/支付担保不足、负股票交割及真实备兑股份不足保持OPEN；预留/待核实上下文不伪装成永久真实财务事故，但当前未解决状态仍阻断。option-incident-review预检/显式提交需原异常哈希、当前账户序号、异常后的全部明确恢复事实、同账户/序号/时点PASSED对账、核实人/理由及凭据文件SHA256。引用恢复前缀和当前状态须均已恢复，不能仅凭后续余额或理由覆盖旧问题。真实/paper只接受actual声明及实际恢复事件；这不是自动验证券商真实性或授予账户权限。

原异常快照/原事实永久保留；核实只增加任务审计及不可变options/incident-evidence凭据，不改财务事件、释放预留、恢复原计划为READY或发单。一次异常仅一份核实，同请求精确重跑返回原证据，冲突拒绝；新的财务变化不覆盖旧核实。读取/备份核对核实哈希、原异常/原账本前缀、恢复事件及对账，并重算核心财务字段；即使篡改后重新计算自哈希也拒绝假余额。证据篡改或缺引用时共享监测BLOCKED。监测如今检查所有账户的当前事实异常/到期未解决持仓及OPEN核实事件，无对冲父/组也不能绕过；daily/计划/模拟/激活和四页/今日待办沿用同服务。没有将NO_ACCOUNT_ANOMALY当作估值/压力或完整执行资格。

首轮42相关测试无跳过通过（40.52秒），option-incident-check.log；加固真实财务与上下文分类、独立重算/历史核实保持后85通过（69.32秒），option-incident-final-check.log。冲销恢复独立回归随后复现实际缺陷：只看active_events无法引用被冲销原事件/冲销记录，1失败（12.87秒），option-incident-correction-before.log；修正凭据读取为原始账本序号，余额仍按active_events重建。首次扩大回归1通过/1失败为新测试试图在同环境创建第二账户，SINGLE_ACCOUNT按约定拒绝；改用独立单账户fixture，不放宽业务约束。最终同源码87项无跳过通过（69.49秒），option-incident-correction-second-final-check.log，含更正链、纯待核实上下文、原价/估值/计划/模拟/日常/UI、完整备份恢复及篡改门禁；非系统最终全量。

verify_option_incident.py已实跑10CLI，首轮及冲销修复后的最终源码均通过。最终证据reports/v19-implementation/option-incident-cli-20261011-final/incident-verification.json。前3条沿用明确合成receipt样例，之后核对未核实阻断/预检/旧序号拒绝/提交/重跑/核实后状态/原凭据故意破坏再次阻断；财务序号始终5、现金19600，原SPY -100中间前缀不删除。最后工作区故意损坏用于门禁测试，不能作为实际运行配置。无用户账户或真实券商凭据写入；核实动作新增财务事件0，未取得真实期权数据。

2项真实LEAN机械daily恢复回归无跳过通过（112.57秒），option-incident-native-check.log，固定/tmp/lyrax-incident-native-20261011。覆盖原生OPEN财务提交中断后恢复及临时CLOSE失败只在真实native执行后清除；非真实期权行情/券商凭据。已核对旧/tmp/lyrax-stock-option-native-20261011无活跃Python/dotnet引用并仅删除该已结束测试临时文件，旧reports保留。当前批次无实际浏览器最终验收。

下一具体动作：执行组修订/滚动与每阶段来源/报价/覆盖/压力资格，提前指派/多腿净交割异常的官方native恢复样例；多期权主标的及自然路径同资本报告、来源/证券/行动资格联动和原P5/O6/H5最终同源码清洁安装/全量/CLI/实际浏览器/迁移备份仍待。真实期权来源/券商权限/自然前向独立条件未用合成替代；Goal active，v1.9 coding未完成。

## 当前批次：期权估值贯通股票计划/修订/模拟（2026-10-11）

planning_marks复用既有quote_set/quality/assess_source，显式请求snapshot_id/limits；无请求不继承旧报价。有期权时全部报价来源/单位/可用时间/价差合格才发布完整估值，并校验期权标的报价与股票收盘参考时点的偏差。股票份额仍用股票原价，只将期权中价合约市值纳入统一账户权益；不是期权可成交价或券商授权。create/revise/simulate、BindingService/daily、三个CLI及计划页JSON上传均已接。原修订幂等键增加期权请求及检查时点，缺新报价不能误返回旧READY。保存完整估值/请求，备份正确区分股票与期权快照并包含计划中的期权引用。

迟到模拟复用quality原有knowledge_cutoff：估值所属/成交状态时点仍冻结，报价exchange_timestamp不得晚于该时点；available_at/received_at可以在处理截止前迟到。不假装报价事前已知，期权报价/持仓状态不偷偷移动到处理日。独立测试未来交易所价格不能进入冻结收盘估值，合成报价不能授予paper来源资格。手算例入金1000−已付保费200+期权估值205=权益1005，50%目标/股票100生成5股；股票模拟后现金300、股票500、期权205=1005，保费/乘数未重扣。

首轮失败为测试强制数量字符串'5'而实现Decimal合法表示'5.0'；改按Decimal核对独立预期5，不改业务。60项相关回归通过（56.57秒），stock-option-valuation-second-check.log。31项绑定/UI/保护/凭据回归也通过（51.33秒），stock-option-valuation-ui-binding-check.log。新增迟到/未来价/来源门禁及备份修复后的最终同源码78项无跳过通过（77.35秒），stock-option-valuation-final-check.log；非系统最终全量。

verify_stock_option_valuation.py 实跑5CLI：无估值计划BLOCKED/退出3，明确报价修订READY/退出0，无成交日估值模拟拒绝/退出2，新成交日报价成功/退出0，完成重跑NO_ACTION。READY完整备份验证/恢复保持原期权估值和账户序号2，最终原账户序号3、现金300、SPY5、Put1、权益1005；源码再次匹配。证据 reports/v19-implementation/stock-option-valuation-cli-20261011-verified/verification.json，全部明确合成工作区，无用户真实账户写入。

CLI首轮验证脚本未切工作目录导致备份路径约定不符；切入隔离root后发现真实业务缺陷：option_valuation_request被当股票snapshot引用，现已修复分类及计划期权引用收集。第三轮脚本误从stdout读取预期失败（CLI错误JSON按约定在stderr）；修正脚本不改CLI退出/阻断语义，最终上述5条通过。失败日志保留。

2项真实LEAN机械daily任务恢复回归无跳过通过（110.23秒）：stock-option-valuation-native-check.log，固定临时目录/tmp/lyrax-stock-option-native-20261011。覆盖原生OPEN财务提交后中断恢复、临时退出失败后真实native执行才清除故障，合成机械行情非实际期权数据。开始前确认旧/tmp/lyrax-monitor-final-20261011无存活Python/dotnet引用并删除该已终止测试临时目录1.4GB；旧reports证据保留，不清理未知用户文件。新流程实际浏览器及最终全量仍待。

下一具体动作：中间异常的核实/恢复凭据工作流，执行组修订/滚动与逐阶段来源/报价/覆盖/压力资格；提前指派/净交割异常、多期权主标的/自然路径同资本报告及原P5/O6/H5最终验收仍待。真实期权/券商权限/自然前向条件独立受阻；当前Goal active，v1.9 coding未完成。

## 当前批次：预测保护覆盖与标准凭据逐笔审计（2026-10-11）

require_projected_coverage 已接基础计划数量计算后及模拟批次写账前。预测股数必须显式包含所有现持股、不能负数，至少保留每个活跃实际/在途保护切片的 share_end；缺字段不按0猜测。旧分配归档与财务预留不变，未建立第二份资源。显式结束引用允许后续股份调整，但实际期权仍是未分配风险，不被删除。首轮48相关回归无跳过通过（48.40秒），hedge-projection-check.log。

receipt_risk 捕捉每个新入账事实的序号、生效时点、原事实/完整账本前缀哈希和财务快照，以及处理时点最终快照。批次及显式解决均在发布锁/SQLite事务内保存；相同生效时点不同序号分别保留。独立例子Put行权先形成SPY -100，Call行权恢复0，最终现金19600，中间REVIEW_REQUIRED仍永久存在；不把后续平衡等同于原异常已核实。无行情报价，valuation_status=NOT_EVALUATED，不判断估值/压力/执行资格。预留与待核实取审计时上下文，标注restated，不伪造当时PIT。运行状态只读展示原审计；旧批次不补造证明，标记LEGACY_UNVERIFIED。重跑/备份校验原账本前缀并重算现金/应收应付/股票期权数量，篡改余额后即使重算审计自哈希仍拒绝。

首轮测试1失败：新测试错误重复调用一次性数据库迁移fixture，改用已迁移库的register_contract登记第二腿后27项通过（45.39秒），receipt-prefix-second-check.log。补齐显式解决、财务重算及扩大全部受影响旧路径后，最终同源码78项无跳过通过（73.22秒），receipt-prefix-final-check.log；补充2项解决审计精确重跑/篡改/完整备份恢复通过（6.84秒），receipt-resolution-check.log。非最终系统全量或实际浏览器验收。

verify_receipt_prefix.py 实跑3条daily CLI并核对源码不变，证据 reports/v19-implementation/receipt-prefix-cli-20261011-final/verification.json。首次脚本失败是错把未绑定行情的daily BLOCKED退出3当作0；未改业务放行，修正脚本明确预期UNASSIGNED_DATA_ROLE/退出3，凭据SUCCESS、重复不新增财务事件、不同文件不重记事实均通过。样例合成独立空账户筹资/两腿开仓和用户提供生命周期事实；不是原生引擎此次验证、真实凭据或完整真实行情日常流程。原用户账户未写入。

下一具体动作：把显式合格期权估值贯通基础计划/修订与月度绑定，不能仍只传股票原价或偷偷默认中价；再完成中间异常的核实/恢复凭据工作流、执行组修订/滚动及逐阶段来源/报价/覆盖/压力资格。提前指派/净交割异常、多期权主标的与自然路径同资本报告，以及原P5/O6/H5同最终源码清洁安装/全量/CLI/实际浏览器/备份最终验收仍待。真实期权/券商权限/自然前向独立条件未以合成替代；Goal active，v1.9未完成。

## 当前批次：统一daily/计划门禁与四页对冲监测（2026-10-11）

hedging.monitor/hedge-status 已实现，发布锁与同一SQLite读取事务内核对原父/组/严格引用及风险/证券/链归档，重算指定时点当前覆盖；原决定/原allocation_archive与current_coverage分开。原引用坏、组异常/人工在途、有效前向父未完成、无法核对覆盖及到期未处理头寸均BLOCKED；不按零价值清除资产。daily保存凭据后/全部事实后两份监测，阻断新增基础计划及期权OPEN，实际凭据/对账/报告与风险CLOSE仍可处理。原计划新建/修订、基础模拟、期权激活/模拟共享门禁；月度绑定与日常事务统一先发布锁后SQLite。四页只读对冲视图及今日待办接相同服务，刷新不写财务/计划/诊断任务；新视图时间转上海。

首轮1通过/1失败：测试误要求两次当前监测ID相同，demo重述知识截止随实际检查变化；修正为核对原记录/财务不变并明确口径，后35项无跳过通过（57.08秒），hedge-monitor-second-check.log，含新监测、daily/直接新计划阻断及四页AppTest、旧daily/计划/UI。扩大原生引擎回归9通过/1失败（197.34秒）：/tmp空间耗尽，未发生资金断言失败。清理已终止的自有旧测试目录、迁到项目盘后2通过/1失败（484.84秒）：目录原子rename PermissionError，具体占用未证明，并发诊断目录遍历可能干扰；未把这次当NTFS成功。

补publish_directory有限5次PermissionError重试及清晰错误；始终同目录原子rename，禁止覆盖已有归档，永久拒绝不发布/不激活，不转非原子复制。独立临时拒绝/永久拒绝/原归档保留3项门禁验证。释放已终止旧自有测试缓存后，最终在Linux /tmp重跑19项无跳过通过（422.00秒），hedge-monitor-publication-final-check.log：原失败激活、八类A8账户模拟、原子/重复成交与结算恢复、新监测/daily/直接入口与四页AppTest。最终月度绑定锁顺序7项另通过（15.98秒），hedge-monitor-binding-lock-check.log。本批非系统最终全量，NTFS实际发布兼容仍需最终复核；未无限重试权限错误。

verify_hedge_monitor.py 四条实际CLI在最终源码全部通过，源码再次匹配。最终证据 reports/v19-implementation/hedge-monitor-cli-20261011-publication-final/verification.json，核对历史/重复、到期风险与损坏引用，财务序号/资源/诊断任务不变。先前两轮4CLI也通过，最终以publication-final为准。全部复制明确合成账户，无用户账户写入；真实期权/券商/自然前向未替代。操作/复现/有限发布重试与H4状态已记录V19-USAGE/H计划。新功能仅AppTest，尚非最终实际浏览器验收。

下一具体动作：逐生命周期凭据的账本前缀风险审计接daily（当前只监测批次前后，不能据此证明所有中间状态安全）；新计划/模拟成交前验证预测保护覆盖，执行组修订/滚动与逐阶段当前报价/覆盖/压力资格。H3多期权主标的/自然路径同资本报告、提前指派/净交割异常恢复、来源/行动资格、原P5/O6/H5同源码清洁安装/全量/CLI/实际浏览器/备份验收仍待。外部条件单列，Goal active，v1.9 coding未完成。

## 当前批次：严格保护分配父版本（2026-10-11）

parent_bindings.py 与原 hedge-allocation 的 schema2 已实现：完整保留集合逐allocation_id指定parent_versions，绑定同账户确切父record_hash/候选hash、稳定证券范围、原选定合约/角色/方向；已成交及在途数量合计不超过该父冻结目标。新增/修改仅用未关闭最新父修订，同ID不能静默换父版本；关闭后保留历史和实际风险，仍允许显式退出引用，不增加事件或释放原计划预留。schema1兼容旧研究引用，明确LEGACY_UNBOUND；显式升级验证全集合，升级后禁止降级。BOUND与执行资格分开，仍executable=false。

读取/精确重跑及完整备份也校验原父引用，不能用请求缓存绕过损坏；发现这一必要边界后追加回归并补入history。初批真实构造合成父/条款/成交的6项通过（18.22秒），扩展未选合约/目标张数/旧引用迁移后相关54项通过（57.83秒）。最终55项无跳过通过（62.95秒），hedge-parent-bindings-final-check.log，包含执行组/父关闭/旧分配兼容和备份恢复。无运行失败；本批不是系统最终全量。

verify_hedge_parent_binding.py 已实跑9条CLI，首轮与补齐重跑门禁后的最新源码均通过。最终证据 reports/v19-implementation/hedge-parent-bindings-cli-20261011-final/verification.json，源码再次匹配。复制明确合成期权研究工作区，父冻结、预检、错误父拒绝、提交/重复、禁止降级、关闭后编辑拒绝、引用退出全部核对；两笔标准合成筹资/期权成交程序化导入，重复新增0，退出后实际Put仍是未分配风险。没有用户账户写入。请求/stdout/stderr保留，操作契约和复现命令已记V19-USAGE/H计划。

下一具体动作将父/执行组/严格分配状态与生命周期逐凭据风险接统一daily及四页；执行组修订/滚动、逐阶段当前报价/覆盖/压力资格仍须补齐。提前指派/净交割异常恢复、多期权主标的、自然路径同资本报告、来源/行动资格及原P5/O6/H5最终同源码验收仍待。实际期权/券商/自然前向条件独立待补；Goal active，v1.9 coding未完成。

## 当前批次：原计划执行组绑定与事实时序（2026-10-11）

groups.py 与 hedge-group/hedge-groups CLI 已实现。执行组不可变绑定最新父版本和原 stock/option 计划；全部 OPEN/筹资数量、方向及合约版本与冻结候选完全一致。阶段依赖仅引用前序ID，CLOSE绑定原OPEN；父版本仅一组、原计划不跨父重复使用。候选需筹资时必须显式等待筹资阶段。组不创建/激活订单，不增加第二份预留。绑定组后禁止直接覆盖父执行依据；父关闭复核 registry，无未完组才可关闭研究意图。备份校验组哈希、父记录及原计划所有权引用。

progress 按明确关联 event_id、账户前缀及结算证据重建 OPEN/CLOSE/自然事实进度；未关联事实不冒充完成，缺结算或人工在途不算结束。每次实际成交时点重新检查依赖，后来的结算不能抹掉旧违规。行数量/方向/条款修改或拆股改变单位则阻断；没有自动将旧数量套新单位。整次在发布锁/SQLite事务一致读取，前缀缓存避免多阶段重复递归爆炸；结果明确 restated，executable=false，不冒充当时实时知识或交易资格。

首轮7通过/1失败：原生格式测试股票计划漏as_of，正常成交导入的原计划刷新要求该字段；补齐as_of/price后11通过（18.06秒）。扩大期权测试首轮11通过/1失败：测试helper固定quantity/时间又重复传参；修正构造后36项无跳过通过（39.10秒）。最终缓存/一致读取源码与保护/在途兼容相关57项无跳过通过（69.07秒），hedge-group-final-integration-check.log。包含股票部分/结算、依赖历史违规、期权开/部分平/结算、旧前缀、拆股阻断、父关闭、完整备份恢复及篡改门禁；非系统最终全量。

scripts/verify_hedge_group.py 实跑11CLI，两笔标准合成成交程序化导入，全部预期退出码通过；最新源码再次匹配。证据 reports/v19-implementation/hedge-group-cli-20261011-final/verification.json。隔离复制的合成父研究账户，原生格式DRAFT股票计划未激活，IEF37股卖出后持仓63/现金7400，重复导入新增0，原父记录不变，没有额外财务事件或预留。最初11CLI也通过，最终证据以上述final路径为准。V19-USAGE及H计划表已更新。

下一具体动作严格保护分配父版本绑定、执行组修订/滚动与逐阶段当前资源/报价/覆盖/压力资格，再接统一daily。当前组 COMPLETE 仅定义内实际成交/结算完成，不代表整个账户风险通过；组不生成新的阶段计划，不能从DRAFT下单。尚未完成全部可达中间状态压力/提前指派及净交割异常恢复、多期权主标的、自然路径同资本报告、来源/行动资格、H4四页及原P5/O6/H5最终同源码验收。真实期权/券商/自然前向条件独立待补，Goal active，v1.9 coding未完成。

## 当前批次：父研究意图关闭与不可变凭据（2026-10-11）

追加 intent_actions 与 hedge-intent-close CLI。关闭请求明确最新父版本、资源指纹、动作/原因；默认只预检，提交在 publication_lock/SQLite 事务内复核并保存独立不可变凭据。EXPIRED 核对实际处理时点已达有效期；未核实执行组阻断。保留原父记录、保护引用、实际持仓与预留，不新增财务事件，不宣称券商订单取消。关闭后禁止同父修订/重开，新明确决定仍受策略版本及保护重复检查；精确旧创建重跑只返回原凭据。hedge-intents 将原修订与 closures 分别展示。备份验证关闭哈希、父引用与关闭后无修订。

首轮新测试因漏导入 risk_market fixture 产生11个设置错误，原父11项通过；修正后新旧22项无跳过通过（27.54秒）。追加并发两连接同请求和保护/在途资源兼容检查，最新44项无跳过通过（54.57秒），hedge-intent-close-integration-check.log；补充关闭后精确原创建重跑1项通过（9.22秒），hedge-intent-closed-retry-check.log。相关回归包含完整备份恢复、篡改拒绝、前缀/资源和到期边界，非系统最终全量。

scripts/verify_hedge_intent_close.py 实跑7条CLI全部满足预期退出码，源码核对一致；预检及拒绝无任务/财务副作用，提交一次、精确重复返回原凭据，原父记录与账本序号不变。证据 reports/v19-implementation/hedge-intent-close-cli-20261011/verification.json。输入是隔离合成历史父研究工作区，未写入用户账户。操作契约及实跑命令已记 V19-USAGE。

下一具体动作 ExecutionGroup 的不可变父版本/计划绑定与阶段复核、保护分配严格父版本，再接生命周期逐凭据状态至统一 daily。当前关闭是研究父意图关闭，不是完整执行组/券商订单关闭；这些仍未交付。提前指派/异常交割恢复、多期权主标的、自然路径同资本报告、来源/行动资格、H4四页及原P5/O6/H5最终同源码验收仍待。实际期权/券商/自然前向独立待条件，Goal active，v1.9 coding未完成。

## 当前批次：多腿自然生命周期与逐凭据风险快照（2026-10-11）

自然末期实际引擎样例扩展至十条，覆盖全部八类A8的指定到期路径：原四条、Collar上下两条、Bull Call/Bear Put价差、Long Call行权、Long Put失效。monthly_natural追加官方行权/指派标志与多空方向一致性门禁；monthly_replay在每条生命周期事实的精确账本前缀保存receipt_view和lifecycle-receipts.json，不仅保存同一时点全批次终态。临时股票空头、账务异常或缺权益标BLOCKED；后续相抵不覆盖原快照，不产生额外财务事件/预留。

扩展后10条自然实际引擎回归通过（103.98秒）；首次加入逐条快照的10项再通过（104.10秒）。提取共享receipt_view并追加独立-200股→0股及缺权益分支，最新同源码11项无跳过通过（111.69秒），monthly-multileg-receipts-final-check.log。本批无失败。实际官方十路径的中间状态全部CHECKED，不能声称这些原生样例观测到临时股票空头；该阻断用独立明确样例验证，原状态保留、后续状态恢复分别核对。非系统最终全量。

固定monthly-natural-fixtures.json扩展十条（约150KB明确合成样例），verify_monthly_natural.py按实际腿数/逐凭据数量核验；实际10CLI全部返回0，覆盖14个官方原生到期/行权/指派凭据，数量每腿2张，最终账本/引擎一致、重复新增0。源码再次匹配，证据reports/v19-implementation/monthly-multileg-cli-20261011/verification.json。后六条独立终值98944/100944/100944/100944/101762/99762；无用户账户财务写入。操作/模型限制已更新V19-USAGE。全部合成机械/到期日模型，不是实际期权历史、自然前向或提前指派验证。

下一具体动作父意图关闭/ExecutionGroup与严格保护父版本、将生命周期逐凭据风险状态接统一daily/用户账户任务；提前指派/净交割空头应急恢复、多期权主标的、自然路径同资本报告、来源/行动资格、H4四页及原P5/O6/H5最终同源码验收仍待。十条指定路径不等于A8所有生命周期场景完成。外部真实期权/券商/自然前向独立待补；Goal“完成v1.9的coding工作”仍active，coding未完成。

## 当前批次：月度末期官方自然生命周期桥接（2026-10-11）

用户重新设置Goal为“完成v1.9的coding工作”，继续原P/O/H工程范围，不以外部数据缺失停止可独立实现的代码。monthly_replay/现有CLI扩展final_lifecycle=natural_expiry，早期周期按原规则关闭，末期持有至到期，下一交易日清理交割后股票。LyraXMonthly复用官方自然OptionExercise事件，保存原order_symbol/assignment/in_the_money；短腿使用明确priorExpiration=0到期日模型，不声称提前指派已验证。monthly_natural.py独立按到期内在价值、真实单位、有符号份数、交割后价格变化及费用核对；交割股票原生子事件不重复导入，由期权规范化事实更新一次。周末确认保留原时点，下一交易日结算。隔离账本重复导入不增加事件。

首轮1失败（12.57秒）：新C#未导入Option命名空间导致构建失败，已修正。第二轮1失败（16.98秒）：官方到期于周六凌晨确认，旧calendar.next要求事件日为交易日；已改为按实际事件日寻找后续交易日，不假造时间。随后4条自然路径通过（48.21秒）。追加独立固定终值后，最新14项无跳过通过（135.64秒），monthly-natural-final-check.log，覆盖Put失效/行权、备兑Call及现金担保Put指派，全部旧A8实际月度及变化路径回归。不是系统最终全量。

固定examples/options/monthly-natural-fixtures.json及scripts/verify_monthly_natural.py已交付并实跑4条CLI，均返回0；原生生命周期数量2张、完整结算后头寸/应收应付0、重复新增0、无用户账户财务写入。最新源码再次匹配，证据reports/v19-implementation/monthly-natural-cli-20261011/verification.json。初始资金各100000、前/后周期1/2包、单张交易费2，独立账本/引擎终值99762/98762/101182/99182；这些是明确合成路径核对值，不是实际历史或自然前向收益。操作/到期费用0假设/模型边界已记V19-USAGE。

当前完成末期四条自然模型路径的月度账务桥接；完整A8多腿/提前指派/净交割股票空头应急路径、多期权主标的、自然路径同资本报告和daily/父执行还未贯通。下一具体动作补多腿自然结果与异常分支、接统一账户任务；父关闭/ExecutionGroup/严格分配父版本、来源/行动资格、H4四页及原P5/O6/H5同源码最终验收继续。真实期权来源/券商/自然前向仍单独缺条件，不当作工程完成证据；Goal active，v1.9 coding尚未完成。

## 当前批次：H3同资本变化路径比较报告（2026-10-11）

monthly_compare/现有monthly-compare CLI接入signals/packages/stock_basket/execution_path，与回放输入一致。期权策略、相同股份/篮子股票控制组、现金控制组共享资金/费用/执行窗口/完整数据文件/引擎源码；全部逐日净值对账。metrics按实际成交日bid/ask算解释性价差，不沿用月末参考价；新增股票/期权交易盈亏与净交易盈亏分解，核对终值差，价差不重复扣除。report保存源码/路径hash、包数/篮子与同资本终值差，输出曲线/回撤/交易/指标及原可验证归档；指标仍复用ffn。

最新5项报告相关回归无跳过通过（84.50秒），monthly-variable-compare-check.log：新变化路径三组实际LEAN/47日核对、独立成交日价差110/手续费8/净盈亏52样例，以及旧报告/同资本控制组/完整备份恢复、篡改拒绝和Streamlit AppTest。旧schema2继续读取；本批无失败，不是系统最终全量或四页实际浏览器验收。

新scripts/verify_monthly_compare_path.py使用固定离线样例准备新工作区，实际调用CLI并核验三个成员报告及全部引擎/独立账本曲线。实际CLI返回0，source再次匹配；证据reports/v19-implementation/monthly-variable-compare-cli-20261011/verification.json和comparison/report.md。47观察日，策略净盈亏642.7416、股票597.7416、现金0，差额45，期权价差解释50/期权佣金20。重复桥接新增0、无用户账户财务写入。全部synthetic_variable_path，仅工程路径账务/报告验收，不是真实期权历史、自然前向或策略效果结论。操作/命令已记V19-USAGE。

下一具体动作官方LEAN自然到期/行权/指派与月度/daily账户任务桥接，复用既有生命周期账本，不拼接不同成交假设的旧诊断。单一期权主标的限制、父关闭/ExecutionGroup/严格分配父版本、来源/行动资格、H4完整四页/任务及原P5/O6/H5最终同源码验收仍保留。实际期权来源/券商/自然前向独立缺外部条件；Goal active，v1.9尚未完成。

## 当前批次：H3变化原价/多股票/多张数月度机械回放（2026-10-11）

扩展LyraXMonthly.cs和monthly_replay.py，新增monthly_path.py。原冻结信号数组入口保留；扩展JSON明确signals/packages/stock_basket/execution_path，经现有options monthly-replay CLI调用。每周期1–100包、单一期权主标的/多股票篮子、完整逐日股票原价与合约bid/ask；缺失/额外会话、交叉报价、精度或未知单位拒绝，不能沿用固定100。官方LEAN负责全部成交/资金，Python只校验独立端点现金公式和统一账本/结算；原八类A8保留。不改第三方核心源码。

首轮2通过/1失败（36.38秒）：变化价/多股票/多张数已通过，旧Collar账本路径发现同一UTC瞬间的不同字符串格式被误分组，多出入金中间点。已按pd.Timestamp实际时点分组，不改事实或资金；最新10项无跳过通过（97.24秒），monthly-path-final-check.log，包括新路径校验/实际引擎和全部八类原A8实际回放。本批无跳过，不是系统最终全量。

实际CLI首次成功；随后固定约14KB样例examples/options/monthly-variable-path.json和scripts/verify_monthly_path.py补齐新目录自动准备/精确预期/逐日核对，并实际执行通过。最新证据reports/v19-implementation/monthly-path-cli-20261011-final/verification.json，原生CLI返回0，源码再次匹配；47交易日官方引擎净值与独立账本一致。单账户同资本两期SPY200/300股、IEF各50、Put2/3张，精确独立预期/账本100642.7416、引擎显示100642.74，重复导入新增0，终态持仓与应收应付0；此前口头近似100642.736已以精确证据纠正。GOAL hash保持原样。

全部synthetic_variable_path，两采样点日内同价为工程假设，不是真实期权历史、实际账户业绩或自然前向；测试值不作为投资预测。操作及命令记V19-USAGE。本批只推进H3机械输入/账务，不能宣称完整H3：变量路径统一三组比较报告、多期权主标的及自然行权/指派桥接仍待；现monthly_replay仍拒绝生命周期，plan-simulate原固定100/单张限制独立保留。下一具体动作贯通变量路径的同资本比较与官方自然生命周期账户任务，随后父关闭/ExecutionGroup/严格父版本和H4统一任务/四页、原P5/O6/H5同源码最终验收。外部实际期权/券商/自然前向条件未取得，Goal active，v1.9未完成。

## 当前批次：H2统一账户理论压力（2026-10-11）

新增hedging/stress.py和只读hedge-stress。实际账户股票/全部已有期权为未追加候选基线，候选追加筹资/新保护并以同一冻结权益及E_post摩擦为锚；复用QuantLib理论价值变化，不以理论初始价替换市场报价，不重复扣保费/费用。显式基准涨跌、IV倍率、时间推进、Beta敏感度倍率与逐标的残余收益；所有已有/新增合约模型必须完整、确切版本，缺项阻断。已有短Call有符号数量两侧一致；不跨未经观测到期路径。最大300情景/1500合约情景，有限网格不推断最大亏损，executable=false，成功/失败均不写任务或账本。

首组23项相关回归通过（17.71秒）；追加减仓现金及既有Collar符号样例、连同股票数量与原期权stress回归，最新同源码43项无跳过通过（36.85秒），hedge-stress-final-check.log。手算100股减持后保留卖出现金，仅扣10费用；下跌20%时原权益21000、候选22990，保护差额1990。入金仅抬升权益不改变情景投资盈亏；平价同日仅扣原候选摩擦，Put/Collar到期价格变化、IV/时间、代理失效及缺项阻断均验证。非系统最终全量验收。

首轮CLI三个成功分支通过，缺模型分支实际正确返回2/MODEL_INPUT_REQUIRED，但脚本从stdout而非stderr读取失败信息，导致校验脚本失败；已修正脚本读取通道，未改业务门禁。最新4条实际CLI（Put/重复/Collar/缺模型）通过，返回0/0/0/2，原账户序号/任务数不变、源码指纹再次匹配。证据reports/v19-implementation/hedge-stress-cli-20261011-final/verification.json；脚本scripts/verify_hedge_stress.py。全部synthetic_scenario_only，不是真实行情、自然前向或实际账户业绩，操作与模型限制记V19-USAGE。

H2理论情景已阶段交付，但Beta倍率不是估计相关系数，反向产品终点情景不是日复利路径，现金/应收应付保持冻结，未模拟期间分红/提前指派/实际交割。下一项H3扩展官方LEAN非恒定多股票/多张数和自然生命周期账户桥接，现monthly_replay仍固定100/单张，不能拼接旧诊断冒充研究。父关闭/ExecutionGroup/严格分配父版本、来源/行动资格、H4任务/四页及原P5/O6/H5同源码全范围验收保留。外部真实期权/券商/自然前向条件仍未取得；Goal active、v1.9未完成。

## 当前批次：H2期权数量候选与父意图备份（2026-10-11）

新增hedging/option_sizing.py、option_preview.py，hedge-preview接保护Put/Collar/代理Put；share_protection与beta_target分开，直接Put/Collar亦支持显式Greek的Beta目标。复用A8选约/原链、账户前缀、持久保护引用和当前原生预留；已成交/在途扣除、整张与零碎、保护窗口、未关联风险及卖出Call覆盖约束。Greek归一一次，逐腿符号/时间/模型明确；筹资总Put权利金/全费用不提前使用Call款，按冻价格重算筹资后B/E。所有候选仅研究executable=false，无新账本/预留/任务。

首批29通过/1失败为数值字符串精度预期，改为Decimal核对；随后30相关回归通过。父完整恢复扩展21通过/1失败发现真实代码缺陷：通用备份扫描将原请求的期权链snapshot_id当作股票行情引用；已按期权上下文识别，父引用仍独立加载原链验证，缺链/篡改不放行。最新同源码44项期权数量/父意图/股票候选/选约回归无跳过通过（43.79秒），hedge-option-beta-check.log。独立手算Put两张B=15000/E=25986、Collar两组B=5000/E=25972；占用100股后不可再拟两组，恢复原父/链一致并拒绝删除链。此次两次启动因相对日志路径的大小写沙箱映射失败，改绝对小写路径后运行成功，未改权限。

7条实际CLI已通过：Put/重跑/Collar/代理Put/缺Greek/直接Put Beta/Collar Beta，源码指纹再次匹配，账户序号与任务数不变。证据reports/v19-implementation/hedge-option-preview-cli-20261011-beta/verification.json；脚本scripts/verify_hedge_option_preview.py。缺Greek返回明确NO_FEASIBLE_HEDGE诊断，非任务失败；全部synthetic_restated_account_research，不是实际期权行情、真实账单或自然前向绩效。旧5CLI保留历史，不替代当前证据。操作字段/费用/保护与Beta口径已记docs/V19-USAGE.md。

本批为H2数量与原链/持股桥接阶段，不宣称H2/H3完整：压力情景/残余相关风险、来源/行动资格、父关闭/ExecutionGroup/严格分配父版本、H3非恒定多股票/多张数及自然生命周期账户桥接、H4统一任务/四页和原P5/O6/H5同源码最终验收仍待。下一具体动作复用QuantLib/stress实现账户与候选统一情景，再扩展H3引擎；不将旧固定100/单张诊断当组合研究。外部实际期权/券商/自然前向条件未取得，Goal active、v1.9未完成。

## 当前批次：H0父研究决定绑定与修订（2026-10-11）

新增hedging/intents.py和hedge-intent预检/显式提交、hedge-intents只读原最新修订。父ID绑定账户/稳定证券范围/目标名称版本模式/决策与触发，冻结Spec/Exposure/候选、登记身份、基础策略、资源hash及实际生成时间；输入修改形成同父revision，不覆盖旧记录。同版本改参数拒绝，换版本但范围/有效期重叠仍拒绝。MANUAL_HOLDINGS显式声明，其他基础策略需该账户ACTIVE绑定且已生效。历史重建仅demo并明确标记，前向拒绝重述/未来或结束窗口。资源hash新增父意图与保护引用审计；备份核验风险/身份和修订链。所有父对象DRAFT/RESEARCH_ONLY、executable=false，无新财务预留。

首轮17通过/1失败（26.38秒）：旧v1环境无strategy_bindings表，未绑定策略走到底层SQLite错误；已改为明确HEDGE_BASE_STRATEGY_NOT_ACTIVE，不自动迁移。18项回归及首组7CLI随后通过。复核UTC午夜附近生效日后改用纽约日期，追加独立正反两例；第一次扩展18通过/2失败（28.22秒）为样例INSERT占位符数错误，已修正样例。最新同源码20项父意图/保护引用相关回归无跳过通过，21.91秒，hedge-intent-current-check.log。覆盖原决定/修订、参数与范围冲突、未绑定/时间/资源拒绝、部分成交/并发CAS、完整备份恢复及篡改；纽约尚未开始的下一交易日策略不会在UTC午夜提前生效，已生效版本正向分支通过。

最新7条实际CLI已通过：预检、提交、重跑、只读列表、同目标版本改参数、同请求内容冲突、另一Spec版本重复范围；返回0/0/0/0/2/2/2。原账本序号不变，父修订1，无新预留；源码再次匹配。证据reports/v19-implementation/hedge-intent-cli-20261011-final/verification.json，脚本scripts/verify_hedge_intent.py。该数据synthetic_historical_reconstruction，不是自然前向或真实交易。旧源码7CLI保留历史，不替代当前验证。

父研究绑定已实现，但关闭/滚动、ExecutionGroup、ProtectionAllocation严格父版本绑定尚待；H2保护Put/Collar/代理Put候选仍未实现，H3变化原价多标的/多张数和自然生命周期账户桥接、H4统一任务/看板及P5/O6/H5最终全范围验收保留。下一具体动作优先H2期权数量与真实持仓/在途保护桥接，再收尾父关闭/执行组和H3，不将固定100单张旧诊断直接拼成新账户回放。真实期权来源/券商/自然前向独立受阻，Goal active，未完成v1.9。

## 当前批次：H0保护引用持久版本与事务（2026-10-11）

新增hedging/allocation_store.py及hedge-allocation-basis/hedge-allocation预检和显式提交。SQLite tasks独立审计命名空间保存不可变连续版本链，不新增财务预留或自动迁移。覆盖必须引用登记身份和当前账本前缀，合并全部旧引用/变化/显式退出后重验同股份和张数；更换请求或参数版本不绕过旧父引用。修改同ID不能换父/资产/合约/角色。提交在publication_lock/同一事务内复核分配版本与计划/绑定/来源资格/行情角色/期权审计资源hash。重跑相同请求返回原审计，相同ID内容不同冲突；原审计描述历史快照。引用退出不撤销订单或释放预留，未关联实际风险仍显示。备份核验版本链、原前缀和身份引用。

首批31项相关回归无跳过通过（33.48秒）；追加真实部分成交和两个独立连接并发后，同源码33项无跳过通过（33.88秒），日志hedge-allocation-store-final-check.log。独立样例两张在途保护200股→一张成交保护100/一张剩余意向100，账本现金与原预留201保持不变；同一依据两个写入只允许一个COMMITTED，另一个STALE_ALLOCATION_VERSION。无新事件但原生计划变化仍使预检失效。重复、原版本保持、跨版本覆盖拒绝、原子失败、完整备份恢复和篡改拒绝均覆盖。本批无失败，非整个系统最终全量。

7条实际CLI核对已通过：basis、预检、提交、重跑、新basis、另一父重复保护和请求ID冲突；返回0/0/0/0/0/2/2，账本序号3、持久引用版本1、不产生额外资金/持仓预留。当前源码指纹再次核对，证据reports/v19-implementation/hedge-allocation-store-cli-20261011/verification.json，脚本scripts/verify_hedge_allocation.py。数据为明确synthetic_test_statements，不是实际交易/期权来源/策略业绩。

本批只有保护引用持久化，parent_id是固定引用，正式HedgeIntent/Spec/Exposure/候选及ExecutionGroup绑定尚待；来源/行动资格关联、H2期权候选、H3多标的变化原价/多张数及生命周期桥接、H4任务/看板与P5/O6/H5统一验收未完成。下一项建立正式父意图绑定与修订关系，再推进H2/H3，原P/O/H全范围保持，Goal active。真实期权来源/券商/自然前向独立待补。

## 当前批次：H0不可变证券身份登记（2026-10-11）

新增hedging/securities.py、security-register预检/显式--commit和身份模板。固定内容版本、登记记录hash及原登记时间，原子发布/重复复用；旧引用不随新版本隐式升级。代码有效窗口、稳定ID资产类型/市场和跨ID代码冲突门禁；synthetic仅demo，declared仅身份声明，不能自填verified。来源/公司行动引用尚未授予或核验业务资格。coverage可显式绑定security_versions，校验ID/环境/有效期/当时已登记并引用记录hash；旧映射保留未登记研究标注，executable=false。备份复制既有hedging范围并新增证券登记核验。

首轮23通过/1失败（36.51秒）：完整备份样例未切换到配置对应的工作目录，被备份路径隔离正确拒绝；修正样例cwd，未改业务约束。最新同源码27项证券登记/账本覆盖/风险归档相关回归无跳过通过，35.56秒，hedge-security-final-check.log。覆盖身份不可变/原版本复用、单位/窗口/冲突、后来登记、内容篡改/链接、完整备份恢复及既有前缀/人工订单覆盖。旧失败日志hedge-security-check.log保留。

7条实际CLI已通过：身份预检/登记/重跑，绑定版本的覆盖成功/重复、非法前缀、错误身份；返回0/0/0/0/0/2/2，序号3，登记通用任务2条，覆盖读取/错误不新增任务或资金预留，coverage_id及原登记版本一致。当前源码fingerprint再次核对匹配；证据reports/v19-implementation/hedge-security-cli-20261011/verification.json，脚本scripts/verify_hedge_coverage.py。模板/账单均明确synthetic，非真实合约或来源凭据；GOAL未修改。

下一具体动作：父意图和ProtectionAllocation持久版本/跨版本冲突及事务资源依据，再完成H2期权候选、H3多标的变化原价/多张数与自然生命周期账户桥接、H4统一任务/看板和P5/O6/H5全范围同源码验收。证券来源/行动资格关联仍待，不把已登记身份当成已核资格；实际期权来源/券商/自然前向独立受阻。Goal active，v1.9尚未完成。

## 当前批次：H0指定账本前缀与人工在途覆盖（2026-10-11）

新增hedging/coverage_service.py和只读hedge-coverage CLI。真实持股/期权张数从单一账户前缀派生，条款从注册内容核对版本/创建时间，real复用实际单位凭据核验；输入不能覆盖实际数量或交割单位。人工在途只接受明确提交未结束的计划，复用剩余张数和既有预留；草案不当在途。所有前缀凭据及人工状态须在知识截止前取得；demo restated可明确后来截止而保留原时间，known_then不得晚于覆盖时点。修复纯coverage此前对较早知识截止的不必要限制。security_ids仍是声明式研究映射，证券注册/来源资格和父意图持久化待接入，结果始终executable=false。

首轮测试收集失败为引用不存在样例helper；已改用现有plan/manual_action。第二轮27通过/5失败为样例生成顺序使分配记录晚于知识截止，以及CLI试图改写固定runtime/demo环境目录；修正样例顺序、用SQLite backup建立隔离合法运行目录。第三轮32通过/2预期错误码不符，第四轮35通过/1错误码不符；保留失败日志。相关拒绝均符合现有门禁，未放宽业务；最终独立核对前缀3保护100股、后续前缀4平仓保护0，追加无分配最新前缀核验。

最新同源码36项保护分配/前缀/人工订单相关回归无跳过通过，31.42秒，hedge-coverage-current-check.log。含未关联期权保留、部分成交100股实际/100股在途、无重复预留、注册单位冲突、较早知识截止、未来/迟到/未知前缀及草案阻断。3条实际CLI成功/重复/非法前缀全部通过，返回0/0/2，序号3、任务0、coverage_id稳定；当前源码指纹已再次核对。证据reports/v19-implementation/hedge-coverage-cli-20261011/verification.json，脚本scripts/verify_hedge_coverage.py。数据明确synthetic_test_statements，不是实际券商凭据或策略业绩；GOAL SHA未改。

下一动作证券身份/父意图持久化与ProtectionAllocation事务，H2保护Put/Collar/代理Put整数候选；随后H3多标的变化原价/多张数及自然生命周期桥接→H4统一日常/看板→P5/O6/H5全范围同源码验收。真实期权来源/券商/自然前向独立待补，Goal active，未完成v1.9。

## 当前批次：H0保护分配独立计算（2026-10-11）

新增hedging/allocation.py只读coverage：稳定证券ID/实际股数切片、父意图、合约版本、有符号整数张数、实际/在途分支及条款时间。Collar同父Put/Call可引用同一100股但只计100保护；跨父或同角色重叠拒绝，张数/持股不可超分配。代理Put/错误权利/交割物不能标直接股份保护；条款未收到或分配超出条款窗口阻断。在途仅显示意向，未关联实际期权仍单独列出，不新增预留/账务。

首轮34项保护分配/股票数量相关回归通过（27.70秒），追加条款窗口/已知时点后最新同源码37项无跳过通过（29.37秒），日志hedge-allocation-final-check.log。最新3条实际股票预览CLI仍通过，非法输入明确返回2，事件/任务不变，当前源码指纹已再次匹配；证据reports/v19-implementation/hedge-allocation-preview-cli-20261011/verification.json。没有把纯函数样本称为计划接入或真实期权资格。

尚未完成：证券身份注册、统一账本及来源/计划适配、持久保护分配和部分成交/终止事务；H2期权候选、H3多资产变化价格及生命周期账户桥接、H4日常/界面和P5/O6/H5统一验收。下一项先从确切账本前缀和合约证据构造保护分配输入，完成H0事实适配后推进期权候选。真实来源/券商/自然前向独立受阻；Goal保持active。

## 当前批次：H0目标及H2股票候选（2026-10-11）

新增冻结HedgeSpec、股票减持/反向ETF整数候选及只读hedge-preview。数量是新增交易量而非目标总量；价格/Beta须匹配归档，筹资和费用进入B_post/E_post。卖出筹资不提前成为可用现金；超出max_cash的现有现金保留。proxy_symbols允许非持仓代理在同一完整收益窗口估计。所有结果executable=false，不生成计划或写账；期权候选尚未实现，证券资格、父意图及实际保护分配接入仍待。

首轮26通过/2失败：独立数量比较误用字符串精度，以及源码编辑与CLI测试同时执行触发正确的指纹守卫；第二轮28通过/1样例依赖未注册。已修正样例与执行顺序；29项风险/归档/数量回归通过（49.71秒）。之后修正现金预算保留边界，最新16项数量相关回归通过（28.65秒），含费用、预留、禁止卖空、预算、KEEP和CLI；这两批源码不同，不合称最终全量。最新3条实际CLI检查通过，减持IEF37股、预计Beta23900/30000，重复预览身份相同、非法参数返回2；事件/任务不变。证据reports/v19-implementation/hedge-preview-cli-20261011-final/verification.json，原批源码指纹匹配，后续新增分配模块会改变当前源码身份，最终统一验收另做。

下一动作保护分配计算与证券/父意图完整契约、H2期权候选、H3变化价格多标的及自然生命周期账户桥接→H4→P5/O6/H5。真实期权来源/券商/自然前向未补齐，Goal active。

## 当前批次：H1归档与历史期权前缀（2026-10-11）

统一options/valuation.quote_set增加可选ledger_seq：指定时按该前缀持仓/条款估值，默认当前行为不变。H风险调用同一前缀，不再借后来平仓或更正后的当前持仓；知识截止和报价来源/时效仍检查。Exposure新增原账本前缀hash。hedging/archive.py及hedge-exposure --archive原子发布完整不可变风险结果，重复复用、篡改/链接拒绝；备份核验账户/环境/原前缀和原价/收益/期权快照引用，不按新源码覆盖旧归档，不预留或记账。

首轮24通过/1失败（46.64秒）发现备份显式清单遗漏hedging目录，导致恢复缺归档；已加入复制范围。第二轮24通过/1失败（46.85秒）为独立缺价样例发现归档引用检查漏包装FileNotFoundError，现统一返回CORRUPT_EXPOSURE_ARCHIVE。保留失败日志，不掩盖。最新当前源码25项相关回归无跳过通过，49.66秒（hedge-archive-current-check.log），含完整恢复、原账本篡改、文件/缺价及既有风险/账户估值行为。

历史期权独立算例：前缀3持SPY100股、Put2张；后续序号4已平仓，同一截至时点当前估值NO_OPTION_POSITIONS，但前缀3中价2.05、权益30010、一阶Beta金额约0，Greek整份-100股不重复乘张数。冻结归档仍保存ledger_seq3。后来入金后原快照字节与依据不变，完整恢复可按原ID读取；原账本前缀直接篡改则拒绝。

8条实际CLI检查通过：只读成功/重复、未知当时账本错误、归档/重复、backup-bundle/verify-backup/restore；7条返回0、预期错误返回2，序号3/任务数量不变、归档和恢复对象相同，当前源码hash匹配。证据reports/v19-implementation/hedge-archive-cli-20261011/verification.json；数据为明确合成重述风险，非真实投资业绩/对冲交易资格。

下一动作完成H0证券/目标/保护分配契约并实现H2预算/数量候选，再扩展H3多标的/变化价格/多张数及官方生命周期账户桥接→O/H任务/H4→P5/O6/H5。H1目录/模型资格及全部验收仍需与后续统一核对；真实期权来源/券商/自然前向未新增。Goal active，未完成整个v1.9。

## 当前批次：H0/H1只读风险基础（2026-10-11）

检查确认月度LEAN主动拒绝自然生命周期，且固定100/单张；已有诊断案例的开仓时间/价格与月度计划不同，不直接拼接成交冒认兼容。官方生命周期桥接/H3引擎扩展保留；按H计划可穿插先实现独立风险计算。新增hedging/exposure.py及service.py、hedge-exposure只读CLI和请求模板。风险契约schema1绑定双行情快照、账本序号/known_then或demo restated、知识截止、模型阈值、资源/源码hash及曝光ID；H0完整证券/目标/保护分配契约未完成。

共同126个收益/127个完整价格、简单总收益带截距OLS、R²/相关性/标准误、零方差/缺日/迟到/零量门禁；股数按原价市值生成Beta金额，全账户权益作分母。Greek显式per_share/per_contract/position_total、有符号张数及真实合约版本，只归一一次；期权既有风险不可漏算，缺项仅展示已知部分。发布时效与价格时差分别配置。供应商或模型输入仅研究参考，未授予独立Greek资格；历史期权前缀明确拒绝借当前持仓估值。CLI成功/失败均不写事件/计划/任务。

首轮17项通过（26.25秒）；扩大后30通过/1失败（51.11秒），失败为测试从stdout读取既有CLI错误JSON，而协议实际使用stderr，已修正测试预期。当前同源码31项无跳过通过，50.94秒（hedge-exposure-current-check.log），覆盖风险、凭据及估值相关回归。独立算例：100股@100/Beta0.5及100股@200/Beta1.5，市值30000、B35000/Beta7/6；增加10000现金后B不变、比例0.875；两张Put整份Delta-100股只产生-10000金额；净名义0但Beta7000不称中性。未来行情不改变过去Beta；缺日不桥接收益，未知当时账本和未来风险时点拒绝。

3条实际CLI检查通过：成功/重复返回0、相同Exposure ID/Beta结果；当时未收到的账本返回2/LEDGER_NOT_KNOWN，全部序号3及任务数量不变。当前源码hash再次匹配，证据reports/v19-implementation/hedge-exposure-cli-20261011/verification.json；数据明确synthetic_restated_account_risk，非真实账户或历史表现。

下一动作完成H0证券/目标/分配契约及H1统一归档/历史期权前缀，再推进H2/H3变化价格多标的和生命周期引擎扩展→O/H任务/H4→P5/O6/H5。原P/O及H范围保留；真实期权来源/券商/自然前向仍待，Goal active，尚未完成v1.9。

## 当前批次：生命周期凭据日常处理与待核实解决（2026-10-11）

新增options/receipts.py，显式批次ID/rows预检哈希/账户序号、原子事实和审计；daily新增--option-receipts及--option-resolutions。普通账单后推进明确期权凭据、再执行冻结模拟；未核实或错误停止后续模拟。每次刷新待核实状态，已解决后重跑原批次不会复活凭据。真实记录仍需actual和实际单位证明，不以到期日期、理论值或机械样本自动推断通知。修复同ID待核实/已记账冲突，以及注册条款后普通导入绕过原待核实记录的漏洞，必须显式resolve。备份核验日常凭据步骤和原生批次审计及请求哈希。

首轮39通过/3失败（40.98秒），失败为新增测试样例重复传入effective_at参数，已修正样例。最新54项无跳过通过，53.21秒（option-receipts-final-check.log），覆盖三类生命周期手算、两个提交边界恢复、待核实/显式解决/阻断、ID冲突、未来/预检/序号、完整备份恢复及审计篡改，含既有账本/daily/估值回归。原冻结开平仓daily兼容7项回归也已无跳过通过，131.23秒（option-receipts-simulation-check.log），包括开仓/平仓两边界恢复及完整备份；与54项为当前同源码分批验证，不代替全项目最终验收。

9条实际CLI检查已通过：到期/指派/行权各执行和重复，以及待核实、补齐条款后解决、重跑；全部按预期返回3，因股票信号数据缺失，生命周期处理本身SUCCESS或待核实时BLOCKED。事件序号稳定；手算现金分别9800/200/10000、指派获得100股，其余基础股归零。全部是synthetic_test_statements，不是券商凭据；当前源码指纹匹配，证据reports/v19-implementation/option-receipts-cli-20261011/verification.json，日志option-receipts-cli-check.log。

下一动作继续官方引擎生命周期账户桥接/H0–H5及统一P5/O6/H5。实际期权来源/券商权限/自然前向仍待，Goal active，本批不宣称v1.9完成。

## 当前批次：日常冻结期权成交及中断恢复（2026-10-11）

daily新增显式option_tasks数组，demo内按顺序推进已冻结OPEN/CLOSE，校验同账户/同处理时点。原生原子成交审计与日常步骤分开持久化，两个提交边界中断都复用事实；失败停止后续任务和股票模拟，恢复成功保留原因并标RECOVERED。备份验证日常成功步骤与原生审计一致；不把期权快照误当ETF输入。CLI新增--option-tasks，操作见V19-USAGE。

首次相关回归31通过/1失败（159.81秒）：测试试图在单账户数据库创建第二账户，被SINGLE_ACCOUNT正确拒绝。改为外来冻结请求所属账户样本，保留约束；补充OPEN中断恢复及临时失败后恢复。最新34项无跳过通过，164.22秒，option-daily-final-check.log；覆盖CLOSE两提交边界、OPEN原生提交中断、幂等、失败停止、时点/账户、完整恢复及既有daily/估值行为。六条实际CLI调用在独立合成工作区已通过：OPEN/CLOSE各错误时点阻断、正确执行及重复执行；全部按预期返回3，因为股票信号数据缺失，期权执行分别SUCCESS且权益99993/99986、序号2/3不重复。报告ID稳定、源码指纹与当前一致；证据reports/v19-implementation/option-daily-cli-20261011/verification.json，日志option-daily-cli-check.log。

本批仅推进事前冻结的历史合成成交，未获取真实期权数据/券商权限；有凭据官方生命周期任务编排、H0–H5及统一P5/O6/H5仍待。下一动作继续有凭据官方生命周期任务编排及H0–H5，最后统一P5/O6/H5，Goal active。

## 当前批次：账户期权估值、来源核验与日常报告（2026-10-11）

新增options/source.py及valuation.py，来源契约独立schema2/OPRA、确切合约版本、报价/时点/行动/许可说明与真实核验证据；沿用股票来源的统一不可变证据归档，禁止以股票资格、CSV标签、test或引擎案例代替。实际报价须范围/有效期/凭据及单位证明合格；paper/real不倒用后来登记。仅合成demo可在明确标签下估值，真实期权数据/券商权限尚未新增。

报告读取显式链快照和配置化检查参数，用bid/ask中价每报价单位估值，负债及乘数在统一账本计算一次；缺/迟到/旧价/单位冲突/价差等使权益保持不完整。修复有期权却标CASH_ONLY的问题。报告和日常估值步骤引用的期权快照纳入完整备份/恢复；daily新增可追溯估值阶段及独立期权对账，股票数据/计划检查仍独立。账户页新增中文报价/来源结果及截至时间，不因刷新记账。

首轮估值/来源10项回归无跳过通过，9.88秒；接daily后35项通过，36.22秒；最终当前源码36项报价报告/来源/资金/日常/备份/Streamlit组件回归无跳过通过，49.83秒，日志option-valuation-ui-check.log。独立手算：10000入金、卖Put收200、费2、负债205，权益9993/投资盈亏-7；再入金1000后权益10993、盈亏仍-7。真实标签和test资格均不能产生完整权益；scope及归档篡改阻断。正向资格分支仅形式凭据测试，不代表真实供应商核验。

6条实际CLI检查通过：来源登记/重复、报告/重复各返回0；两次daily因无股票信号数据按预期返回3/BLOCKED，同时期权估值9993及独立对账PASSED、报告ID一致、事件仍2/股票计划0。首个验证脚本误将该BLOCKED预期为0，已按现有退出码修正，未放宽业务门禁。证据reports/v19-implementation/option-valuation-cli-02d0798587d545a8a638e59836d682ed/verification.json；当前源码hash再次核对一致。操作/模板见V19-USAGE和templates/demo-option-valuation.json。

上批A8追加退出终态5项无跳过通过，792.56秒（exit-task-extra-a8-check.log），八模板均有阶段性账户CLOSE覆盖；它与前10项为对应源码的历史证据，不替代新增估值后的最终全量。下一动作：把冻结开仓/退出及有凭据生命周期接日常任务恢复，继续H0–H5，最后统一P5/O6/H5安装/全量/CLI/浏览器/交付。Goal active，不把估值对账成功称为完整策略跟踪或v1.9完成。

## 当前批次：A8退出覆盖与冻结报价双时点（2026-10-11；继续验证）

原三模板最新退出回归终态10项无跳过通过，962.53秒（exit-task-final-check.log），覆盖实际CLOSE、取消/替换、无成交资源变化CAS、T+1/历史序号及CSP完整备份恢复。A8另外五模板已补独立现金/标记价格预期并执行补充回归（exit-task-extra-a8-check.log），仍运行，尚不提前计通过。三模板21CLI为双时点修正前证据，历史归档保留，最新源码全项目验收另行执行。

发现并修复迟到处理边界：模拟此前按处理时点判断执行报价过期，可能错误拒绝冻结成交时点的有效历史报价。现quality支持显式knowledge_cutoff，开仓/退出按冻结成交时点检查价格/合约，按处理时点检查实际到达；默认实时决策/选约/信号语义不变，不改报价原时间。17项报价/选约/月度信号回归无跳过通过、6.04秒（option-clock-check.log），独立核对未来价格、晚到但未收到、倒置知识时点及实时旧价仍过期。

最新实际延迟平仓3条CLI已通过，源码hash核对与当前一致；证据reports/v19-implementation/delayed-exit-verification.json及delayed-exit-final-check.log。未收到报价退出码3且无写入，迟到但已收到报价在22:01处理原21:00成交，权益99986、重复无新增。最新开仓延迟一小时、原子失败/重跑、T+1/DST及完整恢复回归已通过，1项无跳过、123.60秒（opening-clock-check.log）；合成引擎在Linux临时目录运行，长期验证日志保留项目内。首个延迟CLI验证脚本错误预期退出码2，实际按现有MISSING_*规范为3，应用正确拒绝尚未收到报价；已修正验证脚本，未放宽应用。A8补充已完成三组且仍运行，价差两组等待终态，不预先计通过。下一动作：核对A8补充进程终态，完成本批证据记录，再继续官方生命周期/daily及H0–H5和统一P5/O6/H5。真实来源/券商/自然前向未补齐，Goal active。

## 当前批次：冻结退出与成熟引擎平仓集成（2026-10-11；验证进行中）

新增exit_tasks.py及exit-freeze/exit-simulate/exit-cancel CLI；冻结明确退出用途、当前/下一交易日收盘及20分钟截止，执行绑定已模拟开仓的同一成熟引擎CLOSE归档、已到达报价、逐腿依赖和资源指纹。只导入期权平仓，保留账户基础股票；批次失败回滚、重跑幂等、T+1结算。取消仅关闭未执行意图，不释放实际担保、不取消实际事实。备份新增退出审计和报价/报告引用核验，看板加入退出审计及待办。仅合成demo，完整官方到期/行权/指派账户任务、daily、H和最终验收仍待。

首轮24项终态为21通过/3失败、522.34秒；3组被同一个错误拦住：冻结意图误计账务异常，自阻断对账。现将pending_option_exits独立展示并在股票/期权数量规划阻断新增风险，保留真实账务检查；另修正开仓任务身份需digest(plan_id)的关联。利用归档成交作可回滚核验，CSP平仓权益99986、退出意图清除。畸形请求及历史写入绕过占用等7项守卫通过、8.84秒；不是全量验收。

CLI初次被示例20:42重新冻结正确阻断（21:00收盘的截止为20:40），已调整示例时点，未放宽门禁。第二轮旧输入测试仍在运行，最新输入、恢复/取消/资源CAS及实际CLI等待终态；证据日志exit-task-check.log、exit-task-guards.log、exit-cli-final-check.log位于reports/v19-implementation。后续仅Python变更可显式复用27场景不可变引擎证据，fixture仍逐A8审计当前C#源码/程序集/冻结输入，不跳过资格检查。

最新21项资金/期权守卫/四页Streamlit组件回归无跳过通过，38.21秒（exit-risk-ui-check.log）。三模板实际21条CLI全部通过，证据reports/v19-implementation/exit-cli-f81eae5140e343b49ab56d6fcf818a1c/verification.json；当前源码指纹再次核对一致，CSP/保护Put平仓权益99986、collar99972、后两者保留100股、实际担保及退出意图归零。第二轮加载旧20:42替换输入的终态29通过/3失败，552.04秒；失败仍为正确20分钟门禁，最新正确时点回归已独立启动（exit-task-final-check.log），CSP已进入完整恢复验证，不提前记通过。

恢复核验后继续扩大A8实际账户退出覆盖：新增Long Call/Put、备兑Call、牛Call/熊Put价差五组独立现金算例，仍调用实际成熟引擎CLOSE，不缩放成交或重复导入股票。补充回归已运行，日志exit-task-extra-a8-check.log；原三模板最新回归已完成两组且仍运行，未先计最终通过。

下一动作：核对最新恢复/资源/历史及A8补充回归终态，修复剩余问题；更新确切命令/结果，再接官方生命周期任务和daily，随后H0–H5及统一P5/O6/H5。Goal active，真实期权来源/券商/自然前向未补齐，不宣称v1.9完成。

## 当前批次：股票对冲计划复核R2.1（2026-10-11）

逐段核对H计划与期权/账户源码，补充10项设计缺口，见docs/V19-HEDGING-REVIEW.md。7项高优先级涉及引擎固定100/单张限制、事前时点、筹资后数量、退出风险、代理Put失败交割、无成交资源变化和已成交保护/Greek单位；3项改进涉及统计样本、静态跨月及公平对照。修订H/主计划/O计划/agents/DECISIONS，16组验收规格扩为28组。原P/O未完成工作保留；本轮不实现业务代码。

文档校验已通过：65处本地链接、10项发现到验收的映射、28组规格编号，以及独立筹资/减持与空头/Delta/费用/保护算例。155个源码、配置、测试、依赖、README及GOAL基线文件前后哈希一致。执行证据reports/v19-hedging-review/verification.json；原R2报告保留。不将28组待实现验收规格称为28项测试通过；未重跑业务回归，真实来源/账户权限未新增。下一项：收尾O3/O4退出生命周期，再按R2.1契约和H3适配前置推进，最终P5/O6/H5同源码验证。Goal active。

## 当前批次：股票组合对冲调研与v1.9范围追加（2026-10-11）

用户要求调研股票对冲并加入当前系统规划。已读取当前策略/期权/资金接口，核对OIC/Fidelity、CME、SEC、FINRA、NBER、MSCI/French及LEAN官方资料。产物docs/V19-HEDGING-RESEARCH.md和docs/V19-HEDGING-PLAN.md，主计划/期权计划/agents/DECISIONS已联动；H0–H5核心新增，HX1–HX4列条件扩展，原P0–P5/O0–O6不删减。

核心规划包括账户风险快照、同标的保护Put/Collar、指数/行业ETF代理Put数量、减仓/反向ETF同资本对照、统一意图/资源/退出及四页。补充市值加权Beta、Delta单位、跨标的不能覆盖短Call、代理Put交割失败、基础策略与保护冲突、反向ETF多日路径、PIT/成本/公平基准和16组独立验收算例。官方CME示例的股数加权Beta亦要求独立纠正，不照抄算式。

本轮仅文档，H尚未编码或验收；真实股票/期权/借券/期货来源与账户权限未新增。主计划历史“待实施”及未安装引擎描述按已有PROGRESS证据校正，保留最终验收未完成。7份文档、57处本地链接、6个核心批次、4个条件扩展及16组验收条目检查通过；市值加权Beta、目标数量、Delta单位、保护Put/Collar两端收益及反向ETF复利的独立Decimal算例通过。证据reports/v19-hedging-planning/verification.json；GOAL哈希未变，业务代码未改、未重跑业务测试。下一项开发：继续O组退出执行/生命周期共用契约，再按H0/H1→H2/H3→统一任务H4→P5/O6/H5推进。Goal active，不把调研当功能交付。

## 当前批次：退出窗口、报价与条件资金检查（2026-10-11）

新增management.py及exit-review只读CLI，完整参数/未知字段校验；窗口按行权截止本地日期减显式自然日，非交易日提前到上个交易日，半日收市及最后交易期限取更早，在收市前20分钟检查。NOT_DUE/NO_POSITION不制造交易。只关闭本计划实际剩余张数，报价必须已到达、版本一致/价差/数量/时效合格，多腿核对时间和标的价格；短腿先关闭，保护长腿depends_on明确。

买回预算只在完成本计划短腿平仓后计其条件担保释放，不实际释放账本担保、不借其他持仓担保、不预支保护腿卖款。独立例：两张100 Put回补2.1+费用4需424；原担保20000不提前变动，实际现金100则阻断。同合约另有一张空头时只计算本计划20000释放、保留另10000担保。研究规则hash、稳定management_id及账户模式保留。CHECKED仍DRAFT/executable=false，不授予执行、自动滚仓或真实权限；拒绝commit。

当前源码30项相关回归无跳过通过，4.13秒（management-source-check.log），含10项退出及20项生命周期/资金/人工回归；核验Nov29半日检查17:40Z、周末提前至Nov22、未来报价/不同步/缺数量阻断。当前源码2条实际CLI通过、结果一致且无账本/任务写入；证据reports/v19-implementation/management-cli-829b4c03a60e4e96a725370ffd1da210/verification.json，源码hash和返回规则hash再次核对一致。此前只读CLI归档保留，但不代替最新源码证据。

上批成熟引擎4项回归及A8模拟32CLI已确认终态通过，详见后续批次。下一动作：把冻结退出建议接成熟引擎后续CLOSE/生命周期事件的原子账户任务，逐腿依赖、部分退出、幂等/历史/备份，再接日常发布和最终P5/O6。当前只读退出不能冒充完整退出执行能力；真实来源/券商权限/自然前向仍独立待条件。Goal active。

## 当前批次：账户计划开仓进度与持仓生命周期分离（2026-10-11）

修复：合法关联CLOSE/EXERCISE/ASSIGNMENT/EXPIRY/CASH_SETTLEMENT此前被当作开仓不符，令FILLED倒退并污染账户异常。现在开仓数量独立累计，管理事实只减少本计划持仓，不能消费其他计划或未关联的开仓；超量、合约/方向不符仍保留事实并阻断。execution_status维持开仓执行事实，新增lifecycle独立展示OPEN/PARTIAL_CLOSE/CLOSED及SETTLEMENT_PENDING/EXERCISE_PENDING/ASSIGNMENT_PENDING/RECONCILIATION_REQUIRED。到期日期本身不会清除义务，必须有确切凭据；历史时点及ledger_seq不倒用未来退出，冲销后重新派生状态。

20项资金/生命周期/人工事实回归无跳过通过，3.35秒（position-lifecycle-final-check.log）。独立现金：1000入金、两张Put各买2、各卖3，最终权益1200；部分平仓保持开仓FILLED与一张残留。Put行权交割原100股后现金19800/股票0；Put指派后现金200/股票200，均只交割一次。到期仅清除多头合同，现金800；冲销到期恢复OPEN。初测1失败/9通过为新增测试调用辅助函数重复quantity关键字，已修复测试构造，未改变现金预期。

涉及激活/部分成交/资金关闭及完整备份模拟的成熟引擎4项回归无跳过通过，185.11秒（position-lifecycle-engine-check.log）；实际7条生命周期CLI已通过（预检/提交/重复预检/重复提交/3个历史审阅），精确核对当前源码hash、开仓FILLED不倒退/未来退出不倒灌/1200权益；证据reports/v19-implementation/position-lifecycle-cli-86f140db812d4484a5e48dfd6c0e4833/verification.json。先核对终态，不预先计通过。先前32条A8模拟CLI现已全部通过，见下一批次证据；源码最终全量与清洁安装尚未完成。

下一动作：确认上述回归和CLI终态，再实现事前退出计划与成熟引擎后续平仓/生命周期账户任务、日常发布闭环；仅修复审阅状态不代表已经具备完整生命周期模拟入口。真实数据/权限/自然前向独立受限。Goal active。

## 当前批次：A8账户激活与开仓模拟（2026-10-11）

激活和模拟接口从单CSP扩展到A8八模板，仍仅历史合成demo。逐模板核验当前27例成熟引擎资格、冻结月度信号、同步当前报价、账户序号/对账及现金/股票约束；paper/real保留来源、账户权限和前向门禁。激活account_basis保存实际检查时快照，READY说明不再沿用草案无预留文本。

18项激活回归无跳过通过，81.02秒（a8-activation-check.log）；独立预算依次Long Call/Put222、保护Put122、备兑Call12、CSP9512、collar124、牛Call价差10224、熊Put价差9724，三个覆盖模板另预留100股。

八模板模拟资金/持仓独立检查通过：单腿开仓净损耗7、双腿14；CSP担保9500、牛Call10000、熊Put9500。研究中的100股构造及费用不再次导入已有持股账户，审计保留排除事件；每腿只取实际LEAN OPEN成交，不放大数量或导入后续月份。当前机械引擎spot100限制显式检查。

本批初次模拟测试8通过/1失败，320.43秒（a8-simulation-check.log）；失败在最后备份恢复测试的证据复制，原因/tmp耗尽，并非已通过8组资金预期失配。已清理本任务已完成且可重建的测试临时目录，/tmp空闲恢复约3.7GB；失败项单独重跑已通过，1项无跳过、115.72秒（a8-simulation-recovery-check.log），覆盖原子批次/重复执行/T+1/DST及完整备份恢复；24条激活CLI已全部通过：8模板各首次激活/相同请求重跑/只读审阅，预算及权益与独立预期一致，无重复成交或预留；证据reports/v19-implementation/a8-activation-cli-675f1164dcea44d5ae2fb4cd64cdfb67/verification.json。32条模拟CLI已全部通过：8模板各激活/模拟/同请求重复模拟/审阅，全部FILLED、单腿权益99993/双腿99986、担保及100股不重复。证据reports/v19-implementation/a8-simulation-cli-b984b68dd2a043ccb86f96b29e369321/verification.json；不是全项目最终验收。长期报告和用户运行数据保留。

下一动作：确认恢复测试及实际CLI终态，更新确切证据；继续统一账户的退出/生命周期/日常任务、最终P5/O6全量/清洁安装/浏览器及交付。真实来源/券商/自然前向仍独立待条件。Goal active，不能以A8开仓通过替代完整生命周期验收。

## 当前批次：A8必需生命周期分支贯通（2026-10-11）

成熟LEAN适配现27场景，增加collar_call_assignment、collar_put_exercise及bear_put_partial_assignment。collar Call指派交割原100股，剩余保护Put等待官方无价值到期；collar Put行权先按实际报价买回短Call、确认义务已清除，再交割100股，避免裸卖Call。熊Put短腿指派支付9500取得100股，保留长Put至下一交易日开市取得同步报价，再交割100股收10000恢复，不提前预支交割款。

独立现金：collar Call指派/剩余Put到期100486；collar关闭Call/Put行权99482（短Call买回0.02、三笔成交各费2、行权/交割费0）；熊Put恢复100386。熊Put中间现金90386/股票100/长Put尚在，缺期权估值时equity=None，不把后续报价倒用到过去；恢复后证券/期权归零。交割子事件由期权事实表示一次，不重复记股票。

1项27场景完整回归通过、无跳过，77.96秒（lifecycle27-check.log）；A8八模板逐分支工程资格全部PASSED但executable/source_qualified仍false。适配源码变更后再跑9项激活/资金关闭/人工历史/备份恢复及成熟引擎模拟回归，无跳过通过、188.19秒（lifecycle27-integration-check.log），不是全项目最终验收。

实际10条CLI成功：导链/27例回放/8模板审计。证据reports/v19-implementation/lifecycle27-cli-c6df543302814ef2a49bea82a2ccd617/verification.json；只读额外核对collar短Call CLOSE在Put EXERCISE之前，熊Put阶段股票/现金及最终归零，三组双腿到期方向与Long Put OPEN/CLOSE保持正确。未创建用户工作区账户DB或提交券商订单。新引擎源码使旧版本运行证据不能直接用于新激活/模拟；旧归档仍保留供历史恢复。

当前账户激活/模拟仍仅demo CSP；27例通过不等于其他模板READY、真实来源/权限或自然前向。下一动作：按八模板资金/股份/保护腿约束扩展激活与模拟接口，再贯通完整日常/退出/生命周期任务及P5/O6最终统一源码全量、清洁安装、实际浏览器与交付。离散分红、未知调整条款等边界仍按明确门禁保留，不用本批合成样本替代真实验证。Goal active。

## 当前批次：多腿到期与Long Put价内退出（2026-10-11）

成熟引擎现24场景，新增collar_worthless_expiry、bull_call_worthless_expiry、bear_put_worthless_expiry及long_put_itm_exit。逐腿生成同步到期报价，冻结合约方向分别映射LONG/SHORT，不能用首腿方向解释整个组合。逐模板资格核验实际腿数/各自官方到期事件及无内在价值；Long Put价内退出是实际市场卖出CLOSE，不记为OPTION_EXERCISE。

独立预期：牛Call价差、熊Put价差各支付净权利金110及两腿费用4，到期现金/权益99886、证券/期权/担保归零；collar净支出10+4，现金89986/100股估值10000/权益99986，覆盖占用归零但证券保留。Long Put买ask2.1、卖bid10，开平各费2，现金/权益100786，记录OPEN→CLOSE，无行权和残余期权。

1项完整24场景回归无跳过通过、65.68秒（expiry24-check.log），包含旧现金路径、所有执行文件hash、共享基线未被生命周期修订和桥接篡改阻断。6模板引擎单项通过：CSP、备兑Call、保护Put、Long Call、Long Put、牛Call价差。collar及熊Put价差仍缺部分指派/行权场景，BLOCKED；所有审计executable/source_qualified=false，当前激活仍只demo CSP。

实际10条CLI通过：导链/完整24例回放/8模板审计（6通过、2预期阻断）。证据reports/v19-implementation/expiry24-cli-9beba1fd83914d6fa47360ed1bae49cf/verification.json；另只读核验报告内3组双腿OPTION_EXPIRY分别LONG/SHORT，只有原开仓权利金记录，没有虚构平仓；Long Put账本明确OPEN/CLOSE且无行权。未建立用户工作区账户DB或提交券商订单。

下一动作：补collar两种行权/指派及熊Put价差部分指派恢复，形成A8完整分支证据，再扩展激活/模拟日常链路。最后按统一源码执行全量/清洁安装/浏览器/CLI及P5/O6。真实来源/券商/自然前向仍独立待条件，Goal active。

## 当前批次：备兑/保护/Long Call到期与资金完整行权（2026-10-11）

LEAN现20个实际场景。新增covered_call_worthless_expiry、protective_put_worthless_expiry、long_call_worthless_expiry和long_call_exercise；使用官方OptionExercise及实物交割事件，Call/Put各自方向生成到期执行数据，不再把到期文件名固定为Put。每个场景独立执行数据及清单/hash，A8普通回放不受后续冲击修改。

独立手算：备兑Call持有100股、终价95，无价值到期后现金90098/股票9500/权益99598；保护Put持有100股、终价105，现金89888/股票10500/权益100388。Long Call无价值到期现金/权益99788，无证券/期权残余；资金完整Long Call行权支付10000，取得100股终价110，现金89788/股票11000/权益100788。到期/交割费用显式0、成交费2；到期清除义务而不重复入权利金，不强制卖掉仍持有的股票。

1项完整成熟引擎回归覆盖20场景、无跳过通过，55.99秒（expiry20-check.log），核验原现金路径、独立股票/现金预期、执行文件hash、普通回放未被修订及桥接篡改阻断。逐模板资格CSP/备兑Call/保护Put/Long Call通过，executable/source_qualified均false；collar等缺失分支继续BLOCKED。当前激活仍只允许demo CSP，新模板未凭此审计直接开放READY。

实际7条CLI通过：导链→20例完整回放→5个模板独立审计（4通过/collar预期阻断）。证据reports/v19-implementation/expiry20-cli-86154697bcc347f490a56799f078f320/verification.json；同时核对3种保留100股场景的期权现金担保/覆盖占用归零，没有建立用户工作区账户DB或提交券商订单。

下一动作：补多腿到期、Long Put价内退出及剩余指派/行权分支，扩展逐模板激活/模拟任务；最终统一源码全量、清洁安装、实际浏览器和P5/O6仍待。真实期权/券商/自然前向独立受限，不以合成机械收益替代。Goal active。

## 当前批次：外部资金变化关闭未提交期权意图（2026-10-11）

激活后入金/出金关闭未提交部分，等待下个月末新信号。没有在途人工订单时CANCELLED并释放剩余计划资源；有在途订单则WAITING_MANUAL_CONFIRMATION，只保留实际未成交人工订单占用，已成交期权担保继续由账本保留，确认结束后关闭剩余意图。保留部分成交数量/关联事件，不伪造撤单、平仓或全量成交。相同冻结信号改张数/风险造成新intent_id也不能重新激活以投入新资金。

资金冲销只更正账务，不自动重启旧月度意图；关闭依据保留原始资金事件，历史时点/ledger_seq过滤保证不倒灌。人工审计新增expected_sequence过滤，后来的结束通知不会消除旧账本版本的占用。看板文案区分草案/合成READY/保存记录与当前时点审阅，无新增页面写入。

测试首批13通过/1失败、53.88秒（capital-close-check.log）：新测试冲销时点不同于原资金事件，违反既有更正契约；已使用同生效时点、不同记录序号补充凭据，未改账本契约。最终15项无跳过通过、136.27秒（capital-close-final-check.log），覆盖激活/人工/部分成交/资金关闭/冲销/同信号换张数阻断/历史序号，以及成熟引擎模拟、结算和完整恢复。

7条CLI实际通过：激活→资金预检→提交→重复预检/提交→当前/历史审阅。证据reports/v19-implementation/capital-close-cli-d40e0366685b4c1bb539319da1845750/verification.json。原22000入金后新增100，权益/净投入均22100、投资盈亏0；当前CANCELLED/预留0，变动前READY不被后来关闭覆盖；重复导入仍2个资金事件。只写独立合成demo，无券商订单和用户原账户修改。

尚未完整验收v1.9：其他A8模板生命周期/激活、完整平仓/指派/到期模拟及日常任务链路、真实来源/券商/自然前向和P5/O6最终全量/安装/浏览器/交付仍待。下一动作：补其他模板缺少的官方到期/行权分支，再扩展资源资格及模拟生命周期，保持原范围。Goal active。

## 当前批次：成熟引擎收盘成交→CSP演示账本（2026-10-11）

新增simulation.py和plan-simulate --file/--commit。仅demo已激活CSP，以工作区schema2 monthly-compare归档中的实际LEAN MarketOnClose事件为输入，不自行撮合。重新检查激活资格/当前对账/人工订单、完整报告哈希/逐日净值、当前适配源码/程序集/输入、冻结信号、精确合约和收盘时点/已到达执行报价/方向/数量/费用/偏离；只导入该信号OPEN批次，后续月份及平仓不进入账户。每计划稳定任务ID，重复请求无新增，换输入冲突；事件和审计原子写入，资源异常回滚。收盘报价数量检查已加，最终全量仍需验证全部边界。

固定手算一张95行权价CSP：原现金22000，成交卖价1/费用2，应收98；负债按1.05×100估值，权益21993、实际担保9500、可用现金12500。工程T+1结算后现金22098、应收0、权益不变。首测结算断言失败（simulation-check.log，85.98秒）：测试误将夏令时结束后的11月4日收盘写为20:00UTC；日历实际为21:00UTC。已补20:01仍应收、21:01转现金的独立检查，没有改为固定UTC结算。

20项模拟/计划/人工/备份回归通过、无跳过，100.21秒（simulation-final-check.log）；覆盖提前处理/缺收盘报价/价格偏离无写入、成交数量与费用/担保转换、幂等冲突、T+1及完整备份恢复。最新4条CLI通过（激活/模拟/重复模拟/审阅），证据reports/v19-implementation/simulation-cli-36f10e2fa77243c58596b23bb5d35042/verification.json；仅1笔测试入金与1笔合成成交，原用户账户未写，无券商订单。新模拟审计归独立期权链及报告引用校验，不误归ETF快照；说明见V19-USAGE末节。

当前只是历史合成归档驱动的独立入口，delayed_processing不代表实际前向任务运行。月度引擎固定每腿1张，不能缩放其成交以填满更大的计划。仍需完整日常模拟/平仓/生命周期/对账报告闭环、其他模板资格和最终P5/O6；真实数据与自然前向独立受限。下一动作：连接后续生命周期/计划任务，完善外部资金变动关闭规则并继续A8缺失分支。Goal active，不以单CSP入口缩小范围。

## 当前批次：CSP演示激活、部分成交资源和完整恢复（2026-10-11）

新增activation.py与plan-activate --file/--commit：仅demo合成历史CSP，核验冻结月度选约、下一交易日收盘期限/提前20分钟提交窗口、已到达当前报价、分模板引擎资格、账本序号、资金及对账。READY预留和幂等审计在同一事务建立，引擎证据校验后原子归档。paper/real始终保留来源、权限及前向门禁；其他模板目前TEMPLATE_ACTIVATION_NOT_VALIDATED。

独立手算两张95行权价CSP：激活预留19014、可用2986；一张关联成交后剩余预算9512与实际担保9500合计19012，可用3086；全成交后仅实际担保19000。历史时点及ledger_seq查询不倒灌未来预留。未关联账户变化、对账差异、待核实期权凭据阻断执行；过期无在途订单释放未执行部分，在途占用须确认结束。同一意图已READY/PARTIAL/FILLED时，新修订不能再次激活。

验证：早期12项47.82秒、状态修复后15项49.01秒通过（activation-state-check.log）。备份初测5通过/1失败（activation-backup-check.log）：嵌入月度期权链被误归ETF快照；已修复分类，独立核验冻结信号及链引用。最终25项无跳过全部通过、69.17秒（activation-final-regression.log），覆盖激活/部分成交/在途订单/外部入金/对账/完整恢复，以及重算外层备份清单仍拒绝修改程序集。失败日志保留。

最新源码3条CLI通过：激活、同请求重跑、只读审阅。证据reports/v19-implementation/activation-cli-cf4fc2a09a4942aba78641c929224f29/verification.json；仅1笔测试入金和1份激活审计，无重复事件/预留、无券商订单、无用户原账户写入。操作见docs/V19-USAGE.md末节。

未完成：模拟执行任务/日常链路、其他A8模板缺失生命周期及激活、外部资金变化后的意图关闭完整规则、最终统一源码全量/清洁安装/实际浏览器/CLI及P5/O6。当前executable仅表示合成demo局部激活检查通过，不授予自动执行或真实交易权限。下一动作：以成熟引擎成交证据驱动原子模拟批次，贯通计划→事件→对账→报告；继续其他生命周期，不以CSP缩小Goal。Goal active。

## 当前批次：CSP到期与逐模板生命周期审计（2026-10-11）

成熟引擎现16例：新增现金担保Put无价值到期。官方OptionExercise到期事件映射SHORT义务清除，不重复入权利金、不记虚构卖出；初始100000、权利金100、费用2，现金/权益100098，证券/期权/担保0。1项完整引擎回归覆盖16例通过（csp-expiry-check.log，48.45秒）；新增资格/篡改检查后1项回归再次通过（csp-qualified-check.log，47.07秒）。

新增qualification.py与engine-assess：分模板必需案例矩阵、规则版本/源码hash，核验当前C#源码/固定LEAN SDK/程序集、输入/执行数据hash、实际引擎终态和生命周期账本。CSP开平仓/指派/到期3分支通过；备兑Call因未验证无价值到期仍BLOCKED；修改账本桥接会阻断。PASSED仅合成引擎生命周期单项，executable/source_qualified始终false，不自动开放READY。

长期4条CLI已通过，csp-qualification-cli.log及reports/v19-implementation/csp-qualified-cli-864b40f3503c4586b0e6f6cd03500ce2/verification.json；包含导链/16例回放/CSP通过及covered-call预期阻断审计，未创建用户账户DB，尚未做最新全项目验收。下一项接CSP工程资格到月度信号/当前报价/账户及资源事务，形成受门禁的模拟计划；继续其他模板缺失生命周期分支。真实来源/券商/自然前向独立待输入，Goal active。

## 当前批次：未成交资源预算与审阅预览（2026-10-11）

新增unfilled_resources，按明确关联的有效成交数量计算剩余买入权利金/费用、Put完整履约现金、Call覆盖股票及价差长腿完整行权资金。不预支卖出权利金；现金缓冲/指派额外预留在仍有未成交腿时保留，全部完成后只由实际持仓担保接管。collar的已成交短Call覆盖股票不再被剩余保护Put重复占用。

独立预期：2张CSP计划预算19014→1张未成交9512→全部成交0（实际9500/19000担保由账本另计）；牛Call价差10224→长腿完成后10012→全部完成0（实际价差完整行权现金由账本另计）。plan-review新增reservation_preview/applied=false，未改变账户预留/执行资格。10项草案/部分成交/冲销/人工订单回归通过（resource-preview-check.log，2.65秒）。首次仅金额字符串尾零断言失败，已按Decimal金额核对，未改变现金预期。

实际CLI在历史合成工作区的独立副本逐个审阅现有期权计划，预览不可执行，事件数量前后不变：reports/v19-implementation/resource-review-cli-3350eaee7b5d4b5cab5362e14d08d1e3/verification.json。未改原账户或旧证据。

READY仍未开放：预算预览不能替代分模板成熟生命周期、来源资格、冻结月度信号/新鲜执行报价、对账和账户权限门禁，也不是实际预留。下一项实现带资格审计的激活/资源事务，接部分成交和模拟任务；继续最终源码验收，Goal active。

## 当前批次：同条件月度比较、逐日净值及报告看板（2026-10-11）

新增monthly-compare CLI与月度比较报告：同LEAN/源码/数据哈希/资本/区间/费用配置运行模板、100股股票控制组及现金控制组。ffn复用累计/年化/回撤/波动率；实际引擎事件计算佣金、价差解释成本、批次换手/买卖金额。示例两期collar终值99936（期权佣金16+股票佣金8+价差40），股票99992，现金100000；初始资金基线、短样本年化、T+1保护空档和控制组并非全仓股票均标注。

修复两项验证发现：ZIP写入时刻导致相同执行内容hash不同，已固定ZIP元数据；LEAN午夜日蜡烛收盘值属于前一天，原日期截取漏掉首日费用。现逐日将引擎收盘与独立统一账本核对，首日collar99984/股票99998/现金100000。旧schema1报告在读取时拒绝；保留首个CLI退出0事实，但acceptance-review.json明确撤销其验收资格，不称旧结果正确。

修正收益日期后6项月度/备份/恢复/Streamlit组件回归通过（monthly-report-fixed-check.log，53.30秒）；随后schema2旧报告拒绝与收益基线2项通过（monthly-report-schema-check.log，7.21秒）。最新实际CLI schema2报告通过逐日/整体哈希核验且未创建用户账户DB：reports/v19-implementation/monthly-compare-cli-bddfba23081d4314a39c07c227cd47c8/verification.json。隔离schema2完整恢复及Streamlit组件验证通过（monthly-schema2-recovery-ui.log和对应schema2-recovery-ui-verification.json）；刷新前后账户/事件/计划/任务均0且不变。组件检查不等于实际浏览器最终验收。

研究页新增月度曲线、回撤、指标/费用/换手和交易明细，读取前验证归档文件及引擎/账本逐日一致性，刷新不运行引擎/导入事实。工作区options/monthly-research下报告纳入备份引用校验；合成/历史重建标签保持。追加输入边界6项回归通过（monthly-boundary-check.log，16.97秒），当前读取器再次核验schema2归档通过。完整P5/O6全量验收、真实历史/前向来源、READY/执行计划仍待。下一动作：接月度计划/模拟任务的资格及资源闭环，按最终源码验收。Goal active。

## 当前批次：连续月度LEAN组合与统一账本（2026-10-11）

新增LyraXMonthly外部算法及monthly_replay.py/CLI monthly-replay。多个月度冻结信号在同一个引擎组合运行，资本不重置；旧组合在次月首个适用收盘平仓，新组合按工程T+1等待至下一交易日收盘开仓。使用官方MOC、实际日历及提前收盘；事件导出到期日/类型/行权价/冻结信号标识，避免同一行权价不同到期合约误配。所有编译C#文件纳入源码归档/hash。

统一隔离demo账本导入成熟引擎事件，按T+1区分现金与应收应付，重复导入新增0；逐批次重放资产/担保/估值并核验最终结算现金。两月collar权益路径99986→99972→99958→99944，与每期2腿各10价差+4费用手算一致，无期权/股票残余。1项引擎/账本回归通过14.35秒；实际CLI及长期报告成功：reports/v19-implementation/monthly-replay-cli-64fd9b4663aa4ae58c73f1aa067b296b/verification.json，未创建/修改用户工作区账户。

首次构建因DOTNET_CLI_HOME未显式设置被只读路径拒绝，改用隔离/tmp前缀；编译Symbol与QCAlgorithm方法重名后已限定类型；样例跨到期ID重复后已修复。未修改第三方源码。八模板相关回归通过（monthly-a8-check.log，8 passed/77.99秒）。随后补加合成固定100标的/每腿1张及相同合约跨月报价变化拒绝，并校验选约内部decision_hash，不能重算外层哈希掩盖腿修改；最新5项月度/备份/两月collar回归通过（monthly-final-check.log，15.94秒），最终全量仍需按统一源码执行。

此入口仅合成机械月度验证；固定执行价格不代表真实历史收益或来源资格。真实期权、自然前向、READY/计划状态与公平月度基准、完整报告/看板最终验收仍待。下一项扩展A8和控制组同条件归档，接月度计划/模拟任务及报告，不解除真实来源或券商权限门禁。Goal active。

## 当前批次：月度归档备份与收盘成交约束（2026-10-11）

月度冻结信号已纳入备份引用检查：身份/内容/输入哈希及选约快照关联需一致，缺失报价链阻断；完整bundle恢复后冻结信号原样一致。CLI月度发布取得工作区共享锁，再取得归档锁，与备份锁顺序保持一致。17项月度/备份回归通过（19.90秒），证据monthly-backup-check.log。

正在验证LEAN收盘成交适配。第一次15:46提交被官方默认15分30秒门槛拒绝，保留失败日志close-engine-check.log；已改为按实际收盘提前20分钟提交，未修改官方门槛或第三方源码。重跑10个A8/基准场景通过，长期报告reports/v19-implementation/close-engine-71dad00041fd49a69599328f5bab4751/engine/verification.json。随后将收盘报价与提交价区分（+0.2），新增实际成交价/订单数量/时点回归通过（close-price-check.log，1 passed/33.48秒，覆盖10例）。最终2条CLI成功，10例完成且全部550次数据文件哈希核对通过，未创建用户账户DB。证据reports/v19-implementation/close-cli-034b3af77c854fabaf032e4c1380a4b5/verification.json及close-cli-check.log。

下一项检查收盘事件与现金独立预期，再连接多月冻结信号及共享模拟账本。月度备份功能已补齐，实际跨月执行/READY与最终验收仍待；Goal active。

## 最新批次：月度研究信号冻结（2026-10-11）

新增options/monthly.py及CLI monthly-freeze。只在交易日历确认的月末、实际收盘加显式发布延迟时生成；冻结下一交易日及其收盘时点、输入/日历/源码哈希、选约及内容哈希。独立scope按月份/模板/标的稳定标识，发布锁和原子文件防止重跑重复；输入变化或文件篡改明确拒绝。不足数据返回BLOCKED且不发布信号，非月末NO_ACTION。所有输出仍为历史重建研究信号，executable=false，不建立账户或READY。

验证：monthly-freeze-check.log，3项回归覆盖重复/冲突、提前收盘、截断日历、缺数据和冻结篡改。实际3条CLI完成导链、月末冻结、相同任务重跑，结果一致且未创建账户DB：reports/v19-implementation/monthly-cli-9d87822e8467459d94020ea869ba56f8/verification.json。

尚未完成：月度归档纳入统一备份/恢复、真实前向生成、LEAN次日收盘执行验证、跨月持仓及计划/对账/报告贯通。此模块不代表月度策略回测已经完成。下一项核验成熟引擎收盘订单约束并实现多周期回放，再接月度模拟任务。Goal active。

## 最新批次：牛市Call价差部分指派及隔夜恢复（2026-10-11）

LEAN合成生命周期现覆盖15例。新增短Call被官方模型指派后产生100股临时空头；保留长Call及完整行权资金，等待下一交易日开市取得报价再行权恢复。统一账本按事件序号重放：指派时现金110386、股票−100且异常阻断；次日恢复后现金/权益100386，股票和期权归零，异常解除。中间缺少期权估值时权益保持不完整，不引用未来报价。

证据：reports/v19-implementation/spread-path-check.log（2项引擎回归通过，覆盖15例）；测试报告目录/tmp/lyrax-spread-path/中的engine/各场景含冻结输入、引擎事件、隔离账本及ledger-lifecycle-path.json。临时测试目录不作为长期交付报告，下一批归档CLI证据。旧14例CLI与旧全量验收分别保留，未把本轮两项回归称为最终全量。

下一动作：归档15例CLI证据，贯通月度冻结信号→引擎→模拟账本→计划/对账/报告与READY资格，再按最终源码验收。真实期权/券商/自然前向条件独立待输入，Goal active。

## 最新批次：CSP指派、无价值到期及执行数据冻结

LEAN生命周期扩展现共14例：A8、股票/现金基准、保护Put行权、备兑Call指派、CSP指派和Long Put无价值到期。CSP保留交割后100股，现金90598/股票8500/权益99098与手算一致；无价值到期现金99788且合约归零，不记一笔虚构卖出。2项引擎回归覆盖全部14例并核验所有执行数据哈希；实际CLI --include-exercise完成14例，未建立/修改用户工作区账户。

修复可复现性缺陷：生命周期价格冲击不再修改共享行情；每例从基线复制独立执行数据、保存data-files.json及哈希。A8与基准维持相同区间，生命周期诊断单列结束时点。最终CLI再次逐文件核验通过。

证据：reports/v19-implementation/lifecycle-14-cli-851ffe5a61ea465cb3bfbfe798cbad2e/verification.json，engine各场景数据清单/输入/引擎事件/隔离账本；lifecycle-14-check.log（2 passed，40.49秒）。此前12/13场景为历史批次，不代表最新全链路。尚未做最新全项目最终验收。

下一动作：贯通月度冻结信号、引擎事件→模拟账本→计划/对账/报告任务；验证多腿部分指派与现金/保护释放路径，再实现READY资格。真实数据/券商/自然前向条件仍待输入，不宣称v1.9完成。Goal active。

## 最新批次：LEAN行权/指派与事件账本桥接

外部适配导出实际引擎事件，新增保护Put价内行权和备兑Call官方模型指派。全部12例（A8+股票/现金+2生命周期）运行完成，行权/交割事件导入报告内隔离demo账本，手算现金99388/100598一致，期权和股票均归零；未写用户工作区账户。2项引擎回归通过（包含全部12例），实际CLI导链/fixture-replay --include-exercise成功。

证据：reports/v19-implementation/lifecycle-engine-cli-2516cd614ef949518c1ca5a4cc9d8bdb/verification.json、engine各案例engine-events.json/ledger-bridge.json，以及exercise-check.log。源码/程序集/引擎版本与输入已归档。编译曾因ExerciseOption要求整型数量失败，已显式整张校验；费用回归曾发现成交FeeModel重复套于行权和交割，已将样例行权/交割费显式设为0并按独立预期重跑。未隐藏旧失败，不把费用假设当成券商费率。

指派使用官方DefaultOptionAssignmentModel的显式10日工程参数及官方价内/套利判断；不代表真实概率。尚未验证CSP指派、无价值到期、分红/多腿部分指派、非零行权费用和月度调度。不能因这两分支通过解除READY。最终全量源码验收仍待；下节各批次测试与CLI分别保留。

下一动作：验证CSP指派和无价值到期，扩展生命周期导出/对账，再接月度冻结计划/模拟闭环及READY资格。Goal active，真实期权来源/账户条件独立受阻。

## 最新批次：人工在途订单与预留转换（进行中）

新增manual-record：已提交订单记录、确认无剩余订单、本地取消；稳定请求ID/账户序号/原因、重复幂等及冲突检查。部分成交只转换已完成数量的预留，取消不能释放尚未确认结束的在途订单；FILLED事实不可取消。买Put/Call按未成交参考金额及费用预留，卖Put全额履约现金、卖Call保守覆盖证券；不预支卖出权利金或未来保护腿。历史审计重建预留，不以当前关闭状态抹去过去占用。

49项相关回归通过。随后完整315项测试通过（212.41秒），但CLI发现备份将人工审计里的期权快照当作ETF引用而失败；该日志按失败批次保留，不宣称该批CLI通过。修复引用分类并核验审计哈希后，14项人工/备份回归、2项人工预留及已有ETF检查失效回归通过；最新源码52条CLI全部通过，包含完整备份/恢复。未用修复前315项宣称最新源码全量已复核。

证据：reports/v19-implementation/manual-milestone.json及manual-cli-final.log；CLI reports/v19-validation/bb246e3231d848d7818dabd3d9b0a6f8/verification.json。新增人工占用变化会使已有ETF计划检查BLOCKED，但不改变其执行事实或释放在途占用。期权READY及成熟引擎月度生命周期仍未完成，真实来源/权限条件继续独立标注。

下一动作：继续成熟引擎行权/指派事件导出与月度生命周期验证，再贯通READY资格和模拟任务；最终按源码重新全量验收。Goal active。

## 最新工作：期权事实关联和待核实凭据解决（进行中）

新增`options/lifecycle.py`：明确同账户期权plan_id、按有效事件重建PARTIAL/FILLED/冲销状态、超额/方向/合约偏离保留并阻断后续建议。账户统一读取ETF/期权计划预留；公共草案仍不建立预留，不把内部预算测试称为READY闭环。

新增CLI：plan-review（指定时点只读计算）、pending-list、resolve-pending（原凭据哈希/账户序号、原样重试、原文/原因/结果审计、重复解决幂等）。不支持的公司行动或内容更正不能通过重试强制入账。界面展示解决审计及实际进度。

最新源码8b564edf…：48项相关回归、完整314项测试无跳过（214.85秒）、49条隔离CLI全部通过。新增原凭据解决/重复解决及明确关联成交FILLED链路，早期样例现金598/SPY4/权益998不变。真实ETF固定快照按同源码研究通过，账户/成交/计划仍0；实际Chromium四页、解决审计可见、保护Put700及刷新只读通过，服务器日志无异常。

证据：reports/v19-implementation/lifecycle-milestone.json、lifecycle-local-check.log、lifecycle-browser/verification.json；CLI reports/v19-validation/590ad039311943c69877701645e4c7d2/verification.json。此前为修复两处历史时点边界主动中断运行，未计为通过；旧310/34对应下节bb88基线。

下一动作：继续READY预留转换/在途人工执行和成熟引擎月度生命周期闭环。Goal保持active，无自动交易。

## 当前实施：v1.9 核心工程进行中（不是最终交付）

版本1.9.0.dev0，独立Conda `.conda/v19-clean`，基础显式锁、77包wheel锁及QuantLib1.43哈希锁；pip check通过。v1.8源码1437f4c6…保留；GOAL未改；实际研究工作区未迁移、未写入账户事实。

已实现：

- P0/P1：连续交易日就绪、策略回看、同任务重试恢复、显式报告检查；备份空间/清单/保护保留/验证后清理/隔离恢复及本地检查脚本。
- P2/P3：声明式账单映射、预检哈希与账户序号、重复导入防护、来源资格归档/到期门禁；四页中文待办、显式迁移、映射导入、期权持仓与草案、隔离组合摘要。界面刷新不写账。
- P4：资产/成本归因、63/126/252共同窗口比较、复用现有策略的双动量预设；多个独立模拟工作区只读汇总，不合并资金或账本。
- O0/O1：固定LEAN提交80e7843…、隔离.NET10.0.100及外部算法适配；不可变合约/链CSV、单位/PIT/价差/最小跳动检查。官方样本仅引擎冒烟，不能证明LyraX策略。
- O2：14类目录、A组8个同到期情景；QuantLib美式/欧式、Greeks/IV、离散现金分红定价、跨期理论压力。离散分红IV明确未支持；跨期压力尚未集成离散分红。
- O3：v5备份迁移、统一现金/ETF/期权事件账本、负债/担保/覆盖/行权/指派/到期/现金结算及待核实凭据；Call价差长腿只可保护一次，并预留完整行权现金，不重复扣权益。
- O4局部：A8冻结选约、未来OI/成交价屏蔽、规则版本/源码指纹、研究草案；LEAN合成机械回放8策略加股票/现金基准完成开平仓与现金桥接。只支持合成标准100股美式实物合约，不能冒充真实历史/月度策略/提前指派验收。

验证证据（对应源码版本分别保留）：

- 最新源码bb88bc8f…：完整310项测试无跳过（217.45秒）、34条隔离CLI，accepted-local-check.log及reports/v19-validation/2e66eb6e03aa458db005e34607e68eba/verification.json；手算现金598/SPY4/权益998。
- 实际Yahoo ETF下载到2026-10-09，2838行，快照33bc3418…；同一真实快照的bb88源码扣费研究成功，accounts/events/plans均0。证据reports/v19-implementation/online-28e19f5978b9457db3cb3287e22cb707/current-source-verification.json。
- 实际Chromium四页、保护Put最大损失700、刷新只读通过（关闭统计后服务器日志无异常），reports/v19-implementation/browser/verification.json；全部使用隔离合成账户。
- 新发现并修复：真实工作区不能用测试合约条款代替实际单位凭据。登记/导入要求SHA256匹配的归档文件；凭据缺失或改变使权益不完整并阻断备份。22项账本/备份相关回归及最新310项完整测试通过，34条CLI通过；accepted-milestone.json记录本次统一源码证据。

未完成：期权READY计划预留转换及手工执行状态、待核实凭据内容更正/不支持行动处理、A8月度模拟/生命周期闭环（明确部分成交关联及原凭据重试已在顶部新增批次验证）、实际行情适配资格、条件B组及P5/O6最终验收。真实期权授权、券商权限/脱敏账单/账户参数、自然前向周期是独立外部条件；不存在自动下单。上游LEAN审计警告保留，隔离研究，不携带账户密钥。模型/API用量及费用未获取。

下一动作：推进统一计划状态与资源闭环；不得把DRAFT无预留草案标为可执行。操作入口见[V19-USAGE](V19-USAGE.md)。

## 之前的期权调研与规划（实施前历史）

用户要求调研期权策略并纳入v1.9。已核对OIC/OCC、Cboe、CME、券商教育/数据说明、QuantLib和LEAN官方资料，形成[14类策略目录](V19-OPTIONS-RESEARCH.md)及[O0–O6实施计划](V19-OPTIONS-PLAN.md)，并更新[主计划](lyraX-v1.9.md)、agents、README和DECISIONS。单腿、覆盖/保护、价差、跨式、日历/对角、蝶/鹰、比例、合成/套利、动态/波动率及产品边界均有目录；A组8模板首批闭环，B组条件扩展，C/D不冒充可执行。

明确了合约/链/行动/Greeks数据、原始单位、PIT、担保、卖出权利金负债、提前指派、实物交割、多腿部分成交、统一ETF/期权计划及现金桥接。bt保留ETF研究；期权混合组合先验证LEAN，QuantLib评估理论定价，不自行重写引擎。官方CLI商业条件与引擎许可、历史数据权限分别处理，没有自动购买或安装。

本轮仅文档。代码/配置/测试/锁/GOAL保持，实际版本1.8.0；没有接入真实期权历史、确认账户权限、运行新回测或写账。使用Jina读取成功；agent-reach/mcporter/gh命令未安装，体检/更新检查无法运行，以现有网页能力完成资料核对。没有统计到模型分项/API费用。

验证：PASS_V19_OPTIONS_PLAN_REVIEW；7份文档、68个本地链接、14类目录/8个首批模板及5个独立资金手算例检查通过，124个业务/配置/测试/锁/样本/GOAL等基线文件未变。证据reports/v19-options-planning/verification.json、baseline.json和references.json。网页引用目录不等于实际数据接入证据；本轮未运行应用pytest或期权引擎。

待输入：具体市场及产品（暂沿用美股ETF）、券商期权权限、实际报价/合约历史授权、费用/交割/风险参数及脱敏账单。尚未实施：原P0–P5、期权O0–O6、F/OF实际观察。下一步在用户要求开发后先固化R01/R02失败回归和v1.8基线，同时执行O0成熟引擎与期权契约验证；资料不足时先推进目录/情景工具，不声称历史或前向完成。

## 之前的v1.9基础规划（R0历史，尚未实施）

用户要求把复核建议纳入版本计划，已写入[lyraX-v1.9.md](lyraX-v1.9.md)。P0–P5覆盖诊断修复、工程维护、来源资格/账单映射、前向模拟、中文待办、归因/滚动/双动量及隔离组合；F单独验收实际接入和月末观察。当前代码仍为1.8.0，上一轮隔离复现的R01历史缺口诊断、R02成功重跑后旧告警尚未修复，257项仍属v1.8覆盖证据。

本轮只调整计划及入口：主计划、agents、README、PROGRESS、DECISIONS；纠正历史D01/D02仍写成最新未修复及README旧标题。没有修改业务、配置、测试、依赖锁、样本或GOAL，也未更新软件版本、迁移数据库、安装服务、提交Git或写入账户。

验证：Conda Python执行文档链接、范围/状态和SHA256检查，结果PASS_V19_PLAN_REVIEW；5份文档、50个本地链接通过，124个业务/配置/测试/锁/样本/GOAL等基线文件未变，软件版本1.8.0。证据为reports/v19-planning/baseline.json和verification.json。本轮没有运行应用pytest，未把v1.8测试结果记为v1.9验收。

未完成：P0–P5均未开始；真实原价/公司行动、券商脱敏账单/独立快照及账户参数待提供，实际前向观察待启动。下一具体动作：用户要求实施后，先归档v1.8基线，将R01/R02临时复现写为正式失败回归，再修共享就绪检查及任务恢复提醒。资料等待不阻塞独立工程任务。

## 已交付基线：LyraX v1.8核心工程交付完成

P0–P5已完成：D01/D02、四用途、共享发布锁、v4备份迁移/回滚、源码研究包、验证套件/协议/恢复、年度切片、执行复盘、doctor/本地待办和四页集成。最终源码1437f4c6…；Conda新环境1.8.0安装及pip check通过；257测试无跳过、新34/旧32CLI通过；真实行情增量下载及4子实验成功；浏览器四页/操作/刷新检查通过。最终证据reports/v18-implementation/accepted-*及browser/，交付[V18-DELIVERY](V18-DELIVERY.md)，用法[V18-USAGE](V18-USAGE.md)。

实际工作区reports/manual-online已完整备份并升级v4，只绑定signal；账户/事件/计划仍0。Yahoo原价单位未核验，因此execution/valuation未分配，doctor明确BLOCKED；真实基本面/券商凭据/长期前向未获取；调度模板未安装；V2未启动。下一具体动作：使用者可复现演示和研究；实际使用前提供原价/公司行动及账户配置/账单，再单独验收。没有剩余核心编码任务。

本轮失败均保留开发日志：D02正式失败回归、SQL占位符、测试导入/冲销时点、因子用途拒绝及研究还原错误已修复；默认Conda渠道ToS失败用官方conda-forge显式锁绕开未使用渠道，浏览器依赖用既有本地库；最终检查通过。模型token、套餐额度和API费用未获取，未购买服务。

## 之前的v1.8规划（历史记录）

用户要求检查项目改进及扩展，并制定v1.8计划。已按现有源码与审计写入[主计划](lyraX-v1.8.md)：必修D01/D02、数据系列/用途与并发发布、源码及研究包还原、分段/成本验证与预先登记协议、执行复盘/导出、doctor/本地待办、迁移和四页集成。P0–P5全部待实施；实际版本1.5.0，原231项仍为v1.5证据。

本轮仅读取源码、已有验收与Git状态，修改文档。D01的修复范围覆盖daily之外的plan/revise、模拟、估值及对账入口；分段窗口与费用情景的比较口径、发布锁顺序、v3→v4兼容和归档源码资格均已明确。可选策略、账单映射、真实因子来源、影子组合、通知和券商接入独立列条件，不扩大核心交付。

验证记录：reports/v18-planning/baseline.json、verification.json。下一具体动作：用户要求实施后，先建立D01/D02失败回归及最小双来源daily链路，再按P0/P1推进。当前无新代码、数据库迁移、调度安装或真实交易。

## 历史复核：曾发现两项设计缺口

2026-10-10源码复核及隔离样例确认：D01日常任务未贯通独立信号/执行价格；D02并发因子合并可丢失latest中的一批更新。尚未修复，原231项验收为既有覆盖基线；复核见[V15设计审计](V15-DESIGN-AUDIT.md)，证据reports/v15-validation/design-audit-20261010.json。下一具体动作：先补两个场景回归，再修数据用途选择及发布锁。实际账本未修改。

## 历史交付：lyraX v1.5 工程验收完成

P0–P5已完成。六模板、不可变规格/共享解码、多策略bt、PIT因子、attempt/发布恢复、未来月末绑定/NO_ACTION、daily绑定篮子和四页工作台、草稿/预检/差异/原价导入、v3备份恢复已交付。真实基本面与实际账户资料单独保持受阻，未冒充完成真实数据资格。详见[V1.5交付](V15-DELIVERY.md)和[操作说明](V15-USAGE.md)。

- 新清洁Conda `.conda/v15-clean`按26包基础锁/77包wheel SHA256锁安装项目1.5.0；pip check通过。
- 最终全量：231 passed、0 skipped，88.51s，reports/v15-validation/clean-final-pytest.log。
- 新完整流程41条CLI通过；合成六策略复现、后台合成因子研究明确mixed_test_factors、入金10000/结算现金630.0637177095350、计划/成交幂等及v3因子/实验/绑定备份恢复通过。证据reports/v15-validation/91b39254ed444ff19bf34273c832e535/verification.json；真实ETF六策略两次一致，run_id ed43907b77f24739a30d2833e92a15c9。
- 较早v1.5源码830511334e9b6551e4696b56c46d5cd7172c0ecd100de60742ea5e934cc0811d的旧32条离线CLI通过，独立现金503.5/持仓10/权益998.5、生命周期9事件及daily/恢复均正确；reports/offline-validation/f6bca4d39a2f49a5ad25092f68c56761/verification.json。
- 最终旧fixed/trend全部数值CSV和指标与开发前真实快照基线一致；reports/v15-validation/final-legacy.json。
- 实际研究目录备份后v2→v3，六策略run_id b4246c0f40f74d01bf204e527e0253d6；原始完整备份reports/manual-online/reports/v15-migrations/60e5d8e505b14868974bad64405c24f8。
- 实际Chromium编辑/草稿/预检/冻结、后台提交与成功报告、重复提交/刷新、四页切换通过；reports/v15-validation/browser/verification.json，run_id 9df4049ade874fb286f613d6fe20963a。实际目录7个策略版本、6个研究attempt，账户/事件/计划/信号/绑定均0。
- 最终源码770fa17584ce2ecf9d0da3728e8e7052c2b5cc3d12cf81928f9dda7be123a8c1；最终回归、新41条CLI、旧数值兼容及浏览器证据对应此源码；旧32条CLI保留为较早源码的兼容证据。GOAL原样，未提交Git。模型/API实际费用及分项用量未获取。

已修复实际发现的问题：因子使用收盘后发布时间；新信号/配置冻结重放；报告清单与发布断点；受阻绑定不顺延；daily用绑定篮子；备份排除provider-cache并区分因子。Conda默认频道ToS阻断通过明确conda-forge锁/缓存解决，未接受其他频道条款。旧服务缓存V1模块导致导入失败，停止并重启解决，升级重启约定已写文档。

看板保留运行：http://localhost:8501/?view=research，句柄49344；恢复需实查服务状态。暂无运行中的研究任务、真实资金或自动下单。后续仅需用户查看；真实跟踪需原价/行动来源及账户费用/单位/结算/风险/账单，真实价值/质量需PIT因子资格。V2需券商/API条件及单独开发请求，不继续扩展本次范围。

## 上次追加：lyraX v1.5 R1复核

[主计划](lyraX-v1.5.md)已修订，[复核记录](lyraX-v1.5-REVIEW.md)列出12项设计缺口和8个端到端验证场景。重点补齐多版本身份、两种价格用途、因子时点、缺失状态、月末版本切换、任务幂等及发布/备份恢复。设计约定已补齐，运行验证待实施；没有修改业务代码。

本轮实际检查：PASS_R1_DESIGN_REVIEW；6份文档、34个本地链接、12项复核覆盖及独立权重算术通过，77个业务/配置/测试/锁/GOAL基线文件哈希未变。

用户已追加要求完成v1.5实施。复核结束后开始P0契约/兼容及临时库迁移；后续按P0–P5验收。真实基本面/原价等外部资格仍需实际来源证据。

## 上次追加：lyraX v1.5 规划

[计划文档](lyraX-v1.5.md)已编写，状态为设计完成、尚未实施。覆盖六类只做多策略、模板/版本管理、中文编辑与回测比较、多因子CSV及时间检查、现有账户跟踪接入。真实基本面资格单独验收；套利/市场中性明确列后续条件。

本轮仅文档，实际读取源码接口；文档检查PASS_DOCUMENT_REVIEW：5份文档、18个本地链接通过，77个基线文件哈希未变。没有运行新策略、修改业务代码或迁移数据库。P0–P5均为待办，不能引用V1的180项测试宣称v1.5通过。下一项是收到实施要求后执行P0契约与兼容验证；本轮规划交付完成。

## 上次追加：系统名称 LyraX

界面、CLI帮助、当前文档及新报告已更新名称。3项UI回归通过，实际浏览器标题/页面/刷新通过；新研究run_id f48e6d855a7b4e5384593f4a0aa16d25，净值、交易、决策和指标与更名前相同，旧报告保留。证据reports/branding/20261009/verification.json。启动命令仍为lyra，Conda及存储ID保留。

## 上次追加：真实行情与研究看板

用户已要求执行一次更新。实际Yahoo价格2023-01-03至2026-10-08，SPY/IEF/GLD各945日、共2835行；覆盖及质量通过。评估期2024-07-01至2026-10-08，共571日，规则/费用不变，该批次run_id 04c6a6adb095476d960d2a16db34b6a0。

研究页默认最新报告及view=research入口，隐藏无关固定账户时钟。3项UI回归通过、实际浏览器验证两图/表/日期/最新报告与刷新；研究目录账户和事实均0。看板本轮保留运行：http://localhost:8501/?view=research（句柄17390，恢复需实查）。记录reports/live-research/20261009/verification.json与browser-verification.json。无自动调度或实际资金；下一项由用户查看，再决定纸面跟踪。

以下180项/旧1536行及源码指纹为V1交付时验收基线，保留历史证据；本轮仅UI显示改动做相关回归，没有声称重新跑全量。

## V1交付基线已完成

- Python3.11.15、独立Conda，第三清洁前缀按26包基础显式锁/77包wheel SHA256锁重装；pip check、激活及主库导入通过，无其他环境依赖。
- 在线Yahoo真实1536行、增量与供应商修订版本保留；bt双策略扣费回测、固定真实快照两次报告数值/指标/决策一致。
- CSV/缓存/日历/质量，126日趋势与固定策略，信号归档、月度计划、模拟跟踪，账本/公司行动/标准账单导入与独立对账；四页中文看板、Asia/Shanghai业务时间。
- 修复bt现金/全现金接口、首日费用/当日权益换手；demo资金独立配置、拒绝未来账户状态、差异阻断已有计划且保留资源；最终补零量成交资格及status递归日志问题。

## 最后验证命令与结果

- 第三清洁前缀 `python -m pytest -q`：**180 passed / 0 skipped，60.50s**；reports/environment/clean-20261009/pytest-final.log。
- `python scripts/verify_offline.py`：32CLI全退出0，根reports/offline-validation/e12c359d1422412f8b168597e126a571。现金503.5/SPY10/权益998.5、九节点现金350/IEF9/权益800、完整恢复后3事实不重复。
- `lyra research`两次真实快照：dd67d9d071a0471c891564fcf52f6a95 / 6a747b8f5fad42ef9974dcda202e4e9c；实际产物哈希与数值核对通过，reports/online-validation/20261009/verification.json。
- README安装/激活/help、demo/status、fetch/research/incremental、ui与daily/备份/校验/恢复均已执行。最终演示blocked_batches=0；当前备份恢复逻辑哈希/行数一致。
- Chromium四页切换/刷新、上传预检/提交/重复/立即更新、独立差异/解决和重启保持8测试事实；最终读页6计划/9归档不变。临时看板服务已停止。
- 源码指纹d1467f33e8d1f84f8c82e6275ec00bd82e1dbafe7ffe985421b0d50bb080cc8b。未提交Git；GOAL原样保留。

## 限制、历史失败及未覆盖

旧socket拒绝已解决。普通Conda YAML索引ReadTimeout，使用已成功显式锁安装；测试localhost代理502以NO_PROXY排除，不改系统网络。Yahoo价格不能直接算真实证券数量；分红支付/税费、真实账单和费用/单位/结算/风险需用户凭据。零量保守阻断，不能确认停牌。

没有实际券商原始账单映射、月末真实前向周期或长期cron记录；只提供调度示例、没有部署crontab或自动下单。Linux x86_64锁以外平台、复杂行动及多币种未验收。模型详细用量及API实际费用未获取。

## 下一项

V1既定验收已完成；v1.5工程完成，以本文件顶部交付记录为准。真实记录需用户提供费用、单位、结算、风险及账单；V2须明确券商/API权限与单独开发请求。

Goal工具完成时累计统计：tokensUsed=2,053,135，timeUsedSeconds=19,569（约5小时26分有效执行统计）。这是整个Goal的工具汇总，不是API账单；模型及输入/缓存/输出/推理分项、工具/API实际费用仍未获取。

2026-10-10最终只读核对：代码指纹、最终测试/41条CLI/浏览器/旧数值兼容一致；完整备份168个文件哈希全部匹配，看板健康检查HTTP200。汇总记录：`reports/v15-validation/final-verification.json`。旧32条CLI保留较早源码证据，未混称最终源码验收。

2026-10-10 v1.8规划检查：PASS_V18_PLAN_REVIEW；5份文档、44个本地链接通过，107个业务/配置/测试/锁/样本/GOAL文件未变。P0先保存匹配原运行的源码/锁基线，再实施数据修复；P0–P5未开始。证据reports/v18-planning/verification.json。


第三轮61相关回归全部通过，无跳过（3173.19秒，NTFS备份复制），hedge-option-late-regression-third-check.log；与11公开CLI一致2b2d96af指纹。全部句柄已终止。开始补组内期权CLOSE：execution_replay显式exit_id绑定原FROZEN退出及原阶段审计/序号/市场收盘，模拟显式state_as_of并核对风险确切退出ID。最新源码已变化，尚未验证CLOSE；v1.9及最终验收仍待。

期权CLOSE首轮1失败（54.65秒，hedge-option-close-late-check.log）：独立账单误把激活预留122当实际支付，写89878/中价1.15；原生真实样例开仓1.1*100+2，结算现金89888/中价1.05。对账正确记录差异并阻断组退出，未产生平仓事实。更正测试/CLI样例预期，业务门禁不改；第二轮完整往返进行中。

CLOSE第二轮完整组内迟到往返1项通过（72.42秒，hedge-option-close-late-second-check.log）；缺/错时钟拒绝、原生LEAN三组、冻结退出、审计注入回滚、重跑及完整备份恢复均通过。Demo SPY100不重复卖出，序号2→3→4，现金89986/权益99986；当前公开roundtrip CLI运行中，源码冻结。仍非最终全量，下一项原退出审计时点/前缀篡改独立检查及相关回归。

公开退出CLI首轮因缺少--expected-hash被PREVIEW_REQUIRED拒绝；脚本补公开预检后显式提交，业务不改。另在独立恢复账本中篡改原退出决定时间并重哈希，重放仍接受，hedge-option-close-clock-before-check.log保留。现补原review/阶段压力时点与财务前缀交叉核对，加入同场景负例。第三轮往返及第二轮CLI正在运行，两任务活跃，源码冻结；第二轮1项为新增审计约束前历史证据。

组内迟到往返第三轮1项通过（77.83秒，hedge-option-close-late-third-check.log），含原退出时间重哈希拒绝。公开20条CLI通过，bound-option-roundtrip-cli-20261012-second/verification.json；当前源码0ff8332989700ca5f26e94c26ca0e053ad4188abdd4a2ddbed587aa70ad80521，demo序号4、SPY100、现金89986/权益99986。未知退出、缺/错状态时钟拒绝，精确重跑不重复。当前仅退出/风险/阶段/daily相关回归活跃；为容量仅清理本轮已结束的前三次option-close测试临时目录，保留原A8源证据和所有日志，未清理正在运行目录。v1.9仍未完成。

0ff83329源码40相关回归无跳过通过（346.46秒，hedge-option-close-late-regression-check.log），涵盖8模板原生退出、风险、阶段及daily。之后补共享cached审计时点/金融前缀/确切退出ID校验，使重跑和备份也检查原操作，而不只在新风险入口检查；非字符串plan_kind改为结构化错误。当前cached-clock相关回归活跃，新源码尚待确认；40/20CLI作为之前指纹证据保留。清理仅该已结束40项测试的临时根以避免再次/tmp耗尽，保留本轮活跃根和原A8证据。

共享缓存门禁首轮1通过/1失败（68.40秒，hedge-option-close-cached-clock-check.log）：原退出时间篡改现在更早抛CORRUPT_HEDGE_STAGE_AUDIT，而预期仍写旧入口CORRUPT_OPTION_AUDIT；改对应预期，业务门禁未放宽。另加缓存审计处理时间/退出ID各自重哈希拒绝及非字符串请求5样例。当前仅cached-clock第二轮及roundtrip第三轮CLI活跃，源码冻结。

最新b6106a7f源码公开第三轮20CLI通过，bound-option-roundtrip-cli-20261012-third/verification.json；与13专项一致。仅最终相关回归活跃（hedge-option-close-late-final-regression-check.log）。原参数/时间/资源门禁未放宽，demo最终序号4、现金89986/权益99986/SPY100。v1.9未完成。

最新b6106a7f源码最终40相关回归无跳过通过（338.33秒，hedge-option-close-late-final-regression-check.log），与13专项及20公开CLI同源码。全部测试/CLI句柄已终止，无待轮询任务。当前可继续股票显式剩余/报价修订：原计划须确认无人工在途并关闭未执行部分；冻结当前组/阶段/财务前缀、原成交切片、剩余方向/单位和当前合格原价，不改变父候选或重开已完成方向。OPEN及CLOSE修订、退出依赖及原生单位行动仍未完成，不能把本批期权迟到成功算最终v1.9。随后原生提前指派/净交割异常恢复、多期权标的、资格联动及统一P5/O6/H5继续。Goal active。


## 当前批次：股票原生报价及剩余修订（2026-10-12）

新增hedge-stock-reprice公开预检/提交：原计划明确结束/无人工在途且释放旧预留后，引用当前组/资源及完整当前风险，独立计算冻结前缀下原方向确切剩余数量、合格原价/费用/日历及新修订身份。没有新月度Signal、父候选或金融事实；新DRAFT须显式替换原组剩余并重新激活。CLOSE引用修订可跨父新增风险窗口，但固定原关闭起点及配置execution_window_sessions上界，不逐次延长。原关闭依赖可包含已成交/替代OPEN切片，原成交与关闭总义务单次核对。

首轮1失败（19.94秒，hedge-stock-reprice-check.log）：配置symbols/weights内存元组与JSON列表直接比较，规范化内容一致却误判；改规范化内容比较，未取消独立价格/费用/剩余核对。第二轮2完整路径通过（101.23秒，hedge-stock-reprice-second-check.log），包含部分OPEN换价/关闭依赖、新价格完整CLOSE、独立资金/费用/股数和完整恢复。

现补部分CLOSE多次修订的原退出义务/窗口、拒绝未释放/过期成交时间/新外部资金/旧资源，并核对分红/已凭据费用可作为内部更新；第三轮相关回归正在运行，hedge-stock-reprice-third-check.log，当前仅该句柄活跃，源码冻结。b6106a7f的期权13/40/20CLI为历史证据；本批公开CLI和扩大相关回归仍待，未标v1.9完成。

股票第三轮20项无跳过通过（172.78秒，hedge-stock-reprice-third-check.log）。独立重哈希根组并加historical_slice实际复现会使必需阶段门禁返回UNBOUND_NATIVE_PLAN（hedge-root-slice-before-check.log）；现严格核对根阶段与原request字段、原生数量，根不接受修订专用隐藏标识。第四轮37项无跳过通过（187.45秒），覆盖根隐藏标识3负例、合计不变但原成交切片21/19伪造、固定退出窗口禁止逐次延长。实际CLI仍在验证，不冒充最终验收。

内部应收/到账/费用独立1项通过（15.78秒）；增加前向原计划/组/父/行情实际接收时点门禁后，第五轮42项无跳过通过（188.76秒）。当前仅49671扩大相关回归及92294第四轮CLI活跃。第三轮CLI脚本预期2仍错误，公开main对BLOCKED返回3，按实际契约修正；业务取消与门禁未改。源码保持冻结。

扩大相关回归首轮32通过/1失败（308.61秒）：严格根组核对现在提前返回CORRUPT_HEDGE_GROUP，旧监测测试仍索引progress[0]导致IndexError。改为明确核对BLOCKED、空progress和具体损坏错误；业务门禁未放宽。后续监测/原生引用/期权组修订/daily/备份50项无跳过通过（122.81秒，hedge-stock-reprice-related-second-check.log）。第四轮CLI已通过24个入口后在部分成交计划取消时失败：该计划check_status=PASSED实际返回0，原草案BLOCKED则返回3。脚本现同时核对结果状态及其对应退出码，零预留/无人工在途仍须成立。第五轮完整CLI正在运行（94726），当前唯一活跃任务；源码冻结。

股票报价/剩余完整第五轮37CLI通过；所有相关测试/CLI句柄已终止。当前新原生指派恢复测试进行中，native-incident-recovery-check.log；未声称重跑LEAN或真实行情/券商凭据，该测试使用与当前适配器哈希一致的原生A8归档。

## 原生指派恢复与CSV入口审计（2026-10-12）

原生Call/Put价差部分指派两条跨进程恢复测试第三轮通过（2 passed / 7.77秒，native-incident-recovery-third-check.log）。原引擎真实运行归档的实际事件先独立交叉核对标准合约、数量、费用与时点，再测试金融写入后/审计发布前中断回滚、重启、重跑、下一日恢复、Call中间-100审查和完整备份恢复。Call原现金110386/股数-100、Put原现金90386/股数100；两例最终现金100386/零股，独立预期为100000-210+100-4+500。未重新运行LEAN，不冒充真实期权数据。前两轮失败为测试把归一化contract内嵌字段当输入，以及备份相对runtime未切换cwd；修测试映射/目录，业务未放宽。

独立复现public options import-facts未创建逐凭据审计：1失败（12.86秒，options-csv-receipt-before-check.log），同批实物交割最终为零却漏掉中间-100。现在CSV提交调用共享import_batch，稳定批次ID绑定文件内容及预检序号，事务包含金融事实与风险审计；保留原added/pending字段并追加receipt_audit_id/has_intermediate_anomaly。原native两项、CSV负例及凭据/风险/审查/更正/账本/生命周期/CLI共50项无跳过通过（20.41秒，options-csv-receipt-final-check.log）。源码已变化，股票319af364证据作为历史，不冒充新全量。当前2914原生公开CLI和新预检重复导入专项运行中，源码冻结；其后单位行动、多期权标的、资格联动及最终验收继续。

原生公开17CLI全部通过（native-incident-recovery-cli-20261012/verification.json），与最新50相关及新预检重复1项为a985f7ca源码。真实native assignment/next-day exercise的合成机械记录已进入公开CSV审计/异常/核实/完整备份链；最终100386、零股、序号5。所有进程已终止。接下来单位行动显式重规划；上述记录不代表整个v1.9或真实期权条件验收。

股票单位换算8项通过（0.32秒，hedge-stock-unit-math-check.log）。未启用新交易接口，旧拆股阻断不放宽。下一实现必须同时处理：原阶段/每笔成交各自单位基准、原OPEN候选经济数量守恒、历史成交切片和单次CLOSE总义务、已完成原阶段的当前单位显示、未完成方向的显式草案、当前原价/风险/序号/资源与备份校验。先支持有明确SPLIT事实的纯股票组；涉及期权单位行动/未知交割条款或交易单位零碎尾差仍须凭据核实，禁止直接缩放期权合约。Goal active。

普通股票报价修订已复用stock_units的逐成交剩余核对，但显式拒绝任何单位变化，不借此解除拆股门禁。当前50整合项（8单位+42原股票专项）及实际37CLI正在运行，句柄99699/65164；等待全部终态后才修改源码。下一项单位重规划草案和组单位基准/原父数量守恒/历史切片/单次关闭义务的成套契约，不能只缩放新计划而留下旧退出依赖。

通用CSV独立复现遗漏审计（1失败/12.88秒，generic-csv-receipt-before-check.log）。现CLI import-events、UI提交、daily._import共用import_statement；股票/现金/期权混合账单不丢普通费用/资金，v19账户一旦涉及期权保留每个财务前缀，完整覆盖声明与审计同事务。首轮77项通过（108.39秒），之后修UI直接脚本的绝对导入并加混合费用/审计故障回滚2项；第二轮69通过/1准备错误（67.63秒，/tmp空间不足，非业务断言），仅清理已终止自有测试目录并保留源A8证据/日志；第三轮79项无跳过通过（109.48秒）。实际通用原生17CLI、浏览器7项与79回归同6af81084源码。浏览器首轮两次上传已通过，但隐藏radio输入被标签覆盖导致超时；改点击可见导航标签，第二轮全部通过。使用现有只读agent-reach Python/Playwright与缓存Chromium/portable系统库，不安装/修改用户环境；应用仍运行v19-clean。8506临时测试服务已停，所有句柄终止。


2026-10-12单位批次终态补记：stock-unit-final-third 50通过/1失败377.79秒，实际篡改样例删除as_of触发未处理KeyError；已改为明确NATIVE_STOCK_UNIT_BASIS_MISSING阻断，不假定当前时点。fourth旧测试只允许一个错误码，9通过/1失败24.05秒；新版同时精确核对NATIVE_PLAN_LINES_CHANGED和缺基准两项原因，业务门禁保持阻断。fifth44项及stage33项已同aad6016b源码通过；第三CLI40项实际通过/完整恢复，早于最后诊断修复，依其自身verification指纹保留。上述所有句柄终止；新活跃为多标的测试15395及A8机械重跑37090。
