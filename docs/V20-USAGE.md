# LyraX v2.0 开发使用说明

状态：v2.0本地P0–P8编码及验收完成，1110项完整逐阶段无跳过通过；外部条件仍见支持矩阵。Python3.11独立Conda环境，沿用已锁定依赖。旧v1.95发布归档保留。

## 输入与实验

1. 固定样例继续使用原工作区入口。
2. 多月模型包使用 `input-package scenario --file configs/v20-scenario.json --destination /绝对路径/新输入包`。QuantLib合成报价不是实际行情。
3. `input-package verify --source /绝对路径/输入包` 逐文件核验；非空公司行动等未核实事项阻断配置。
4. 工作区初始化spec可增加 `input_bundle`。ETF分别绑定signal/execution/valuation快照；输入更新需要新实验，已有运行不跟随latest。
5. 期权prepare配置增加 `input_bundle`、`max_cycles`、`retain_stock`。规则、资金、费用及来源全部冻结，更改代码后另建实验。

示例公开CLI完整验证脚本：

```bash
python scripts/verify_v20_quarter.py --destination /绝对路径/新验证目录 \
  --engine-root '/绝对路径/LEAN' --dotnet '/绝对路径/dotnet'
```

## 工作台

运行状态页增加工作区/输入、场景生成、后台维护和任务核实入口。调仓计划页增加只读多策略预算预演。所有查看、刷新和预演不新增资金事实。

- 新工作区使用独立目录、账户和资金。打开新看板使用明确本地端口，不全局切换服务器cwd，也不停止未知占用端口的服务。
- 场景生成器接受日期、价格/IV节点、随机种子、期限与价差，后台生成。节点须为交易日，缺价不补成可成交数据。
- 普通模板可选持续持股。Wheel使用自然到期；后续月度阶段通过此前原生前缀账本决定，未结算/不满足覆盖则阻断，不用未来结果预选分支。
- 任务重跑采用稳定请求身份。未知、损坏或中断记录保留；核实无在途后使用当前文件指纹记录人工复核，不撤销实际成交或释放计划担保。
- 维护任务复用完整备份格式；恢复到新目录。成功回执和实际业务完成状态分别显示，任务完成不授予来源或账户资格。

## 四腿模板

铁鹰与铁蝶均按同到期、标准100股美式实物合约研究。铁蝶短Put/Call共用ATM，双翼等宽；铁鹰两侧OTM，翼宽由显式minimum_spread_width约束。先建立长翼，再形成短腿义务。资金按双方履约分别预留，不假定组合保证金或借款。

原生机械样本使用100000USD和每张2USD；开平仓损失包含买卖价差及佣金。它检验账务和生命周期，不证明投资收益。

## 研究协议

冻结研究问题、候选参数、开发/评估决策窗口、成本、初始资本和退出政策。开发窗口必须早于评估，最多24个预声明实验。不同窗口/成本独立报告，不拼接净值或跨成本排名。源/参数改变需要新研究目录，失败和报价不足计入覆盖结果，不隐藏。

股票/现金基准与候选复用同一LEAN运行条件、资本与区间。佣金、价差、交易损益和交割现金分别解释；价差已体现在bid/ask成交，不再从净值重复扣除。短样本年化只作换算。

## 数据和前向边界

供应商分页协议仅已录制故障样本验证，真实期权源仍属E1。前向追加契约禁止覆盖已有日输入，迟到修订独立研究；测试时钟不是自然前向证据。E2实际观察、E3同账户多策略执行及原GOAL券商自动交易不包含在本地编码授权内。

实际用量和API/工具费用未获取。未安装调度、未提交Git或开通付费服务。

## 安装和工具路径

使用独立Conda Python3.11.15；Linux x86_64依赖锁与v1.95相同，普通wheel版本2.0.0。当前发布wheel：`reports/v20-validation/release-final/wheel/lyra_personal_quant-2.0.0-py3-none-any.whl`，详见V20-DELIVERY。示例配置/验证脚本随源码归档提供，wheel不含整个仓库、第三方LEAN或SDK。

```bash
python -m pip install --require-hashes -r requirements-linux-py311.lock -r requirements-options-linux-py311.lock
python -m pip install --no-deps /绝对路径/lyra_personal_quant-2.0.0-py3-none-any.whl
python -I -m pip check
```

明确外部工具，支持带空格路径；不要用Python的PYTHONPATH代替应用配置。工具身份改变需重新核验当前模板，不转用旧资格。

```bash
export LYRAX_TEST_ENGINE_ROOT='/绝对路径/LEAN'
export LYRAX_TEST_DOTNET='/绝对路径/dotnet'
```

优先使用有固定提交/已编译Launcher的LEAN和.NET10.0.100。对应历史构建说明见V19-USAGE；本次实际验证使用官方LEAN提交`80e7843f645673bcbeaab963049f76f20f6785e1`。普通wheel安装时子进程使用同一解释器`-I`，不会继承任意PYTHONPATH/PYTHONHOME。

## 新版实际验证入口

以下脚本会创建新目录，目标不能重用。安装验证脚本本身从源码归档运行，应用从当前普通wheel导入；无需真实账号或密钥：

```bash
python -I scripts/verify_installed_v195.py --project /绝对路径/源码目录 --destination /绝对路径/新的兼容验证目录 --engine-root "$LYRAX_TEST_ENGINE_ROOT" --dotnet "$LYRAX_TEST_DOTNET"
python -I scripts/verify_v20_quarter.py --destination /绝对路径/新的三月验证目录 --engine-root "$LYRAX_TEST_ENGINE_ROOT" --dotnet "$LYRAX_TEST_DOTNET"
```

前一脚本名称保留兼容，当前ETF流程显式给256会话预算；后一脚本生成三月非恒价场景，执行8条CLI并验证重复推进不增加7笔模拟事件。99633USD是固定输入工程断言，不是推荐资金或收益目标。

开发环境可执行：

```bash
python scripts/check_v20.py --scope fast --destination /绝对路径/新的快速门禁目录
python scripts/check_v20.py --scope release --destination /绝对路径/新的完整门禁目录 --timeout-seconds 28800
```

release重新收集所有测试并逐setup/call/teardown核对，失败即停止且报告覆盖不完整；禁止用fast或某个原生组替代整版发布门禁。当前同源码fast实际60项28.05秒（完整门禁包装37.62秒）；WSL挂载盘/同时任务会影响时间，非性能承诺。

浏览器脚本`verify_browser_v20.py`需要另行提供Playwright/Chromium及系统动态库，不属于应用运行依赖；本次工具安装隔离于/tmp，不修改应用锁。该脚本会临时启动仅localhost的两个自有服务并在finally停止它们，不能停止未知端口所有者。手工看板使用原`ui --workspace ... --port ...`，账户、数据截至时点和类型在四页分别显示。

维护、升级、原始任务核实及首提交审阅见[V20-MIGRATION](V20-MIGRATION.md)，支持/未验证边界见[V20-SUPPORT-MATRIX](V20-SUPPORT-MATRIX.md)。任务文件清理预览保守保留全部原始/孤立凭据，不提供按年龄盲删运行记录功能。

## 原生盘容量有限时的完整门禁

完整临时产物历史约10.3GB。/tmp空间不足以一次容纳全部时，按完整测试模块分成独立进程，成功组先完整归档并读回校验，才释放自有临时目录；失败组保留。不是跳过测试，不按失败筛选节点。

```bash
python scripts/check_v20.py --scope release --destination /tmp/lyrax-v20-release-r6 --integration-groups 8 --archive-temp-to /绝对路径/全新归档目录 --timeout-seconds 28800
```

每个阶段的节点和setup/call/teardown仍与完整收集清单逐项核对；archive_seconds、归档SHA256及成员清单单独记录。测试临时归档可能包含复制的SDK，属于本机原始证据，不纳入项目源码/wheel发布。原始失败目录不自动删除。

## 滚动研究终点与结算完成

持续持股选项表示跨月复用股票；当前研究模式在冻结的rolling_end_session退出股票。市场末日处理完，仍可能有卖出应收，业务状态为PAUSED。按实际成交中已记录的settlement_at继续到结算日，待COMPLETED且应收应付归零后才算账户闭环。调度/任务传输成功不等于业务完成，不以日历提示UNKNOWN覆盖实际凭据，也不补造缺失价格。

当前实际浏览器补验：三周期备兑Call滚动到2024-10-31有9998USD应收，9事件；按原SELL中明确的2024-11-01结算日期继续后，COMPLETED、应收应付0、权益100283USD，仍9事件。只是固定模型样例。观察期间一个日期脚本误提交2024-01-01被正确拒绝；原始失败保留，业务代码未因此修改。
