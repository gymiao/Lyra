# README历史快照

保留2026-10-16整理前的说明；旧版本数量、地址和服务状态不代表当前状态。当前入口见仓库README与PROGRESS。

# LyraX：个人量化投资系统 v1.9 开发版

**v1.95验收中，源码版本1.95.0，尚未宣布整版完成。** 期权配置、公共计划、模拟恢复、实验比较、风险工具及异常指派已分组验证；清洁完整依赖/wheel模拟已通过开发批次，正在核验最终同源码测试、浏览器和发布包。见[进度](docs/PROGRESS.md)、[操作](docs/V195-USAGE.md)及[计划](docs/lyraX-v1.95.md)。

**当前可用演示：** 用户要求先跳过真实账号，已运行合成期权历史模拟账户；看板http://localhost:8501，操作与报告见[模拟账户说明](docs/V19-SIMULATION-USAGE.md)。

系统名称为 **LyraX**，CLI沿用 `lyra`；下列启动命令可直接使用。

中文日线研究、月度策略、模拟跟踪、人工调仓建议及账户账本。演示为美股 ETF SPY / IEF / GLD、USD、只做多、无杠杆；真实账户从零开始。V1 没有券商下单接口。

**V1工程验收完成。** 独立Conda清洁重装、180项回归无跳过、32条离线CLI、真实Yahoo行情到bt双策略复现、四页浏览器/提交/恢复以及README命令均通过。完整说明见[交付](docs/DELIVERY.md)、[agents.md](agents.md)与[验收](docs/ACCEPTANCE.md)。真实账户资料、长期前向记录及自动交易条件单独说明。

**v1.5工程验收完成：231项测试无跳过、新41条/旧32条CLI、实际浏览器通过。** 已实现六类只做多模板、中文草稿/预检/版本编辑、多策略bt研究、后台任务、因子时点、月末绑定和完整恢复。使用与验收见[操作说明](docs/V15-USAGE.md)、[v1.5交付](docs/V15-DELIVERY.md)；设计与范围见[原计划](docs/lyraX-v1.5.md)。真实基本面资格与真实账户凭据单独记录。

**稳定交付基线：LyraX v1.8.0核心工程完成。** 已修复独立数据用途与并发因子合并，增加可还原研究包、分段/成本验证、执行复盘、doctor与本地待办。最终257项测试、新34条/旧32条CLI及浏览器验收见[v1.8交付](docs/V18-DELIVERY.md)、[使用说明](docs/V18-USAGE.md)。真实原价/基本面及账户凭据仍按资格检查阻断，不以测试代替实盘条件。

**v1.9历史基线：1.9.0.dev0，核心本地工程已验收、实际接入/观察未完整验收。** 已实现诊断恢复、备份维护、账单映射/来源资格、归因/滚动/双动量与隔离paper汇总；期权使用标准合约/版本化链、14类目录、A8选约、QuantLib定价/压力及模型Delta输入资格、LEAN机械研究与生命周期、v5统一账本。对冲已有风险归档、数量/压力、父意图、共用预留、阶段计划及关闭/修订/日常监测。详见[V19-USAGE](docs/V19-USAGE.md)、[支持矩阵](docs/V19-SUPPORT-MATRIX.md)和[进度](docs/PROGRESS.md)。

当前源码已通过普通wheel清洁Conda安装、真实Yahoo ETF截至2026-10-12的双策略复现、四页浏览器以及17条原生异常恢复CLI/重复账单提交。此前7849源码核心本地验收通过：802项无跳过、旧V1/V15/V18入口32/32/34、核心52/模型11/资格12CLI、清洁安装、真实ETF复现及完整四页/账单/计划浏览器均通过。随后补齐H0产品方法目录，当前c0a9的6相关/空账户浏览器/安装CLI已通过，当前804全量无跳过及核心53/模型11/资格12、完整四页已通过；旧802仅为历史。实际期权来源/账户资料和自然前向仍缺，完整计划未全部完成；见[工程交付](docs/V19-DELIVERY.md)。 当前指纹和日志见PROGRESS，旧180/231/257项不算新版本验收。

期权样本明确为**合成测试**，与真实ETF研究分别标识。实际期权历史/报价、证券原价、账户权限及自然前向仍缺资格证据；资料不完整时草案BLOCKED。合成demo可在明确门槛通过后产生READY并模拟执行；READY不表示券商订单。B/HX条件扩展不得凭目录或泛用情景工具宣称完整支持；没有自动下单接口。

## v1.9 全量本地验证

须已有[V19-USAGE](docs/V19-USAGE.md)中隔离LEAN SDK/Launcher和A8持久验证证据；脚本会核对证据与当前引擎源码，不能用空文件替代。下列入口已实际执行通过，802项pytest无跳过：

```bash
LYRAX_PYTHON=/mnt/c/quant/project/lyra/.conda/v19-clean/bin/python \
LYRAX_TEST_ENGINE_EVIDENCE=/mnt/c/quant/project/lyra/reports/v19-implementation/multi-native-engine-evidence-20261012/verification.json \
MPLCONFIGDIR=/tmp/lyrax-mpl PYTHONDONTWRITEBYTECODE=1 \
  bash scripts/check_v19.sh
```

默认创建新的reports/v19-validation/full-<id>，清单记录锁/输入文件哈希、源码、实际收集数、依赖检查、全仓pytest及CLI。缺引擎证据报错，测试须无跳过且通过数等于收集数。终态LOCAL_AUTOMATED_CHECKS_PASSED只说明本地自动检查通过；清洁安装、在线、实际浏览器和自然前向分别验收。

本机当前普通wheel安装验证在.conda/v19-release-install，证据reports/v19-validation/clean-final-20261013-second/verification.json；实际行情研究报告在reports/v19-validation/online-final-20261013-second/runtime/demo/reports/research/5b621a58047241d4be34aa090756356a/report.md。这些本地产物不提交Git；不包含实际用户账单或密钥。整体交付状态见[最终验收追踪](docs/V19-FINAL-AUDIT.md)。

## v1.8 快速复现

安装后在项目根目录执行：

```bash
python scripts/verify_v18.py
python -m pytest -q
```

演示无需密钥，在新目录完成研究、测试账户、计划、成交、复盘和备份恢复。结果位置记录在`reports/v18-validation/latest.json`。升级、用途绑定及看板启动见[操作说明](docs/V18-USAGE.md)。

## 安装

验证平台：Linux x86_64 / WSL，Python **3.11.15**。在项目根目录执行：

```bash
conda create --override-channels -c conda-forge --prefix "$PWD/.conda/lyra" --file conda-linux-64.lock --no-default-packages --yes
conda env config vars set --prefix "$PWD/.conda/lyra" PYTHONNOUSERSITE=1
conda activate "$PWD/.conda/lyra"
python -m pip install --require-hashes -r requirements-linux-py311.lock
python -m pip install --no-deps --no-build-isolation -e .
python -m pip check
lyra --help
```

已创建 `.conda/lyra` 时跳过第一行。当前清洁安装实际由26个已校验Conda基础包新建前缀，再按上述77包哈希锁重装；普通 `environment.yml` 需要Conda索引，本次索引请求超时；推荐上面的显式基础锁，已实际从官方包URL创建成功，跳过索引解析。YAML保留为可编辑的基础定义。锁文件包含测试与个人回报扩展，平台不同需重新验证。构建项目需要已锁定的 setuptools/wheel；不引入另一个环境的 site-packages。

环境激活设置 `PYTHONNOUSERSITE=1`。若系统已有 `PYTHONPATH/PYTHONHOME`，执行前移除；未激活时可用 `.conda/lyra/bin/python`，并显式设置 `PYTHONNOUSERSITE=1`。原 `.venv` 仅保留历史，不再作为运行入口。

## 无密钥离线复现

```bash
python -m pytest -q
python scripts/verify_offline.py
python scripts/verify_v15.py
```

离线脚本每次创建独立目录，执行32条CLI并保存命令/返回码/源码指纹。覆盖标准测试账单、独立手算对账、重复导入、12份历史信号、六个月模拟、三个月九节点分红/拆股/出金、daily及完整备份恢复。最新报告入口为 `reports/offline-validation/latest.json`。

独立预期：现金503.5、SPY10份、资产998.5、净投入1000、盈亏-1.5；生命周期期末现金350、IEF9份、资产800、净投入900、盈亏-100。新增入金不算盈利。所有这些数据均明确为测试/模拟，不是真实账单或前向业绩。

完整演示包含实际 bt 回测和模拟账户。请使用独立工作目录，避免改变已有在线系列或其他账户：

```bash
LYRA_PROJECT="$PWD"
mkdir -p reports/manual-demo/configs
cp configs/demo.toml reports/manual-demo/configs/demo.toml
cd reports/manual-demo
lyra demo
lyra status
lyra ui
```

`demo`只允许demo环境，测试入金由demo_deposit配置（示例10000 USD），非用户真实资金；一个环境数据库仅支持一个账户。已有数据时不要跨来源混用。`ui`前台运行，按 Ctrl+C 退出；服务会从当前工作目录读取配置及运行数据。

## 在线行情与研究

回到项目根目录，使用与演示分开的数据目录：

```bash
cd "$LYRA_PROJECT"
mkdir -p reports/manual-online/configs
cp configs/demo.toml reports/manual-online/configs/demo.toml
cd reports/manual-online
lyra fetch --new-series --start 2023-01-01 --end 2025-01-17
lyra research
lyra fetch --start 2023-01-03 --end 2025-01-17
```

Yahoo / yfinance 无需示例密钥，结束日期不包含。网络与数据源可用性不作保证，不自动购买服务。实际下载已验证SPY/IEF/GLD共1536行；增量回看14天，重叠复权修订/新行动触发全历史刷新，不静默拼接来源。初次切换来源需显式 `--new-series`，也可显式 `--full-refresh`。

规则在观察报告前确定：固定等权基准；月末复权收盘严格高于126日均线时保留原基准权重，否则留现金。开发检查期2024-01-02至06-28，最终评估期07-01至12-31；不自动搜索参数或选收益赢家。区间、资金、价格口径及成本在配置中固定。

月末收盘后产生信号，下一交易日收盘成交，成交前收益归旧持仓。bt为唯一主回测；复权虚拟份额不等于真实证券份额，分红不重复加现金。佣金2bps、滑点5bps为演示假设，滑点按等价成本扣除。收益/回撤纳入首日费用，CAGR注明实际自然日观察期；波动年化因子252。单次换手为买卖绝对金额之和除以2倍当日成交前权益，包含首次建仓。

`runtime/demo/reports/research/<run_id>/`包含report.md、manifest.json、净值、回撤、两策略权重/持仓、信号及成交CSV。清单冻结输入、源码、配置、依赖及成本假设。当前真实示例的run_id和复现结果见 `reports/online-validation/20261009/`；历史可用时点是假设，不冒充当时采集证据。

**Yahoo Close仍标记为供应商拆股调整口径，不能直接计算真实证券买卖数量。** 实际执行需核验的原价CSV；分红支付日及实际税费需CSV/账单补齐。真实来源的研究成功不解除执行价格资格检查。

## 最新真实行情研究看板

2026-10-09实际更新已完成：SPY/IEF/GLD各945交易日、共2835行，截至2026-10-08。两策略共同评估2024-07-01至2026-10-08（571日），参数没有调整。报告与页面检查见 `reports/live-research/20261009/verification.json` 和 browser-verification.json。

系统更名后的最新研究报告：`reports/manual-online/runtime/demo/reports/research/f48e6d855a7b4e5384593f4a0aa16d25/report.md`；名称及页面验证见 `reports/branding/20261009/verification.json`。

历史真实ETF研究工作区的启动方法保留如下。当前localhost:8501运行的是用户新要求的合成期权模拟账户，见[模拟使用说明](docs/V19-SIMULATION-USAGE.md)，不要把该地址当作真实账户或真实期权行情。

服务退出后，从项目根目录激活Conda并重新启动：

```bash
conda activate "$PWD/.conda/lyra"
cd reports/manual-online
lyra --config configs/research-current.toml ui
```

浏览器进入 `http://localhost:8501/?view=research`。research-current.toml是本次工作目录的本地配置，评估终点固定为本次更新日期；之后下载新数据需同步评估终点再生成报告。本次没有安装自动更新任务。

## 信号、计划和账单

统一CLI支持：`fixture`、`import-prices`、`fetch`、`research`、`signals`、`list-signals`、`plan`、`simulate`、`account`、`import-events`、`reconcile`、`report`、`daily`、`backup-bundle`、`verify-backup`、`restore`、`status`、`demo`、`ui`。各命令参数用 `lyra <命令> --help` 查看。

标准 [CSV模板](templates/) 与 [测试账单](examples/) 见 [字段说明](docs/CSV.md)与[配置说明](docs/CONFIGURATION.md)。导入默认只预检；提交须使用返回的expected_sequence和batch_hash。文件/账户变化需要重新预检。同ID同内容不重复入账，同ID不同内容拒绝，整批失败回滚。券商原始文件需映射到标准CSV。

信号SQLite归档冻结首次生成时间及版本，signals.json仅为导出。paper/real只用实际前向时钟，不能从历史报告补造当前信号。计划持久化目标、实际持仓、建议数量、参考价/时间、费用及检查；READY是人工建议，没有向券商下单。未解决对账、缺数据、资金不足、过期或价格单位未知都会阻断执行。

页面刷新不产生交易。账单提交后共享事务更新账本/关联计划，再生成报告；实际事实只依据账单，不能用建议或估算费用覆盖实际成交。部分/迟到/计划外成交支持导入；人工在途资源只有确认结束后才能释放。

真实使用复制 `configs/real.example.toml` 为本地配置，明确费用、风险、交易单位、结算、数据发布和启用策略；使用 `--config`显式选择。真实账本只接收actual凭据，从零现金/持仓开始。对账要求同账户/币种/时点/现金口径，真实凭据独立且有哈希，不用系统自己的快照冒充券商对账。

## 日常执行和恢复

`scripts/verify_offline.py`已执行月末计划→次日成交→结算以及完整备份恢复。下面重跑其最新恢复目录，不会增加业务事件；备份目标必须不存在或为空：

```bash
cd "$LYRA_PROJECT"
LYRA_RUN_DIR="$(python -c 'import json; print(json.load(open("reports/offline-validation/latest.json"))["root"])')"
cd "$LYRA_RUN_DIR/daily-restored"
lyra --config configs/recovered.toml daily --account-id daily-account --as-of 2024-08-02T21:00:00Z
lyra --config configs/recovered.toml backup-bundle --destination "$LYRA_RUN_DIR/documentation-backup"
lyra verify-backup --source "$LYRA_RUN_DIR/documentation-backup" --environment demo
lyra restore --source "$LYRA_RUN_DIR/documentation-backup" --destination "$LYRA_RUN_DIR/documentation-restored" --environment demo
```

历史时钟只用于demo。真实/paper日常任务使用实际时钟，完整日线未发布时WAITING，检查失败BLOCKED，系统失败FAILED。跟踪缺口列出漏跑/阻断月份，不补造历史信号或成交。对账基线、价格跳变和数据新鲜度阈值配置化，不保证最大回撤。

备份包包含对应配置、SQLite、已发布行情/信号/报告及哈希；校验后只恢复新空目录。运行目录之外的原始账单、密钥及授权文件另行备份。并发变化、中断、坏哈希、路径越界及跨环境恢复会拒绝。调度与备份边界见 [运行维护](docs/OPERATIONS.md)。

## 已知限制与下一阶段输入

- V1仅XNYS/USD；日线参考价不能保证实际成交。Yahoo历史Close尚非真实数量依据，源的支付日不完整需补凭据。
- 模拟、研究及实际账户隔离；标准账单验证已完成，没有用户真实券商账单映射/账户权限验证。
- 月末真实前向采集、信号归档和长期cron运行尚无实采周期证据；固定时钟测试不能作为这类凭据。
- XIRR由pyxirr计算外部资金流与期末权益，内部买卖/分红不重复作为投入；无解、现金流不足/多次变号显示原因。
- 合并、分拆、实物转入转出及复杂税务事件需待核实，不能伪装成买卖/入金；不使用复杂撮合引擎。
- 跨平台锁文件不在当前验证范围；当前README复现和页面异常恢复已完成。依赖与数据权限分别见 [DEPENDENCIES](docs/DEPENDENCIES.md)。
- 无交易所停牌状态源；零成交量保留为不合格诊断并阻断信号/数量/模拟成交，不认定已确认停牌或填充旧价格。

真实使用需要市场/标的、账户费用、单位、结算、风险参数及实际账单；不因缺这些资料伪造账户。V2自动交易还需券商、API权限及用户明确要求，软件开发授权不包含真实自动下单。

### 2026-10-14 当前验收结果

当前c0a9dcee：804项无跳过、旧32/32/34及当前53/11/12 CLI/恢复通过；329输入一致。对冲目录4项实际浏览器及普通wheel升级通过。完整实际ETF研究/账户浏览器/清洁环境为7849历史证据；金融模块哈希未变，范围见[最终审计](docs/V19-FINAL-AUDIT.md)。真实期权源、账户凭据及自然周期未验收，未宣称整个计划完成。
