# LyraX v1.9 开发版操作说明

## 对冲方法目录（空账户可用）

```bash
.conda/v19-clean/bin/lyra --config configs/demo.toml hedge-catalog
```

实际CLI和普通wheel入口已验证：返回16种方法、用途、主要风险、所需输入与支持等级，不创建runtime、账户、计划或任务。四页均有“对冲方法目录与支持等级”折叠区，账户为空时也可以查看。

reduce_stock、inverse_etf、protective_put、collar、proxy_put是当前HedgeSpec工具；covered_call仅为A8收益叠加模板，不视为完整下跌保护。Put价差/连续滚动、股票卖空/多空/配对/因子中性、期货、动态Delta/VIX/跨资产按B/HX条件批次显示未支持执行。目录所有executable均false；具体账户仍需数据、权限、资源及风险检查。

当前目录源码c0a9dcee；6相关回归、空账户实际浏览器4检查和安装CLI只读性已通过。804全量门禁正在运行，前次7849/802为补齐前证据。


2026-10-14（工程证据2026-10-13）。版本1.9.0.dev0；核心本地编码/验收通过，实际来源/账户权限及自然前向未完整验证，状态见[PROGRESS](PROGRESS.md)和[交付](V19-DELIVERY.md)。以下期权样本都是明确标注的合成数据，不是实际期权报价或交易记录。

## 环境与完整离线检查

Python3.11.15 / Linux x86_64 / WSL；独立前缀`.conda/v19-clean`已实际安装。基础依赖沿用requirements-linux-py311.lock，新增QuantLib1.43独立wheel哈希锁requirements-options-linux-py311.lock。不要向其他投资项目环境直接升级依赖。

```bash
# 在项目根目录、已激活的隔离Conda环境中
python -m pip install --require-hashes -r requirements-options-linux-py311.lock
python -m pip check
python scripts/verify_v19.py
```

验证脚本创建新的`reports/v19-validation/<id>/workspace`，运行合成数据、v5迁移、扣费研究、期权工具、账单幂等、诊断、备份及恢复；输出verification.json。与实际研究目录reports/manual-online隔离。固定账单手算现金598、SPY4份、权益998；新增期权测试成交发生于2026年，不能改写2024年账户结果。

此前V1/v1.5/v1.8命令和报告保留，见[V18-USAGE](V18-USAGE.md)。v5需执行`lyra --config config.json v19-init`，先验证完整备份再迁移；页面也提供显式启用按钮。页面刷新不自动迁移或生成资金事件。

## 期权目录、理论情景与压力

`LYRAX_ROOT`填项目绝对路径；WSL存在目录大小写别名时使用拥有写权限的路径。进入验证输出的workspace，使配置中的runtime/demo指向对应隔离目录。

```bash
LYRAX_ROOT=/mnt/c/quant/project/lyra
# cd 到脚本输出的 workspace；以下命令均在该工作区执行
lyra --config config.json options --action catalog
lyra --config config.json options --action scenario --file "$LYRAX_ROOT/examples/options/protective_put.json"
lyra --config config.json options --action price --file "$LYRAX_ROOT/examples/options/european_call.json"
lyra --config config.json options --action stress --file "$LYRAX_ROOT/examples/options/calendar-stress.json"
```

同到期情景分析全域尾部和盈亏平衡，不用有限绘图区间估计裸Call最大损失。跨期压力在近月到期时使用QuantLib保留远月理论时间价值；缺失IV/模型参数和未观察的更早到期路径明确报错。理论计算不会更新账本，也不能填充实际成交价。

## 合约、链、选约与草案

```bash
lyra --config config.json options --action import-chain --contracts "$LYRAX_ROOT/examples/options/contracts-a8.json" --file "$LYRAX_ROOT/examples/options/quotes-a8.csv" --metadata "$LYRAX_ROOT/examples/options/metadata.json"
# SNAPSHOT 替换为导入输出的 snapshot_id
lyra --config config.json options --action check-chain --snapshot-id SNAPSHOT --as-of 2026-10-09T19:46:00Z
lyra --config config.json options --action select --snapshot-id SNAPSHOT --file "$LYRAX_ROOT/examples/options/selection.json"
lyra --config config.json options --action plan-draft --snapshot-id SNAPSHOT --account-id v19-demo --file "$LYRAX_ROOT/examples/options/plan-draft.json"
```

A8选约按当时已收到的合约和报价、期限范围、45日目标、95% Put/105% Call及明确同步/价差参数冻结。示例参数只为工程验证，不代表实际账户风险条件。以后收到的报价不会遮蔽此前报价或改变此前decision_hash。

草案保存稳定身份/修订、整张数量、买ask/卖bid参考、费用、权利金、担保/覆盖和检查原因。草案目前始终DRAFT/BLOCKED、executable=false、不预留资金。已有证券被ETF计划或期权义务占用时，检查不能再次把它用于覆盖。实际来源、账户权限和完整生命周期门槛没有通过，不能把终值损失有限当作可执行证明。

## 期权事实与账单映射

标准期权事件CSV示例为examples/options/test-option-events.csv；先登记确切合约版本，再预检，提交必须携带原文件哈希和账户序号：

```bash
lyra --config config.json options --action register-contracts --contracts "$LYRAX_ROOT/examples/options/contracts.json"
lyra --config config.json options --action import-facts --account-id v19-demo --file "$LYRAX_ROOT/examples/options/test-option-events.csv" --as-of 2026-10-09T21:00:00Z
# 根据预检输出填写HASH、SEQ后显式提交
lyra --config config.json options --action import-facts --account-id v19-demo --file "$LYRAX_ROOT/examples/options/test-option-events.csv" --commit --expected-hash HASH --expected-sequence SEQ
```

支持成交/平仓、实物行权/指派、到期及现金结算的明确凭据；现金结算不能套实物合约。重复ID同内容不重记账，冲突报错。无法支持的调整/未知行动保留待核实凭据并阻断；当前未提供自动解决这些凭据的按钮，不能通过忽略差异解除检查。真实账户拒绝测试凭据和未来事实。

声明式券商CSV映射使用`mapped-import --mapping ... --file ...`；默认预检，提交需要expected-hash/expected-sequence。示例examples/mappings/test_broker.json及test_broker.csv已经实际验证；同价两笔成交有不同稳定外部ID，不合并。未知行、DST歧义、重复费项和不明确分红税口径阻断。账户页有同一服务的上传/预检/提交表单。

## 成熟引擎验证

隔离工具为`.tools/dotnet` SDK10.0.100及`.tools/lean`固定官方提交80e7843f645673bcbeaab963049f76f20f6785e1。当前完整源码checkout包含engines/lean/LyraX.Options.csproj；fixture-replay会把适配器编译到自己的结果目录，并保存源码、DLL哈希及构建日志，不修改第三方核心。

先导入examples/options/contracts-engine-fixture.json与quotes-engine-fixture.csv，metadata沿用同一合成声明。它们是2024年固定合成样本，日期没有借用未来成交。然后使用导入输出的SNAPSHOT：

```bash
lyra --config config.json options --action fixture-replay --snapshot-id SNAPSHOT --file "$LYRAX_ROOT/examples/options/selection-engine-fixture.json" --engine-root "$LYRAX_ROOT/.tools/lean" --dotnet "$LYRAX_ROOT/.tools/dotnet/dotnet" --destination ./engine-fixture-new --capital 100000 --fee-per-contract 2
```

输出8模板及同一引擎股票/现金基准，检查实际订单、非负现金、完整开平仓与独立期末现金桥接。价格固定，买ask/卖bid，单腿往返−14、双腿−28；结果属于机械验证，不能解释为策略收益/年化。非零滑点、真实历史链、离散行动、提前指派和复杂交割尚未验证。裸Put的全部履约现金和Call覆盖由检查约束；当前适配只支持合成标准100股美式实物合约，其他单位明确阻断。

## 日常维护与看板

```bash
lyra --config config.json doctor --as-of 2024-12-31T21:40:00Z --verify-reports
lyra --config config.json backup-maintenance --directory ./backups --environment demo --action preview --keep 3
lyra --config config.json backup-maintenance --directory ./backups --environment demo --action create --keep 3
lyra --config config.json ui
```

四页有只读今日待办、下一合格月末/日历缺口、当下有效条件及明确下一动作；研究页有情景/定价、归因和滚动结果；计划页展示期权草案及阻断；账户页展示期权持仓/担保及声明式映射；运行页有链与待核实凭据。缺少期权估值报价不把资产记为零。

独立paper工作区通过`paper-summary --file <清单JSON> --as-of <时间>`只读汇总；每项含name/workspace/config/report，顶层schema_version=1、max_age_seconds、workspaces。工作区各自有独立账本，报告必须同一时点且未过期/被新事实修改；不同时间或不完整时不发布合计，不拼接收益率或共享资本。

备份新包验证后才轮换，保护指定ID和刚创建的包，损坏包保留。恢复到新空目录，v5包含期权链/合约/事实/草案引用和来源资格凭据。部署调度、真实行情/账单资格和自然前向周期仍需独立验收。


## 实际合约凭据与模型限制

真实工作区登记合约时，条款的`evidence_hash`必须是实际单位凭据的SHA256，并显式传入`--contract-evidence-file /path/to/reviewed-document`。文件归档到工作区`options/contract-evidence/<hash>`；测试样本的证据标签不能替代该文件。后续导入、估值与完整备份会重新验证；文件丢失或改变时权益显示不完整，不生成有效收益。哈希校验不能认证文档来源，仍须核对实际合约、单位和授权。

选约结果包含`strategy_version`、`rule_source_hash`和相关源码文件指纹。规则名中的monthly表示计划目标频率；当前选约工具本身不强制月末，单次机械回放也不构成月度策略验证。

定价接受`discrete_dividends`，格式为`[{"ex_date":"2026-11-01","amount_per_share":1}]`，必须在估值日至到期之间；使用时连续`dividend_yield`必须为0。离散分红IV暂返回明确未支持原因；跨期压力工具仍按其已支持模型参数计算。


受限环境启动看板时，可加入`--browser.gatherUsageStats false`，防止Streamlit统计模块尝试写入只读用户目录。例如：

```bash
python -m streamlit run /mnt/c/quant/project/lyra/src/personal_quant/ui/app.py --server.address 127.0.0.1 --server.port 8504 --server.headless true --browser.gatherUsageStats false -- --config config.json
```

此命令已在隔离验证工作区运行；`config.json`须指向该工作区配置，8504仅为本次验证端口。


## 期权实际成交进度与待核实凭据

标准期权事件CSV可以明确提供`plan_id`关联同账户的期权草案。只有匹配合约版本、买卖方向和OPEN的成交推进该开仓建议；不按相似价格或日期猜配。实际超额、方向不符或生命周期事件保留事实并显示异常，不能因建议不符丢弃账单。冲销后从有效事件重新计算进度；PARTIAL/FILLED不解锁来源或账户权限。

```bash
lyra --config config.json options --action plan-review --plan-id PLAN_ID --as-of 2026-10-09T21:00:00Z
lyra --config config.json options --action pending-list --account-id ACCOUNT_ID
# 登记缺失的确切合约后，使用上一步原凭据哈希及当前账户序号
lyra --config config.json options --action resolve-pending --account-id ACCOUNT_ID --event-id EVENT_ID --commit --expected-sequence SEQUENCE --expected-hash RECEIPT_HASH
```

plan-review按指定时点只读计算派生进度，不覆盖已保存的当前状态；实际事件导入更新当前进度，页面刷新不执行写操作。resolve-pending仅重试原始凭据，不修改其内容；原凭据、原阻断原因和入账结果保存在任务审计记录中。重复解决返回同一结果。尚不支持的公司行动不能通过此入口强制入账；凭据内容更正仍需专门更正流程。

账户估值的预留读取ETF与期权计划同一资源集合。plan-draft只生成无预留草案；实际期权担保限制现金/证券购买力。当前plan-activate支持A8合成历史demo，paper/real另需同账户实时冻结的前向月度信号、真实来源/合约、操作权限、引擎、对账和当前报价通过后才建立READY预留；没有券商自动下单。


## 记录已提交的人工订单（不下单）

`options --action manual-record --file manual-fact.json --commit`记录已发生的人工执行事实。JSON必填`request_id`、`plan_id`、`action`、`as_of`、`expected_sequence`、`reason`、`orders`。动作record-submitted的orders逐腿包含contract_id/side/contracts/limit_price/fee_per_contract；动作confirm-ended和cancel的orders必须为空。request_id重跑幂等，同ID不同内容报错。

这是记录用户已经提交的订单，不是READY资格或下单授权。买入预留未成交数量的参考金额及费用，卖Put预留全部履约现金，卖Call保守占用覆盖证券；不预先计入卖出权利金或未成交保护腿。明确关联的成交只把已完成部分从预留转到真实现金/应付/期权担保，不重复扣权益。限价/费用是用户录入的预留依据，不保证实际成交；偏离和不足仍须核对。

已有在途订单不能被新通知或草案修订覆盖。必须先confirm-ended明确核实券商已无剩余订单，才可cancel关闭未完成建议；本地动作不等于券商撤单。已全部成交的计划不能取消事实。原提交/结束审计支持历史时点预留重建；实际成交可晚到，不因本地关闭丢失。前向READY是人工建议，不代表券商订单或自动模拟成交。


## LEAN行权/指派扩展验证

在合成2024引擎链的fixture-replay命令追加`--include-exercise`，运行原8模板及股票/现金基准，再运行保护Put明确行权、备兑Call官方模型指派，共12例。样本新增标准100股Put价内行权与Call指派的实际引擎事件；`engine-events.json`保存成交/交割，`ledger-bridge.json`保存隔离demo账本重放结果。交割证券事件由对应期权生命周期事件统一表示，不重复写一笔普通买卖或内在价值现金。

固定手算：初始100000，100股按100买入；K95 Put按1.1买入，成交费2，行权/交割费假设0，最终现金99388（盈亏−612）。备兑Call K105按1卖出、成交费2，被指派后现金100598（盈亏598）。这是两个合成分支，不是实际期权收益证据。

指派采用官方DefaultOptionAssignmentModel，工程样例显式设置到期前10日期限，仍使用官方价内/套利判断；不声称实际指派概率。成交费与行权费用分开：样例行权/交割费0，不能将每张成交费重复套到行权及证券交割两条事件。尚未验证非零行权费用、CSP指派、无价值到期、分红/多腿部分指派及月度调度。

扩展会在报告目录建立隔离测试账本；`no_user_account_writes=true`表示不改用户工作区账户，不能把`no_account_writes`写成true。期权READY仍保持门禁。


### 生命周期扩展补充：CSP与无价值到期

`--include-exercise`现在运行14例：原10个比较场景，加保护Put行权、备兑Call指派、现金担保Put指派、Long Put无价值到期。CSP K95收权利金100、成交费2，被指派后现金90598、100股按85估值为8500，权益99098；不能把仍持有股票当成现金或再扣一份内在价值。Long Put K100按2.1买入、成交费2，无价值到期后现金99788、无股票/期权。

无价值到期由LEAN到期处理产生事件，不伪造一次卖出。生命周期场景使用各自冻结的数据目录，`data-files.json`及报告里的哈希可核对；后一个价格冲击不会改写前一个场景。控制组A8与股票/现金仍共用同一评估区间，生命周期诊断有独立结束时点，不混作公平收益比较。分红行动、多腿部分指派、非零行权费、月度调度仍待验证。

### 多腿指派验证补充（2026-10-11）

引擎回归扩展至15例，新增牛市Call价差短腿提前指派。收盘后不强制模拟长腿即时行权；按合成规则等待下一交易日开市报价，再提交保护腿行权。报告ledger-lifecycle-path.json保存指派后的100股股票空头及恢复后的零持仓。临时空头在统一账本中保留异常、阻断新计划；缺少当时的期权估值时权益不完整。最终现金100386不代表隔夜无风险。其余多腿路径、分红及月度调度仍待验证；15例CLI归档及最终全量验收尚待。以上补充取代此前段落将所有多腿部分指派列为未验证的表述。

### 月度研究冻结入口（尚未贯通执行）

```bash
lyrax --config configs/demo.toml options --action monthly-freeze \
  --file <选约请求.json> --snapshot-id <链快照ID> \
  --scope <独立研究范围> --publication-delay-minutes 30
```

请求格式与select相同，但decision_at必须为月末实际收盘加指定发布延迟，提前收盘也按日历处理。稳定信号保存在runtime/demo/options/monthly；重跑读取原结果，修改输入需显式处理既有意图，不覆盖。历史重建和不可执行标签保留。归档已纳入统一备份恢复及引用核验，月度执行任务仍待贯通。已验证命令记录见docs/PROGRESS.md。

### 收盘成交机械验证

在原fixture-replay命令增加`--market-on-close`（不与`--include-exercise`同时使用）。在交易日实际收盘前20分钟提交订单，由LEAN MOC处理到收盘才成交；测试收盘报价比提交报价高0.2，程序核对买ask/卖bid、全部开平仓次数及实际收盘时间。该入口仍是固定合成行情的10例诊断，不是月度历史策略收益或前向运行证据。早先15:46提交不满足官方15分30秒门槛，失败日志保留，未缩短官方门槛。

### 连续月度机械回放（研究验证）

```bash
lyrax --config configs/demo.toml options --action monthly-replay \
  --file <冻结月度信号数组.json> --engine-root .tools/lean \
  --dotnet .tools/dotnet/dotnet --destination <新的报告目录> \
  --capital 100000 --fee-per-contract 2
```

输入至少两份同一scope/模板/标的的monthly-freeze结果，严格按决策时间递增，仅合成标准100股美式合约、每腿1张、固定标的100适用。旧组合先平仓，新增风险等待工程T+1；使用同一资本，不逐月重置。引擎事件、冻结信号、执行数据及哈希、统一账本逐批快照/最终结算和重复导入核对保存在报告目录。报告内bridge.sqlite为隔离demo验证账本，不写用户工作区账户。固定价格诊断不代表真实策略收益，READY/真实前向任务尚待。

### 月度模板与股票/现金控制组比较

```bash
lyrax --config configs/demo.toml options --action monthly-compare \
  --file <冻结月度信号数组.json> --engine-root .tools/lean \
  --dotnet .tools/dotnet/dotnet \
  --destination runtime/demo/options/monthly-research/<新运行ID> \
  --capital 100000 --fee-per-contract 2 --stock-commission-bps 2
```

显式股票bps与期权每张费用应用于所有组合，控制组为每期100股加剩余现金/全现金，不代表全仓SPY基准。报告包含equity.csv、drawdowns.csv、transactions.csv、metrics.json、中文report.md及冻结输入/引擎/账本归档。净值逐日核对引擎和统一账本，初始资金基线保留首日成本；午夜图表日蜡烛归属前一日，旧schema1报告明确拒绝。价差成本只解释已经计入ask/bid成交的损耗，不再次扣减。

上述目录的报告可在策略研究页只读查看，并随完整备份恢复。所有结果为合成机械研究；没有真实历史期权或前向证据，也不解除READY资格。具体已执行CLI记录见PROGRESS。

### 未成交资源预算预览

`options --action plan-review --plan-id <ID> --as-of <带时区时间>`现在显示reservation_preview。预算按已明确关联的有效成交计算剩余权利金/费用和履约资源，实际已成交担保由统一账本负责，不能把收到的权利金当成利润或未来可用资金。`applied=false`表示这只是审阅预览：不新增预留，不授予READY，不代表券商订单。已有人工在途订单仍按持久化订单占用处理，不能用该预览释放资源。

### 按模板审计成熟引擎生命周期证据

```bash
lyra --config configs/demo.toml options --action engine-assess \
  --file <fixture-replay输出目录>/verification.json \
  --template-id cash_secured_put
```

审计逐模板检查必需的开平仓、行权/指派/到期分支，以及当前适配源码、SDK/LEAN版本、程序集、冻结执行文件、引擎终态和统一账本桥接。缺少某一分支或证据改变会BLOCKED，不能按案例总数自动放行。PASSED仅表示合成引擎生命周期这一单项；executable和source_qualified仍为false，月度规则、当前报价、账本/资金、对账及权限检查独立保留。审计输出包含规则版本及源码hash，不生成订单或写入账户。

`--include-exercise`扩展至16例，新增现金担保Put无价值到期：收权利金100、成交费2，期末现金/权益100098，期权和担保归零；用官方到期事件释放义务，不重复记现金或制造平仓交易。备兑Call等模板缺少的分支仍明确显示，不以该新增分支替代。

2026-10-11后续扩展现20例：增加备兑Call、保护Put、Long Call无价值到期及资金充足Long Call行权。无价值到期仅清除合约义务，不制造平仓买卖；备兑/保护策略原有100股保留，Long Call行权支付完整行权资金并取得100股，交割不重复入账。工程费用仍成交2/张、行权/交割0，不代表券商费率。CSP、备兑Call、保护Put和Long Call的逐模板引擎审计可通过；来源/前向/账户权限及计划激活仍独立检查，当前plan-activate只开放合成demo CSP。

最新扩展为24例，增加collar/牛Call价差/熊Put价差逐腿无价值到期及Long Put价内卖出退出。每条到期腿按冻结合约标明LONG或SHORT，清除对应义务；价内普通卖出记录OPEN→CLOSE，不冒充行权。Long Put和牛Call价差逐模板工程审计现可通过；collar与熊Put价差仍缺指派/行权分支，保持BLOCKED。无价值到期矩阵按模板实际腿数检查官方事件数量及身份，不以一个腿的到期替代整组完成。此报告仍不授予真实来源资格或新模板READY。

最新27例已补collar Call指派、Put行权及熊Put部分指派恢复，八个A组模板的engine-assess单项均可PASSED。collar行权前先关闭短Call；熊Put指派取得股票后等待下一交易日同步报价再行权，阶段现金/股票/缺价状态均归档。这里只证明标准100股美式合成样本的必需工程分支，实际指派概率、离散分红和未知调整条款独立保留。当前plan-activate/plan-simulate支持A8八模板的合成demo开仓，账户资源和同步报价检查独立保留；完整日常平仓/生命周期任务仍未验收。旧引擎源码对应的证据不得直接用于新版本激活或模拟，历史归档不覆盖。

### A8合成历史演示计划激活

```bash
lyra --config configs/demo.toml options --action plan-activate \
  --file activation-request.json --commit
```

请求需明确全部字段：request_id、plan_id、as_of、valid_until、expected_sequence、monthly_signal（完整monthly-freeze输出）、engine_evidence_file（当前源码对应27例verification.json路径）、quote_snapshot_id及reconciliation_max_days。账户必须已显式启用v5、导入合成入金及通过同口径对账；月度信号选约须与草案完全一致。执行日为下一交易日，期限为该日实际收盘；激活不晚于收盘前20分钟。当前报价必须已到达、单位一致且通过选约参数的时效/价差检查，不能用月末旧报价代替执行日报价。

当前允许demo且数据标注synthetic的A8八模板。备兑Call、保护Put及领口必须已有足额股票，不隐式代买股票；多腿报价还检查时间同步及标的价格一致性。引擎证据按模板独立审计，并校验后原子冻结到工作区options/engine-evidence；账户检查和READY资源预留在同一事务中保存。同请求重跑返回原审计；同一意图已READY/PARTIAL/FILLED时，新修订不能再次激活。paper/real始终保留来源、权限和前向信号门禁，不能因本入口通过获得执行授权。

两张95行权价CSP的固定验证预算为19014美元（履约19000、成交费4、显式缓冲/额外预留10）。明确关联一张成交后，剩余计划9512与实际担保9500合计19012；全部成交后只有实际担保19000。预留不扣权益、不预支卖出权利金。账户未关联变化、对账差异或未核实期权凭据阻断继续执行；过期且没有在途人工订单时关闭未执行预留，在途占用必须确认结束才释放。历史查询按激活/人工审计恢复当时状态，不能把未来预留倒灌过去。

此入口建立演示建议及审计，不提交订单。成熟引擎归档的演示成交可通过下节独立任务导入；完整日常任务、退出及生命周期闭环仍需继续实现和验收。

激活后入金或出金会关闭未提交部分，CANCELLED不撤销既有成交。若已有人工在途订单，intent_closure显示WAITING_MANUAL_CONFIRMATION并仅保留实际订单剩余资源；确认无剩余订单后关闭。资金冲销、更改张数/风险或建立新修订都不重启同一旧信号，新增资金等待下次合格月末。历史查询按资金生效时点及账本序号保留当时占用，后来的人工结束通知不会倒改旧版本。

### 导入成熟引擎的A8演示成交批次

```bash
lyra --config configs/demo.toml options --action plan-simulate \
  --file simulation-request.json --commit
```

请求字段固定为plan_id、report_id、execution_snapshot_id、as_of及expected_sequence。report_id是工作区options/monthly-research下由monthly-compare生成的schema2报告目录名；不接受任意外部路径或用户自行填入成交价。execution_snapshot_id须是明确synthetic、实际收盘时点且截至as_of已到达的确切合约报价。as_of不得早于成交收盘；晚处理保留delayed_processing，不补造前向运行证据。

任务重新核验激活资格、当前账户/对账及人工订单、完整报告哈希/逐日净值、当前适配源码与程序集、冻结信号身份、实际MarketOnClose事件的单位/方向/数量/价格/费用和报价数量。只取该信号的OPEN事件，不导入报告后续月份或平仓事件。数量不能超过事前剩余计划，超出费用或价格偏离参数、缺价或资金异常均阻断；事件及任务审计在同一事务写入。同计划批次相同请求重跑不新增成交，换输入会冲突。

仅合成demo A8适用。备兑Call、保护Put及领口使用账户已有股票；研究从现金构造100股的买入事件及其费用不重复导入，审计中保留research_underlying_events_not_imported。当前机械引擎收盘标的价格固定100，其他价格明确阻断，不能将此入口当成任意历史行情模拟。结算使用市场日历的下一交易日收盘（T+1工程假设），不固定UTC时刻。报告当前每腿1张，可导入一张实际引擎成交，不能为填满更大的计划按比例伪造数量。完整模拟生命周期、日常调度、真实报价和自然前向仍需继续开发/取得条件。

### 分开查看开仓完成与持仓生命周期

plan-review新增lifecycle。execution_status的FILLED表示建议开仓张数已成交；之后正常平仓、行权、指派或到期不会将其倒改为未完成。lifecycle.status表示当前持仓及结算阶段，position_status单独显示OPEN/PARTIAL_CLOSE/CLOSED，pending_settlements保留逐事件结算依据。退出只能消耗本计划明确关联的开仓，不自动按日期/报价匹配其他账户持仓；超量或错误关联需对账，实际凭据仍保留。

没有到期凭据时，即使超过截止日也不自动释放义务；REVERSAL后从有效事件重新计算。历史as_of与账本序号隔离未来事实。此为账户事实审阅，尚不是事前退出建议或完整日常生命周期模拟任务。

### 到期窗口或风险减仓的只读退出检查

```bash
lyra --config configs/demo.toml options --action exit-review --file exit-request.json
```

完整请求字段：plan_id、as_of、snapshot_id、trigger（EXPIRY_WINDOW或RISK_REDUCTION）、exit_days、fee_per_contract、max_age_seconds、max_underlying_skew_seconds、max_spread_fraction、max_leg_skew_seconds、max_underlying_price_fraction及reconciliation_max_days。示例退出窗口7自然日是工程规则，不替用户确定真实风险参数。

窗口日期若非交易日，提前到前一市场交易日；尊重半日市和合约最后交易期限，在收市前20分钟进入检查。NOT_DUE/NO_POSITION不制造交易。建议只针对本计划实际剩余张数，按bid/ask、数量及已到达时间检查；多腿检查同步及标的价格一致，短腿先关闭，保护长腿列出depends_on，不预支保护腿卖款。

短腿回补资金可计入“完成对应平仓事实后”本计划担保的条件释放；其他持仓及计划占用保留，账本担保不提前改变。所有结果含规则源码hash和稳定management_id。检查通过仍executable=false、execution_status=DRAFT；该入口不接受commit，不记成交、不撤单、不自动滚仓，也不代替后续退出激活/成交/生命周期任务。真实账户仍保留来源和账户权限门禁。

### 冻结与执行合成演示退出任务

```bash
lyra --config configs/demo.toml options --action exit-freeze --file exit-freeze.json
lyra --config configs/demo.toml options --action exit-freeze --file exit-freeze.json \
  --commit --expected-hash <上一步preview_hash>
lyra --config configs/demo.toml options --action exit-simulate --file exit-simulate.json --commit
lyra --config configs/demo.toml options --action exit-cancel --file exit-cancel.json --commit
```

冻结请求字段为request_id、review（上节完整只读请求）、execution_at、purpose及expected_sequence。用途分别为EXPIRY_MANAGEMENT、OBLIGATION_CLOSE或PROTECTION_WITHDRAWAL；卖掉保护Put需明确使用PROTECTION_WITHDRAWAL，不能据此声称整体风险下降。到期管理需对应EXPIRY_WINDOW检查。决策必须不晚于所选当前或下一市场交易日收盘前20分钟，执行不得超过最后交易时点。

冻结不记成交、不提前释放担保。pending_option_exits单独标识未完成意图，阻断新增股票及期权计划，不当作现金/持仓对账差异。账户序号和现金、持仓、计划、人工状态的资源指纹共同保护执行；没有新成交的资源变化同样使旧冻结失效，需要取消并重新预检。

模拟请求字段为exit_id、report_id、execution_snapshot_id、as_of及expected_sequence。仅隔离demo，必须引用本计划实际模拟开仓的同一monthly-compare归档及确切CLOSE事件；逐腿核对已到达的收盘报价、方向、数量、费用和短腿先关闭依赖。当前引擎固定标的100、每腿1张的限制继续保留。只导入实际期权平仓，研究报告为组合清算而生成的股票卖出不进入个人账本，基础股票继续持有。失败整批回滚，相同请求重跑不新增事实，换输入冲突；T+1按市场日历结算。

取消请求字段为exit_id、as_of、expected_sequence及reason。仅关闭未执行退出意图，不取消实际成交、不释放实际持仓担保；已经模拟平仓的事实不可取消。历史查询保留取消之前的意图与成交之前的持仓。完整备份保存冻结、取消、模拟审计及确切报价/引擎归档引用。当前批次回归与CLI证据以PROGRESS终态记录为准；此入口不替代官方到期/行权/指派任务、日常发布、H组或最终交付验收。

冻结模拟允许迟到处理，但保留原成交时间与实际处理时间：执行报价的时效按冻结收盘核对，报价收到时间按as_of核对，不能将未来价格或尚未收到的报价带入。单次实时决策、选约和退出预检仍使用严格的同一知识时点，不因该模拟能力提前获知报价。

### 账户期权估值与日常对账报告

```bash
lyra --config configs/demo.toml options --action account-report --file account-valuation.json
lyra --config configs/demo.toml daily --account-id sample --as-of <demo历史处理时点> \
  --option-valuation option-marks.json --reconciliation independent-snapshot.json
```

account-valuation.json字段为account_id、as_of及option_valuation；后者仅含snapshot_id和limits。option-marks.json只保存该内层对象。演示填写模板为templates/demo-option-valuation.json，必须替换快照ID并选择真实适用的账户/时点；示例阈值属于工程假设。limits必须明确max_age_seconds、max_underlying_skew_seconds、max_spread_fraction和max_leg_skew_seconds。真实/前向daily不接受手工历史时钟。

估值按截至时点已收到的实际bid/ask中价记录“每报价单位价格”，账本再按实际张数、冻结乘数和空头符号计算市值。权利金现金与负债同时体现，担保不再次扣权益；入金只增加累计投入。参考中价不等于可成交价格。缺报价、过期、单位版本冲突、过宽价差、不同步或来源不合格时，权益保持不完整，缺价不记零。期权账户缺少显式报价请求时不标为CASH_ONLY。

报告保存在工作区reports/account-latest及versions，引用确切报价快照与来源核验身份；完整备份验证这些引用。daily新增期权估值阶段并用同一价格口径核对独立账户快照。即使期权估值/对账通过，股票策略数据及交易条件仍独立检查；缺项时任务保持BLOCKED。当前本入口贯通估值、对账和报告，官方生命周期模拟任务及组合对冲规划另按PROGRESS继续。

### 期权报价来源核验登记

```bash
lyra --config configs/demo.toml options --action source-register \
  --file option-source-review.json --destination source-evidence --commit
```

独立schema_version=2、asset_type=OPTION_QUOTES，OPRA/USD/America/New_York、price_basis=premium_per_quote_unit；不能用股票原价资格、CSV标签或引擎案例代替。series_id由personal_quant.options.source.series_id(source)计算。必须提供source、scope_contract_versions（确切版本哈希数组）、quote_convention、time_convention、corporate_actions、license_terms、reviewed_at、valid_until、decision、reviewer、reason、evidence_type及evidence_files（相对文件名到SHA256）。凭据沿用统一不可变归档机制。

真实报价估值需QUALIFIED、actual核验凭据、范围覆盖、有效期、未改变的归档文件，以及每个实际合约的单位证明。paper/real还检查核验记录在估值时点已被系统收到；后来的核验不能回填过去。test核验只允许demo保存，不能授予真实来源资格；合成报价只允许demo估值，并在报告和看板明确标注。登记表示记录核验结论，不自动获取供应商数据、购买许可或授予账户期权权限。本批以测试凭据验证接口，真实期权来源仍未接入验证。

### 日常推进事前冻结的期权模拟任务

仅隔离demo可显式传入冻结任务数组；kind为OPEN或CLOSE，request分别为既有simulate或exit-simulate完整请求。不得传入策略参数替代冻结计划，不会生成新的决策或券商订单。请求as_of必须与daily处理时点相同，任务必须属于指定账户。

```bash
lyra --config configs/demo.toml daily --account-id sample --as-of <demo处理时点> \
  --option-tasks frozen-tasks.json --option-valuation option-marks.json
```

daily在账单导入后、股票模拟推进前执行这些任务。执行失败停止后续期权任务和本次股票推进，保留已提交事实与具体原因。每笔成交及原生审计原子提交；日常步骤另行记录。两者之间中断时重跑复用原生审计，不重复记账；步骤已提交则复用步骤。临时失败恢复后保留原原因并标RECOVERED。缺少股票信号数据仍返回BLOCKED/退出码3，即使期权任务成功。

有凭据的到期、行权、指派任务自动编排和组合对冲仍在后续批次，不将OPEN/CLOSE推进称为完整生命周期支持。

本批实际验证：34项回归无跳过通过；OPEN/CLOSE各错误时点、执行、重复共6条CLI检查通过，证据reports/v19-implementation/option-daily-cli-20261011/verification.json。开发复现可先运行tests/test_options_daily_v19.py取得隔离fixture，再执行scripts/verify_option_daily.py --base <daily-option-base0> --destination <新证据目录>；该脚本只复制合成冻结样本，输出原命令、退出码、源码指纹、账本序号，不接入真实账户。

### 日常导入生命周期事实及解决待核实凭据

```bash
lyra --config configs/demo.toml daily --account-id sample --as-of <demo处理时点> \
  --option-receipts receipts.json --option-resolutions resolutions.json
```

receipts.json仅含request_id、rows、expected_sequence、expected_hash。rows是标准期权事件数组；expected_hash是规范化数组digest，与options import-facts预检所用口径一致，不是CSV文件字节哈希。request_id应由凭据批次稳定确定；同ID不能更换内容或预检依据。实际生效时点必须已到达，真实账户只接受actual凭据和核验过的实际合约单位证明；demo仍使用明确test标签。尚未升级v1.9时拒绝提交。

resolutions.json是数组，每项仅含event_id、expected_sequence和expected_hash；最后一项取pending-list返回的receipt_hash。条款或明确关系补齐后才可解决原始凭据，不能修改原始事实绕过核验。每次解决按当前账户序号审阅；多项顺序提交时后项序号应包含前项新增事实。原凭据及解决审计保留，重跑不会重新增加已解决事实或复活待核实记录。

日常顺序为普通账单导入→明确期权凭据和解决→冻结模拟成交→估值/对账/计划/报告。存在待核实凭据或处理错误时，停止本次后续模拟，但保留已经提交的事实和错误原因。批次原始审计与daily步骤独立提交，两个边界中断均可重跑恢复；备份核验二者对应。到期、行权、指派、现金结算仍必须由明确凭据提供，不根据日历自动生成通知。示例验证脚本scripts/verify_option_receipts.py只在新建隔离demo中生成测试账单，不代表券商数据或真实策略表现。

本批验证：54项凭据/账本/估值回归及7项冻结模拟daily兼容回归无跳过通过；9条实际CLI检查通过，记录reports/v19-implementation/option-receipts-cli-20261011/verification.json。复现脚本使用新目录：`python scripts/verify_option_receipts.py --destination reports/option-receipts-check-new`；目录已存在时拒绝覆盖。

## 对冲风险快照：只读Beta/Delta入口

```bash
lyra --config configs/demo.toml hedge-exposure --account-id sample --file hedge-risk.json > exposure.json
```

模板templates/demo-hedge-exposure.json需替换两个不可变行情快照ID、时点及账本序号。valuation_snapshot_id必须支持核验原价，return_snapshot_id使用日简单总收益的adj_close，只用于风险估计。共同完整窗口126个收益要求127个价格；缺失/尚未可用/零成交量不补齐，基准零方差及R²/标准误门槛不足显示INCOMPLETE。工程模板阈值不是实际风险偏好。

ledger_view=known_then校验该账本前缀的凭据在knowledge_cutoff已被记录；后来补录旧生效日不能改写当时所知风险。restated仅开放demo，明确当前重述视图。knowledge_cutoff不得晚于as_of，不能使用未来风险时点。实际账户使用真实行情、合格原价凭据及其当时已收到的核验记录，不能用后来登记的资格回填。

Greek每项需contract_version、unit(per_share/per_contract/position_total)、value、signed_contracts、source、data_type(provider/model/synthetic)、as_of、available_at、received_at及model_inputs。确切版本和有符号实际张数一致；整份持仓Delta不再乘100或张数。供应商逐笔观察值可增加qualification_id绑定已归档原始资料和核验结论；无凭据或测试凭据的实际账户新增OPEN仍阻断。模型Greek现支持独立输入凭据和已锁QuantLib重算资格；必须完整输入、确切合约及position_total，输入时点/原始文件/源码/版本和冻结标的原价一致。详见[模型Delta接口](V19-MODEL-GREEK.md)。理论输出不等于可成交报价，真实输入/权限仍须独立验证。max_greek_age_seconds检查已知时点的时效，max_mark_skew_seconds单独检查与标的实际价格时点的偏差，不能把行情发布延迟误作价格时差。

已有期权还需option_valuation快照/limits，缺价或Greek不把风险记为零。历史期权估值显式使用ledger_seq对应的持仓和条款；后来平仓或更正不被借入该前缀。知识截止、报价时效、合约单位和来源核验仍独立检查。净名义额0不等于Beta0；期权Beta金额由已归一有符号Delta股数×原价×标的Beta计算。入金不改变历史资产收益，只会改变全账户权益及风险比例的分母。

此入口成功和失败都不新增事件、计划、预留或任务记录；exposure_id绑定数据/参数/源码及账户依据，JSON可显式归档。它不生成候选数量或可执行计划，H0完整证券/目标/分配契约、H2–H5及统一存储/看板尚待。支持目录与进度以H计划/PROGRESS为准，不把只读风险计算称为对冲执行支持。

### 风险归档与完整恢复

```bash
lyra --config configs/demo.toml hedge-exposure --account-id sample --file hedge-risk.json --archive
```

归档保存到工作区hedging/exposures/<exposure_id>/，包括完整风险输入、账户/账本前缀哈希、参数、数据引用、模型结果和源码指纹。文件先暂存，再原子发布；重复相同内容复用原目录，篡改或链接拒绝读取。归档只冻结风险，不预留现金/股份、不新增计划或记账。后来入金/成交/冲销不会覆盖旧归档；新的依据形成新内容身份。

完整备份现在包含hedging目录，并验证引用的确切原价/收益/期权快照、账户环境与原账本前缀。恢复后可按原exposure_id读取历史风险，不强制用当前源码重算覆盖历史。后续可执行候选必须重新检查当前来源、资源及账户条件，不能把旧档案当作现在可交易资格。统一对冲目标/候选/保护分配和看板继续按H计划实施。

## H2股票减持/反向ETF条件候选

```bash
lyra --config configs/demo.toml hedge-preview --account-id sample --file hedge-preview.json
```

请求仅含exposure_id、spec、method、proxy、funding_quote。exposure_id必须是同账户已归档风险；spec为templates/demo-hedge-spec.json的完整显式目标，不能缺资金/费用/容差字段。scope仅限定允许调整持仓，target_beta分母始终为全账户权益。股票请求支持reduce_stock和inverse_etf；Put/Collar/代理Put使用下面H2期权请求格式。目录白名单不授予执行资格。

proxy及funding_quote需symbol、execution_price、market_price、beta、trade_unit、product_type(stock/etf/inverse_etf)和product_evidence说明。候选market_price/Beta必须匹配归档报价和CHECKED模型。未持有代理时，创建风险请求可显式增加proxy_symbols，使该证券加入相同完整日期窗口与原价检查；不能在候选请求自行改Beta或估值价。产品说明仅声明性研究输入，不替代核验证据；反向ETF不是根据名称自动设Beta=-1。

目标Beta模式按明确max_trade_units（最多10000）确定性枚举整单位，误差相同按费用/成交名义额/稳定数量排序。先重算已获准的基础减持、费用和成交价差对B_post/E_post的影响，再选数量；新增交易数量与交易后持仓分开展示。股票卖出不超过未占用持仓，超出所需的空头不交给只做多执行器。借款、工资未来入金和未结算卖款不作为当前购买力。

funding=cash_only只用当前可用现金；sell_scope还必须明确funding_symbol及对应冻结报价，该证券属于scope。max_cash限制使用现有可用现金的额度，额度之外的现金保留；max_notional在此批限制买卖及筹资交易名义额绝对值之和。每笔交易扣commission_bps和fixed_trade_fee；完整成交后E_post只扣摩擦，不把现金换成证券再算亏损。筹资卖出/结算/重新报价检查作为依赖显示，预览不是已经到账，也不生成计划或预留。

无法在现金/持仓/预算和残余Beta容差内实现目标时返回NO_FEASIBLE_HEDGE并保留原因；已有目标无需调整返回KEEP。所有候选executable=false，必须继续完成单位/产品资格、统一父意图/资源检查、真实报价和分阶段成交/结算才能成为可执行建议。本入口成功/失败不新增账本或任务记录。工程模板参数不是实际用户风险选择。

## H2期权条件数量候选（2026-10-11）

继续使用只读 hedge-preview。股票请求保持原字段；期权请求严格包含 exposure_id、spec、method 和 option，method 支持 protective_put、collar、proxy_put。option 必须包含 snapshot_id、selection_request、coverage_request、greeks、limits、funding_quote。复用 A8 选约规则和原期权链快照；不在本入口重新搜索参数。

selection_request 沿用选约接口，决策时点与风险快照一致，DTE/到期前退出天数匹配 HedgeSpec。coverage_request 沿用账本覆盖接口，但 allocations 必须等于持久保护引用的完整最新集合。没有引用审计时只能为空；未关联实际 Put、未列出的人工在途保护会要求先核对，不能自行填写保护股数。账户现金、持股和当前资源占用来自同一账本，归档现金不能绕过新预留。

limits 严格包含 adverse_slippage_fraction、early_assignment_cash_reserve、max_greek_age_seconds、max_mark_skew_seconds、proxy_exit_policy、failed_exit_policy；全部显式提供。代理 Put 必须指定 sell_before_expiry 与 block_and_require_verified_resolution；这只是约束，退出/生命周期任务尚待贯通，不能据此宣称到期安全。

share_protection 对同标的 Put/Collar 计算整张目标，扣除实际及在途保护，展示零碎股数和剩余目标。Collar 每组 Put/Call 覆盖同一份股份，未配对腿先恢复；已有保护窗口不足要求滚动复核。beta_target 支持三种期权方法：逐腿有符号 Delta 先统一为整份股数，再结合冻结原价、同基准 Beta 与筹资卖出重算 B_post/E_post。缺 Greek 或模型依据返回明确阻断，不填默认 IV。持股保护和局部 Beta 是不同目标，代理保护不提供篮子到期收益底线。

greeks 每项包含 contract_version、unit、value、signed_contracts、source、data_type、as_of、available_at、received_at、model_inputs。支持 per_share/per_contract/position_total，不重复乘合约单位；短 Call 的 signed_contracts=-1。引用的合约版本、时点和知识截止需一致。直接保护的新增张数受实际未占用股份限制；在途 Beta 保护需先核对，不能按新报价猜测其最终成本。

筹资按买入 Put 的总权利金、全部逐腿费用及提前指派现金预留计算，不能提前使用未成交 Call 收款。max_premium 检查总买入权利金及费用，max_notional 检查全部期权腿与筹资卖出的名义额；max_contracts 限制已有/在途/新增的总包数。筹资只能用获准范围的冻结报价，不能卖掉受保护股份筹资。预计成交采用买 ask/卖 bid 和显式不利滑点；E_post 按中间价估值扣价差/滑点/费用，不把买入权利金全当亏损。卖出资金须成交、结算、重新报价检查后才能买入。

候选始终 executable=false，不新增事件、预留或任务。父意图可冻结该研究候选；完整备份会核对并恢复其原期权链。实际来源资格、父执行组、统一计划和完整生命周期仍独立检查。

已验证的合成 CLI 样例（destination 必须不存在）：

    python scripts/verify_hedge_option_preview.py --workspace reports/v19-implementation/hedge-preview-cli-20261011-final --destination reports/my-option-hedge-check

该脚本核对 Put/重复/Collar/代理 Put/缺 Greek/直接 Put Beta/Collar Beta，保留请求、输出和验证清单；不使用真实账单，不代表真实期权数据接入或自然前向绩效。

## H2账户与候选统一情景

只读入口：

    python -m personal_quant.cli --config configs/demo.toml hedge-stress --account-id sample --file hedge-stress.json

请求严格为 preview_request、scenarios、models。preview_request 使用上节候选接口；只有 SELECTED_FOR_RESEARCH 或 KEEP 可以作为条件完成后的比较，不把待成交/不可行方案假装已经完成。成功和失败均不新增任务、事件或预留，重跑内容一致。

每个情景明确 name、horizon_date、benchmark_return、beta_multiplier、residual_returns、volatility_multiplier。name 唯一；residual_returns 必须逐项覆盖当前/条件完成后股票及所有期权标的。情景价格为冻结原价乘以 (1 + Beta × benchmark_return × beta_multiplier + residual_return)。Beta 必须来自冻结 CHECKED 模型。beta_multiplier 是用户指定的相关性失效敏感度假设，不是系统估计的相关系数。上涨/下跌、零冲击、IV变化、时间推进和代理失效均可独立列情景。

models 按实际及新增期权的确切 contract_version 提供 volatility、rate、dividend_yield，不默认缺失IV/股息/利率。行权方式、单位和到期来自原合约。全部期权复用 QuantLib；压力时点不跨过任何未经观测的合约到期路径，到期仅计算给定价格的内在价值，不写行权/交割。单次最多300情景且合约×情景最多1500，避免无界模型计算。

unhedged 表示冻结实际账户（包括已有所有期权），不是去掉旧保护；candidate 是在同一账户上条件完成新增交易。卖出筹资现金保留、费用/价差已包含在候选 E_post。期权用同一模型的情景价值减初始理论价值计算变化，以冻结权益为锚；不以理论价替换观察到的市场初始报价，也不重复扣保费。新增入金只增加权益，不成为情景投资盈利。已有短 Call 依真实有符号数量参与两侧比较。

输出逐情景股票/期权变化、初始摩擦、两侧权益/盈亏、保护差额和有限网格最差损失。maximum_loss 固定为 NOT_INFERRED_FROM_FINITE_GRID，不声称最大亏损、实际绩效或代理到期底线。现金和应收应付保持冻结；期间利息/现金分红、提前指派/结算需独立路径证据，反向ETF条件终点也不能替代其逐日复利路径。该入口是H2理论压力，H3官方引擎和同资本历史研究仍待。

合成工作区实际CLI核对（destination必须不存在）：

    python scripts/verify_hedge_stress.py --workspace reports/v19-implementation/hedge-option-preview-cli-20261011-beta --destination reports/my-stress-check

保留请求、输出和验证清单；Put/重复/Collar/缺模型均检查账户不变。完整历史研究、多阶段执行和生命周期不以此理论情景代替。

## H3变化价格、股票篮子与多张数的机械回放

monthly-replay 保留原冻结信号数组输入。扩展文件为严格四字段对象：signals、packages、stock_basket、execution_path。packages 是每个周期的正整数包数（1–100），乘以冻结模板的逐腿有符号数量；同标的保护/Collar/备兑Call对应100股×包数。stock_basket 为其他股票代码到每周期正整数持股数，不重复包含主标的。股票空头和实际数据仍不在此机械入口内。

execution_path 严格包含 schema_version=1、data_type=synthetic、stocks、options。stocks 按股票代码/完整评估交易日给出正原价；options 按冻结合约ID/上市且已取得报价的完整交易日给出正bid和ask，ask不小于bid。缺少或多出日线、未知合约、超出万分价格精度均拒绝，不自动填充。每个交易日的提交前和收盘两采样点采用该日同价，是明确工程假设；不是实际盘中报价或真实期权历史。

LEAN负责成交与资金；独立核对使用各周期实际入场/退出端点、全部股份/整张数量、bid/ask方向和逐笔费用，不再假定价格恒100。旧A8仍使用原固定样例。新篮子及数量必须提供显式路径，不能继承演示价。引擎事件进入隔离bridge.sqlite，重复导入不增加事件；逐日权益与官方引擎净值核对，T+1等待维持演示假设。

固定离线样例 examples/options/monthly-variable-path.json（约14KB）包含两期保护Put、SPY份数200/300、IEF各50股及47交易日变化价格。可在已安装锁定LEAN/.NET环境直接复现：

    python scripts/verify_monthly_path.py --workspace reports/my-monthly-path --engine-root .tools/lean --dotnet .tools/dotnet/dotnet

workspace 使用不存在的目录，脚本复制固定样例与demo配置并实际运行：

    python -m personal_quant.cli --config configs/demo.toml options --action monthly-replay --file examples/options/monthly-variable-path.json --engine-root .tools/lean --dotnet .tools/dotnet/dotnet --destination reports/my-path-engine --capital 100000 --fee-per-contract 2 --stock-commission-bps 2

预期精确账本权益100642.7416、引擎两位小数100642.74，重复新增事件0；这只是固定合成路径的账务验收值，不是投资收益预测。验证目录保存输入、源文件/二进制hash、价格文件hash、官方日志/订单、账本、逐日净值及验证清单。

此批支持单一期权主标的与多股票篮子；多期权主标的、按变量路径的统一三组研究报告、真实来源、自然行权/指派及父执行/日常任务仍待。monthly-replay依旧拒绝自然生命周期事件，不能将此开平仓桥接称为完整生命周期支持。plan-simulate旧机械入口的固定100/单张限制也独立保留，不能按比例拼接其成交。

## H3同资本变化路径比较报告

monthly-compare 已支持同一四字段扩展文件 signals/packages/stock_basket/execution_path，参数与上节一致。三个成员为冻结A8策略、相同股份和股票篮子的股票控制组、现金控制组；共享初始资金、执行窗口、完整价格文件、股票/期权费用和官方引擎版本。每个成员的逐日曲线都与其独立账本核对，报告先保留初始资金点，以免隐藏首次建仓损耗。

直接运行：

    python -m personal_quant.cli --config configs/demo.toml options --action monthly-compare --file examples/options/monthly-variable-path.json --engine-root .tools/lean --dotnet .tools/dotnet/dotnet --destination reports/my-variable-comparison --capital 100000 --fee-per-contract 2 --stock-commission-bps 2

自动复现和核对同一CLI（workspace必须不存在）：

    python scripts/verify_monthly_compare_path.py --workspace reports/my-compare-check --engine-root .tools/lean --dotnet .tools/dotnet/dotnet

报告目录包含 report.md/json、equity.csv、drawdowns.csv、metrics.json、transactions.csv、三个成员的官方结果/逐日账本/输入/源码及manifest.json。指标复用ffn，展示观察区间、短样本年化、波动、回撤、买卖金额、换手、佣金与解释性价差。变化路径的价差按实际成交日期报价核算，不用月末选约参考价替代。净交易盈亏=股票交易盈亏+期权交易盈亏−佣金；价差已包含在买ask/卖bid的交易价格中，不能再次扣除。报告核对该分解与终值差一致。

固定合成样例中策略净盈亏642.7416、相同股票基准597.7416、现金0，策略相对股票差额45；期权价差解释值50、期权佣金20。这些是工程资金核对值，不证明策略有效、真实历史表现或自然前向保护。控制组的股票仓位不是全仓基准。输入模型、股份与预算没有通过报告优化或自动挑选。

load_monthly_report继续核验文件hash、报告hash及每条发布曲线与官方/独立账本一致；旧schema2仍可读取。此批是变量路径的三组机械报告，实际数据、自然生命周期及统一账户任务/父执行仍需后续验证。

## 月度末期自然到期与账户桥接（工程阶段）

monthly-replay 的扩展文件可增加 final_lifecycle="natural_expiry"。仍需完整显式合成路径与每周期包数；此前周期按原规则平仓，末期持有至到期，下一交易日收盘清理交割后的剩余股票。没有传该字段时继续原到期前退出。该字段已接monthly-compare，尚未接日常用户账户任务，不能据此宣称整个生命周期闭环完成。

使用官方LEAN自然OptionExercise事件，区分到期失效、自动行权和空头指派；同一订单派生的股票交割事件不重复导入，由规范化期权事件一次更新股票和现金。实际原生事件时点保留；发生于周末的确认按下一交易日结算，不把周末伪装成交易日。下一交易日清理是明确模拟假设，不是券商安排。短腿采用显式DefaultOptionAssignmentModel(priorExpiration=0)的到期日模型，本入口未验证提前指派路径。

独立预期按期权到期内在价值、真实合约单位、有符号数量、持股成本、交割后到清理日的价格变化及佣金计算，不直接套用旧固定价往返公式。到期/行权零费用为当前官方模型假设，非零原生费用会要求重新验证，不当作现实费用规则。出现净交割股票空头时需要独立恢复路径，不能借“只做多”掩盖。

固定样例 examples/options/monthly-natural-fixtures.json 包含十条两周期工程路径：原四条单腿/覆盖路径，以及Collar上下两条、Bull Call/Bear Put价差、Long Call行权、Long Put失效。初始资金各100000、包数1/2、单张交易费2；前四条独立终值99762/98762/101182/99182，后六条98944/100944/100944/100944/101762/99762。它们是账务核对值，不是策略业绩。

在不存在的workspace复现实际CLI：

    python scripts/verify_monthly_natural.py --workspace reports/my-natural-check --engine-root .tools/lean --dotnet .tools/dotnet/dotnet

每个成员保存请求、原生输出、引擎事件、隔离bridge.sqlite、账本快照和验证清单。新增lifecycle-receipts.json按每条实际凭据保存不同账本序号的中间状态；出现股票空头、账务异常或缺权益会标BLOCKED，后续相抵不能覆盖旧风险记录。临时空头阻断另用明确独立样例验证，本次官方指定路径的中间状态不冒充已观测的其他成交顺序。重复导入新增0，交割后清理和结算完成时头寸/应收应付均归零；不写入用户账户。

多腿自然事件已经加入指定到期样例，但完整提前指派及异常恢复、多期权主标的、自然路径同资本报告、父执行/daily任务及实际来源仍需继续实现或验证。既有27个诊断生命周期样例不与本月度事件拼接成新成交路径。全部为synthetic工程验证，不代表真实期权历史或自然前向观察。

## H0保护分配计算接口（尚未接入CLI/计划）

`personal_quant.hedging.allocation.coverage`校验冻结持股、实际/在途有符号期权张数与显式分配引用。输入用稳定security_id和(contract_id, contract_version)，切片为[share_start, share_end)，不是税务批次。条款字段为security_id/right/shares_per_contract/valid_from/valid_until/recorded_at，right使用put或call。actual_protected_shares和inflight_intended_shares分别输出；unallocated_actual_contracts保留未关联实际风险。

该接口仅校验显式输入，尚未从统一账本/来源资格自动构造依据，也不创建预留或计划。后续必须由相同前缀事实和经核验条款适配，结合现时资源版本和权限复核后提交；不得手填示例字段作为真实合约资格。

## H0账本事实覆盖读取

```bash
python -m personal_quant.cli --config configs/demo.toml hedge-coverage --account-id sample --file coverage.json
```

请求严格包含schema_version=1、as_of、knowledge_cutoff、ledger_seq、ledger_view、security_ids、allocations及inflight_plan_ids。security_ids为证券代码到稳定ID的一对一显式研究映射，身份注册/来源资格尚待接入，不能凭自填ID授予执行资格。allocations沿用保护分配字段，不接收自填实际持股、实际期权张数或合约条款。

实际股数、期权方向/张数来自该账户指定前缀；条款来自option_contracts并比对账户引用的确切内容版本，真实环境另核验单位凭据。知识截止前必须已取得全部前缀事件及所用条款；known_then不能使用as_of之后的凭据。demo可显式restated并使用后来收到的原始凭据，但不改原记录时间、不冒充当时所知。两个时点都不得在未来。

在途只读取inflight_plan_ids指定的、明确记录人工提交且未结束的订单；草案不算在途。部分成交扣除后再计算剩余张数，不与已成交重复。无持仓ID映射、未取得条款、晚到人工状态、账户异常或方向冲突均明确拒绝。读取和CLI失败都不记任务/成交/计划、不新增预留。

可独立运行的合成凭据示例（destination必须为不存在的目录）：

```bash
python scripts/verify_hedge_coverage.py --destination reports/my-coverage-check
```

它创建明确测试账单与demo账户，验证成功/重复/非法前缀三条真实CLI调用；不下载实际期权数据。已执行证据见reports/v19-implementation/hedge-coverage-cli-20261011/verification.json；示例coverage请求为其中read.json。

## H0证券身份登记与覆盖绑定

```bash
python -m personal_quant.cli --config configs/demo.toml security-register --file templates/demo-security-spy.json
python -m personal_quant.cli --config configs/demo.toml security-register --file templates/demo-security-spy.json --commit
```

首条只预检身份，第二条显式登记；两条沿用通用CLI任务记录，不改账户资金/持仓。重复登记同内容返回同一version_hash和原registered_at。身份保存于runtime/<environment>/hedging/securities/<version_hash>，旧版本保持不可变，不自动把引用升级为新版本。

字段包括稳定security_id、instrument_type、ticker_history有效窗口、exchange/calendar/timezone/currency/trade_unit、身份窗口、corporate_action_refs、source_qualification_refs和source_type。当前支持美国证券/USD；source_type仅synthetic或declared，不能自填verified。synthetic限demo。来源/行动引用只是声明字段，登记不会核验其业务资格；资格状态明确declared_identity_only，所有结果executable=false。类型/市场不能借同一稳定ID变更；同一有效期代码不能指向两个不同ID。

hedge-coverage可额外提供security_versions对象：键与security_ids完全相同，值为登记返回的version_hash。服务校验ID/环境、代码在as_of有效且版本在knowledge_cutoff前已登记，结果保存版本及record_hash。没有security_versions的旧研究输入保持声明映射标注，不授予已登记/已核验身份。

登记内容及record文件拒绝篡改/链接，完整备份恢复复制并核验登记目录。示例登记后的覆盖流程：

```bash
python scripts/verify_hedge_coverage.py --destination reports/my-registered-coverage
```

脚本使用明确合成账单，实际执行身份预检/登记/重跑，以及覆盖读取/重跑/非法前缀/错误身份绑定；不代表取得真实证券/期权来源或券商许可。

## H0保护分配引用的事务版本

```bash
python -m personal_quant.cli --config configs/demo.toml hedge-allocation-basis --account-id sample
python -m personal_quant.cli --config configs/demo.toml hedge-allocation --account-id sample --file allocation.json
python -m personal_quant.cli --config configs/demo.toml hedge-allocation --account-id sample --file allocation.json --commit
```

请求完整字段：schema_version=1、request_id、expected_version、expected_resource_hash、coverage_request、changes、retire_ids、reason。首次expected_version为null；当前版本和资源指纹由basis命令提供。coverage_request使用hedge-coverage契约，必须绑定security_versions，ledger_seq必须仍为当前序号，allocations置空，由所有已有分配和本次changes/retire_ids合并生成。

changes按allocation_id新增或修改；同一ID不能换父意图/证券/合约版本/角色。可以在实际部分成交后将原在途切片改为已成交，并增加剩余在途切片，须由现有账本及明确人工订单证明全部数量。未退出旧引用跨版本继续参与重复覆盖检查；换request_id/参数版本不能绕开。retire_ids是显式结束引用，保留历史和仍持有的未关联期权风险，不撤销订单、不释放原计划现金或股份预留。

预检不记账、不创建版本。提交在publication_lock和同一SQLite事务内复核分配版本、账户序号以及计划/策略绑定/来源资格/行情角色/期权审计资源指纹，再保存不可变版本链。实际存储复用tasks表的hedge-allocation审计命名空间，不自动升级数据库。相同请求ID和同内容重跑返回原审计，即使后来发生事件；该返回描述原快照，不宣称当前实时保护。相同ID不同内容报冲突，新的过期预检必须重做。

备份验证审计哈希/连续版本链、原账本前缀及登记身份记录引用，完整恢复保持原记录。保护引用持久化、HedgeIntent与Spec/Exposure/候选绑定及ExecutionGroup原计划绑定/事实进度已实现；严格分配父版本、逐阶段风险复核、来源资格及可执行计划仍待完成。旧保护分配的父意图名称只是固定引用，不以此授予交易权限；结果始终executable=false。

实际CLI样例：

```bash
python scripts/verify_hedge_allocation.py --workspace reports/v19-implementation/hedge-security-cli-20261011 --destination reports/my-allocation-check
```

目标目录必须不存在。输入为此前登记覆盖的合成工作区，7次CLI核对basis/预检/提交/重跑/新basis/重复保护拒绝/请求ID冲突；样例请求保存在目标allocation.json。

## H0父研究决定冻结与修订

```bash
python -m personal_quant.cli --config configs/demo.toml hedge-intent --account-id sample --file intent.json
python -m personal_quant.cli --config configs/demo.toml hedge-intent --account-id sample --file intent.json --commit
python -m personal_quant.cli --config configs/demo.toml hedge-intents --account-id sample
```

请求字段：schema_version=1、request_id、expected_version、expected_resource_hash、preview_request、security_ids、security_versions、decision_at、knowledge_cutoff、valid_until、trigger、base_strategy_version、timing、reason。preview_request沿用hedge-preview输入；身份必须逐项绑定目标scope。首次expected_version为null，修订引用原version_hash。资源指纹由hedge-allocation-basis读取，也包含已持久的父意图/保护引用，除账户序号外变化仍须重新预检。

base_strategy_version明确MANUAL_HOLDINGS或当前账户已生效且知识截止前已请求的ACTIVE策略spec_hash，不能仅填写任意版本字符串。timing为forward或historical_research；后者限demo，明确记录实际generated_at与历史decision_at，不冒充当时发出的决定。forward不能使用restated风险、未来知识截止或已经结束的窗口。风险必须是当前账本前缀，原前缀内容不得被篡改。

父ID固定于账户/稳定证券范围/目标名称版本和模式/决策时点/触发类型。候选或输入修订保存新revision、previous_version、Spec/Exposure/候选hash、身份记录和资源依据；旧记录保持不可变。同一Spec名称版本不能更改参数，同账户范围和窗口的另一个Spec版本也不能绕过原选定父意图。其他候选可先只读预览，不应将全部搜索结果登记为选定意图。

当前仅冻结父研究决定，状态DRAFT/RESEARCH_ONLY、executable=false，不创建资金预留或执行组。父意图关闭已接入；执行组原计划绑定/事实进度已接入，保护分配严格父版本绑定及逐阶段交易前复核仍待接入，不能根据DRAFT执行交易。hedge-intents读取原最新修订，不宣称现时行情/持仓或权限。完整备份验证风险和身份引用，恢复保持原决定。

合成CLI复现（目标目录须不存在）：

```bash
python scripts/verify_hedge_intent.py --workspace reports/v19-implementation/hedge-preview-cli-20261011-final --destination reports/my-parent-check
```


## H0父研究意图关闭

```bash
python -m personal_quant.cli --config configs/demo.toml hedge-intent-close --account-id sample --file close.json
python -m personal_quant.cli --config configs/demo.toml hedge-intent-close --account-id sample --file close.json --commit
```

close.json 完整字段：schema_version=1、request_id、hedge_id、expected_version、expected_resource_hash、action、reason。expected_version 引用最新父修订的 version_hash，资源指纹由 hedge-allocation-basis 读取。action 为 CANCELLED 或 EXPIRED；EXPIRED 必须已到 valid_until，登记时间使用实际处理时间，不回填历史关闭时点。默认仅预检，--commit 追加不可变关闭凭据。

关闭不修改原父记录、不新增财务事件、不释放计划预留、不取消券商订单。尚未核实结束的 execution_groups 会阻断关闭。执行组另存不可变 registry；关闭同时检查该 registry 的原计划进度。存在未完组时阻断。此门禁不代表完整逐阶段执行资格已交付。旧保护引用仍保存，实际持仓风险不消失；未完成严格父版本/执行组绑定前不得据此生成真实可执行计划。

关闭后禁止修订或重新开启同一 hedge_id。新的明确决定可以使用已关闭研究范围，但仍须通过原策略参数版本校验、当前资源和完整保护覆盖检查。原创建请求的精确重跑仍返回原研究凭据，不代表意图已重新生效。hedge-intents 同时返回原最新修订 intents 和独立 closures，保留两种事实。

同关闭请求重复提交返回原凭据；同 ID 改内容报冲突。锁和 SQLite 事务内核对父版本、资源指纹；并发相同请求只保存一次。备份与恢复验证关闭哈希、父引用和关闭后无修订。

实际七条 CLI 复现（目标目录须不存在）：

```bash
python scripts/verify_hedge_intent_close.py --workspace reports/v19-implementation/hedge-intent-cli-20261011-final --destination reports/my-parent-close-check
```

输入为已有明确合成父研究工作区；样例请求及 stdout/stderr 保存于目标目录，verification.json 标记 synthetic_historical_reconstruction。不会更新用户账户。


## H0原计划执行组绑定与事实进度

```bash
python -m personal_quant.cli --config configs/demo.toml hedge-group --account-id sample --file group.json
python -m personal_quant.cli --config configs/demo.toml hedge-group --account-id sample --file group.json --commit
python -m personal_quant.cli --config configs/demo.toml hedge-groups --account-id sample --as-of 2026-10-10T00:00:00Z
```

请求完整字段：schema_version=1、request_id、hedge_id、parent_version、expected_resource_hash、stages、reason。每阶段仅含 stage_id、plan_kind（stock/option）、plan_id、action（OPEN/CLOSE）、depends_on（前序阶段ID列表）。最多50阶段，依赖必须先声明；未知/循环/重复方向拒绝。全部 OPEN 计划必须恰好桥接原候选的证券/合约版本、方向及数量，不能用另一份接近数量的计划替代。股票筹资也属于 OPEN 阶段；候选要求筹资时，期权 OPEN 明确依赖全部筹资阶段。

股票 CLOSE 依赖所退出 OPEN，原计划数量必须与该 OPEN 的反向数量一致。期权 CLOSE 直接引用本组原 OPEN 的同一个 option_plan_id，由该计划关联的实际 CLOSE/到期/行权/指派事实推进，不另造账本或重复财务事件。一个原计划不能归属另一个父版本，一个父修订仅绑定一组。已有组的父意图不能直接修订覆盖执行依据；原父窗口内的剩余引用修订见后续hedge-group-revise；候选改变/单位行动与滚动重规划仍待，不能据此自动生成替代订单。

组本身不创建计划、不激活草案、不预留现金或股份，不授权交易。原计划实际状态及资源由原业务模块维护。阶段存冻结数量/方向/版本及初始原计划哈希，阶段行改变或拆股单位改变会 BLOCKED，不将旧数量直接套用到新单位。组定义和原父引用纳入完整备份验证。

进度只计明确 plan_id 关联的财务事实，区分 WAITING_FACTS、WAITING_DEPENDENCY、PARTIAL、SETTLEMENT_PENDING、COMPLETE 和 BLOCKED。数量填满还须结算完整、没有未结束人工订单及异常才算完成。依赖同时在每次实际成交时点按账本前缀复核，后来的资金到账不会抹掉之前违规成交。--ledger-seq 可读取旧事实前缀；输出明确 restated，表示按已记录事实重建，不冒充当时实时知识。多阶段时序复核缓存重复前缀，整次读取在发布锁/SQLite事务内保持一致。

当前 COMPLETE 仅表示该组定义的成交/结算完成；来源、报价、当前估值、整体覆盖和每个可达中间状态的压力/风险资格仍须接入逐阶段交易前检查，executable 始终 false。关闭父研究意图仍保留实际资产和原资源，不等同于平仓或撤券商单。

实际合成 CLI 链路（目标目录须不存在）：

```bash
python scripts/verify_hedge_group.py --workspace reports/v19-implementation/hedge-intent-cli-20261011-final --destination reports/my-group-check
```

该 verifier 复制冻结合成研究工作区，建立标记 synthetic 的原生格式 DRAFT 股票计划，核对11条实际 CLI 和两笔标准合成成交的程序化导入。重复成交新增0，37股 IEF 卖出后持仓63、现金7400；原父记录不变、组没有第二份预留。不是券商凭据或实际账户验证。原期权开/部分平/结算进度由独立小样本回归验证，完整多腿中间风险与统一 daily 仍待。


## H0严格保护分配父版本（schema 2）

hedge-allocation 沿用原 CLI；schema_version=2 在原请求字段上增加 parent_versions，逐 allocation_id 映射确切父 version_hash。映射须完整覆盖合并后所有保留的引用，包括未修改的旧引用；退出引用从映射移除。原 changes/coverage_request 格式不变，股份与实际/在途事实仍由原覆盖计算统一核对。

父版本必须属于该账户，父ID和稳定证券范围一致，确切合约和保护角色/方向必须出现在原选定候选。实际与在途张数合计不能超过该父冻结目标，即使账户实际多持有期权，也不能自动归属为这一父的保护。不能给股票减持父意图添加任意Put，代理Put也不能被当作其他股票的直接股数保护。

新增/修改引用仅能使用未关闭父的最新修订。同一allocation_id不能静默换父版本；版本迁移须显式退出旧ID、用新ID登记，旧引用/旧实际风险仍保留历史。已绑定历史在父关闭或后续修订后仍可读取；关闭后新增/修改拒绝，显式退出仍保留实际未分配期权风险，不释放原计划资源。

schema 1 保留旧研究引用兼容，不授予执行资格。升级到schema 2必须显式提供所有保留引用的父版本，原父字符串不符时需显式退出/重新登记；不会按名称自动匹配。升级后整集合禁止降回schema 1。输出和完整备份保存 parent_versions、原父 record_hash 及候选 preview_hash，并验证引用完整性。全部仍 executable=false，不新增财务预留。


读取输出 parent_binding_status：BOUND 表示确切父版本已绑定，LEGACY_UNBOUND 表示仅旧研究字符串引用。读取和精确重跑同样校验原父引用，不能用重复请求绕过已损坏的父/候选记录。

实际合成CLI复现（目标目录须不存在）：

```bash
python scripts/verify_hedge_parent_binding.py --workspace reports/v19-implementation/hedge-option-preview-cli-20261011-final --destination reports/my-strict-parent-check
```

该 verifier 复制明确合成工作区，登记稳定身份并实际调用父决定及严格分配 CLI；标准合成筹资/期权成交程序化导入、重复新增0。9条CLI核对父冻结、预检、错误父拒绝、提交、重复、禁止降级、父关闭、关闭后编辑拒绝和引用退出。退出后实际Put仍是未分配风险；不是券商资料或实际期权数据验收。样例JSON/stdout/stderr/verification.json保存于目标目录。


## H4统一日常对冲监测与四页只读视图

```bash
python -m personal_quant.cli --config configs/demo.toml hedge-status --account-id sample --as-of 2026-10-10T00:00:00Z
```

hedge-status 在同一发布锁/SQLite读取事务中核对父/执行组/保护引用、原风险/证券/期权链引用，并重新计算指定时点和当前账本前缀的覆盖。返回原 allocation_archive 与 current_coverage，原父 decision_at/generated_at、历史重建或前向类型、关闭凭据与实际执行进度分开展示。demo 可明确重述历史；其当前覆盖以实际检查时取得的知识为准，知识截止改变会形成新 monitor_id，不覆盖原决定或财务事实。

原引用损坏、执行组时序/数量异常、人工在途、保护覆盖无法核实、有效前向父决定尚未完成，以及到期后仍未解决的期权持仓会 BLOCKED。过期头寸不能按零价值自动抹掉。历史研究决定仅供归档，不冒充有效前向计划。SUCCESS 只代表本监测检查通过，executable 始终 false，报价/来源/Greek/逐阶段压力资格仍独立检查。

daily 在期权凭据后和全部财务事实后各保存一份对冲步骤输出。监测阻断时停止新增基础计划/期权开仓，继续记录实际凭据、对账、报告及核实风险退出；基础模拟器和原计划新建/修订、期权激活/模拟入口也调用共享门禁，不能仅绕过daily执行。发布锁在SQLite事务之前获取，月度绑定决策与日常事务阶段沿用该顺序。精确已完成模拟重跑仍返回原审计，不制造新的成交。

四页新增“股票与期权对冲：父决定、执行与保护”：账户页显示实际保护、在途和未分配期权风险；研究页读取原冻结风险/模型，标注原截至时间；计划页显示父修订、实际组进度及关闭；运行状态展示全部阻断原因。今日待办引用相同监测。刷新不写事件、计划、预留或诊断任务。

实际四条CLI复现（目标目录须不存在）：

```bash
python scripts/verify_hedge_monitor.py --workspace reports/v19-implementation/hedge-parent-bindings-cli-20261011-final --destination reports/my-hedge-status-check
```

复制明确合成工作区，核对历史视图/重复、未解决到期风险、损坏引用诊断；诊断命令即使返回BLOCKED也正常退出0，用户/调度应检查JSON status。资源/财务序号及诊断任务数量不变。此脚本不执行实际浏览器检查；四页操作另由Streamlit AppTest回归核对，最终同源码实际浏览器仍须验收。


引擎证据归档保留同目录原子重命名。WSL/Windows暂时拒绝目录重命名时最多尝试5次，间隔0.1/0.2/0.4/0.8秒；持续失败明确PUBLICATION_PERMISSION_DENIED，未激活账本/预留，不降级为非原子复制。已有归档永不覆盖。避免并发遍历正在发布的.pending目录。大型引擎回归须预留足够测试磁盘空间；完整备份/恢复及最终浏览器仍纳入P5/O6/H5，当前阶段通过不代表v1.9最终验收完成。

## 预测保护股数与逐笔凭据审计

基础计划和股票模拟写账前，预测持仓必须保留活跃实际/在途保护切片所需股数。失败返回HEDGE_PROJECTED_COVERAGE，不生成新的可执行数量或模拟成交。结束保护引用不会自动平掉期权、取消人工订单或释放原计划资源；未分配实际期权风险继续显示。

daily --option-receipts 的批次审计及 --option-resolutions 的解决审计现在保存risk_history。每个新增财务事实按账本序号分别冻结生效时点快照，即使时间戳相同也不会合并；has_intermediate_anomaly不会因最终余额恢复而消失。准确重跑返回原凭据，重复事实不制造新的风险前缀；备份及恢复核对哈希/原账本前缀，并重新计算核心财务字段。运行状态中的“逐笔期权凭据风险历史”只读显示；旧导入缺少这类证据时标注LEGACY_UNVERIFIED。

这些是按事实前缀重建的账户诊断。没有合格报价时valuation_status=NOT_EVALUATED；预留和待核实状态来自审计时上下文，不能解释为当时实时PIT证据。NO_ACCOUNT_ANOMALY仅代表此账户快照未报异常，不等于来源、估值、压力或执行资格通过。历史异常的核实恢复流程及合格期权估值贯通基础计划仍待交付。

离线CLI校验（目标目录必须不存在）：

```bash
python scripts/verify_receipt_prefix.py --destination reports/my-receipt-prefix-check
```

脚本建立明确合成独立账户，20000入金、两腿各200保费，Put行权产生临时-100股后Call行权恢复零股；最终现金19600，3条实际daily命令核对原审计重跑和不同文件重复事实。故意不绑定行情：预期daily整体BLOCKED/退出3、UNASSIGNED_DATA_ROLE，凭据仍SUCCESS；此为验证保留事实和风险阻断共存，不代表完整行情日常流程或真实账单验证。

## 持有期权时的基础股票计划

plan、revise-plan、simulate现支持--option-valuation，输入沿用daily的JSON：snapshot_id与limits。limits必须包含max_age_seconds、max_underlying_skew_seconds、max_spread_fraction、max_leg_skew_seconds，数值由用户明确配置；示例不是真实风险参数。计划页可上传同一JSON，生成或修订调用相同服务。

有期权时，没有本次明确合格报价则OPTION_VALUATION_REQUEST_REQUIRED；晚到、过期、版本/来源资格或价差失败则INCOMPLETE_OPTION_VALUATION，期权标的报价与股票参考收盘不同步则OPTION_STOCK_TIME_MISMATCH。中价只用于统一权益，股票份额仍按核验股票原价计算；不会再次扣已付保费或增加独立余额。完整估值和输入写入计划，备份还原原报价依据。

修订须再次传入本次输入，不默认继承旧计划估值。股票模拟需成交状态时点的期权报价，不能用决策日旧报价填缺；daily迟到重放保持成交时点，允许收到时间晚于该时点但不晚于处理截止的原报价，拒绝交易所时间晚于成交时点的价格。此为明确模拟状态重述，不冒充当时已收到报价。

实际CLI离线复现（目标目录须不存在）：

```bash
python scripts/verify_stock_option_valuation.py --destination reports/my-stock-option-valuation-check
```

五条CLI和READY备份/恢复核对明确合成账户：1000入金，保费200，期权估值205，权益1005；50%股票目标按100价格生成5股。成交后现金300/股票500/期权205，总权益1005。缺输入拒绝、传新报价成功、完成重跑不重复成交均验证；不是券商成交或真实期权策略业绩。

## 中间财务异常核实与恢复

hedge-status返回option_incidents：标准凭据前缀中的实际负持仓、资金/期权担保不足或实际备兑缺口保持OPEN，最终余额恢复也不自动关闭。OPTION_INCIDENT_REVIEW_REQUIRED阻断新计划；实际凭据导入、对账和报告仍可继续。待核实/预留上下文与真实财务异常分开，当前未解决状态仍需处理。

准备核实JSON（schema_version=1）：request_id、incident_id、expected_hash（异常view_hash）、expected_sequence、as_of、recovery_event_ids、reconciliation_id、reviewer、reason、evidence_type、evidence_files。recovery_event_ids须列出异常后到恢复前缀的全部事实，包含需要的原事件/冲销/更正；对账需同账户/序号/时点PASSED。evidence_files将普通文件名映射到SHA256，原文件放在独立目录；不支持越界路径/符号链接。demo可用明确test，真实/paper需actual及实际恢复事实；声明不等于软件自动验证券商真实性。

```bash
python -m personal_quant.cli --config configs/demo.toml option-incident-review --account-id sample --file review.json --evidence-directory review-evidence
python -m personal_quant.cli --config configs/demo.toml option-incident-review --account-id sample --file review.json --evidence-directory review-evidence --commit
```

预检不写审计/财务/预留；提交冻结核实及凭据，精确重跑原样返回。核实后保留原异常，原计划不会自动变为READY；仍须明确修订并通过当时全部风险检查。当前状态未恢复、对账时点/序号不符、缺恢复事实或凭据篡改均拒绝，不靠理由放行。完整备份包含核实凭据及原引用。

实际CLI离线演示（目标目录必须不存在）：

```bash
python scripts/verify_option_incident.py --destination reports/my-option-incident-check
```

10条CLI核对合成账单的导入/重跑、异常门禁、核实预检/旧序号拒绝/提交/重跑及破坏核实凭据后重新阻断。序号5、现金19600不变；最后示例工作区故意损坏，不作为日常运行配置。这不是自然前向、券商账单认证或自动交易。


## 执行组未成交部分修订

```bash
python -m personal_quant.cli --config configs/demo.toml hedge-group-revise --account-id sample --file group-revision.json
python -m personal_quant.cli --config configs/demo.toml hedge-group-revise --account-id sample --file group-revision.json --commit
```

请求完整字段：schema_version=1、request_id、previous_group_id、expected_group_hash、expected_resource_hash、as_of、replacements、reason。replacements为原OPEN阶段ID到新native计划ID的映射；资源哈希取hedge-allocation-basis。只接受当前组头版本、原父有效窗口及确切未成交数量/方向/单位/合约；不能用来改变已冻结候选或自动滚动。

原计划须已明确CANCELLED/EXPIRED/SUPERSEDED、无人工在途、原现金/持仓预留为0；该命令不替用户撤单或释放预留。预检只读，提交追加不可变逻辑版本；精确重跑返回原凭据。即使原计划未成交，也保留空历史切片捕捉晚到事实。期权已开仓部分继续关联原计划退出，新剩余部分关联新计划退出；关闭依赖分别保留。修订不能掩盖原执行异常，新的修订前生效事实会触发明确阻断。

hedge-groups返回全部不可变groups版本，progress采用指定时点/账本前缀的当前头版本。hedge-status/group_archive及计划页保留旧版本；父关闭核对当前完整进度。BOUND/executable=false仅为引用绑定，阶段来源/报价/压力与原生计划激活仍有未完成门槛。

已验证9条实际CLI及源码指纹，样例明确synthetic，见reports/v19-implementation/hedge-group-revision-cli-20261011-final/verification.json。复现验证：

```bash
python scripts/verify_hedge_group_revision.py --workspace reports/v19-implementation/hedge-intent-cli-20261011-final --destination /tmp/lyrax-group-revision-example
```

使用独立新destination，不覆盖已有工作区。验证脚本含显式合成native格式计划与账本事实，不能作为真实交易或券商接口验证。


## 当前执行阶段的部分成交压力检查

```bash
python -m personal_quant.cli --config configs/demo.toml hedge-stage-check --account-id sample --file stage-check.json
```

输入完整字段：group_id、expected_group_hash、expected_resource_hash、stage_id、exposure_id、option_snapshot_id、quote_limits、stress。风险归档须为同账户当前完整前缀，阶段须属于该时点当前头版本；原计划/资源变化需重新冻结风险，不倒用旧参考。OPEN须在未关闭父窗口，未完成依赖或人工在途不检查为合格。option_snapshot_id在无相关期权时显式null，有相关期权时须本次已可用的确切合约报价。

quote_limits包含max_age_seconds、max_underlying_skew_seconds、max_spread_fraction、max_leg_skew_seconds、max_underlying_price_fraction。stress包含scenarios/models（沿用hedge-stress）和limits；limits完整键为stock_cost_bps、option_fee_per_contract、adverse_slippage_fraction、cash_buffer、minimum_sample_equity、maximum_sample_loss。阈值由用户显式选择，示例不代表真实风险偏好。模型必须涵盖已有及拟交易全部确切合约；当前所有股票/期权标的都须在情景残余收益及风险Beta模型内。

返回每腿0或剩余最大数量的所有端点，含required_settled_cash、sale_proceeds_not_available、现金/备兑/报价数量检查及有限情景损失。卖出费用从应收净额扣除；净卖出款在结算前不可资助买入。复用本阶段预留，其余计划股份不重复覆盖。最多8腿且总合约情景1500，超出明确拒绝，不省略未检查分支。固定报价下的数量线性端点不是提前指派/交割或变化报价路径证明。

CHECKED/execution_qualification=NOT_GRANTED仍为只读情景结果，不能把此结果作为READY或交易授权；原生计划/激活/daily的整合仍待。命令不写财务、预留或诊断任务。4实际CLI复现证据见reports/v19-implementation/hedge-stage-cli-20261011-verified/verification.json；全部synthetic，实际账户未写入。

```bash
python scripts/verify_hedge_stage_check.py --workspace reports/v19-implementation/hedge-intent-cli-20261011-final --destination /tmp/lyrax-stage-check-example
```

使用新destination；脚本复制合成工作区并绑定native格式草案，不构成真实期权/券商或引擎执行验证。


## 组内原生操作的强制阶段请求

已绑定当前执行组的期权激活/OPEN模拟、退出预检冻结/CLOSE模拟请求增加可选键hedge_stage_check：内容为上一节完整当前阶段请求。对组内计划该键必须提供，且重新计算的风险as_of必须等于本次操作时点；不是传旧CHECKED结果。对无组native计划不得冒传另一阶段请求。原有来源、月度时点、原生引擎及真实权限门槛仍需分别满足。

股票simulate可传--hedge-stage-check stage-check.json；daily可传--hedge-stage-checks stock-stage-checks.json，文件为plan_id到请求的映射。daily期权OPEN/CLOSE在--option-tasks各request内传hedge_stage_check。检查失败不写该模拟批次事实，daily保存具体错误并停止后续期权任务；已提交原生操作通过原审计恢复，不重复成交。

激活/模拟/退出审计保存阶段依据；完整备份核验原组/风险/数量引用。当前60项相关回归含真正native格式月度保护Put成功激活及备份恢复，见PROGRESS；本批尚无新增入口最终CLI/实际浏览器验收。该路径仍为合成历史demo，无实际期权数据/券商权限，阶段检查不授予真实账户交易资格。

### 自然到期同资本报告验证

扩展monthly-compare JSON沿用signals/packages/stock_basket/execution_path，并显式增加final_lifecycle="natural_expiry"。股票、现金控制组沿用同一终止日；下一交易日收盘统一清理是工程假设。自然路径日终净值截止下一本地午夜，含到期事实，保留实际事件时间；与普通收盘曲线的观测口径区别明确保存在报告假设及daily-equity.csv。实物交割现金单列，市场换手不含交割，不能解释为实际期权表现。

已实际执行：

```bash
python scripts/verify_monthly_natural_compare.py --workspace reports/v19-implementation/monthly-natural-compare-cli-20261011 --engine-root .tools/lean --dotnet .tools/dotnet/dotnet
```

首次证据目录已存在；复现时选择新的workspace。报告位于该目录comparison/report.md，verification.json含源码指纹与实际CLI。

### 独立股票对冲草案及激活

先冻结完整hedge-intent，再显式调用hedge-stock-draft。JSON需schema_version=1、request_id、hedge_id、parent_version、expected_resource_hash、as_of、snapshot_id、reason；snapshot_id是父风险的实际原价valuation_snapshot_id。默认只读预检，--commit保存DRAFT，不写成交/现金预留，不生成月度信号。

将返回plan_id作为stock_stages中的明确OPEN引用，按hedge-native-plans绑定执行组。随后hedge-stock-activate JSON需schema_version=1、request_id、plan_id、as_of、expected_resource_hash及本次hedge_stage_check。先预检，--commit检查后预留现金/股份并标记READY。这是人工执行建议，未下券商单；固定逐笔股票费非0目前明确阻断。

实际成交仍用标准账单，部分成交和完成由原账本推进；演示simulate需要成交日原价及当前组阶段请求。旧月末目标修订不会修改对冲数量。父/单位/参考价或资金发生变化时需明确重规划，不能把未结算卖出款当可买现金。股票关闭/反向产品持续管理仍未整体交付。

9条实际CLI/源码证据复现：

```bash
python scripts/verify_hedge_stock_draft.py --workspace reports/v19-implementation/hedge-intent-cli-20261011-final --destination reports/my-stock-native-verification
```

输入是已有明确synthetic父工作区；脚本只复制到新destination，示例max_weight显式设0.80以核验IEF减仓，不能继承为真实风险参数。测试生成/绑定/激活不新增财务事件。已验证报告：reports/v19-implementation/hedge-stock-draft-cli-20261012-verified/verification.json。

### 已冻结股票阶段的迟到行情

股票反向退出使用同一hedge-stock-draft入口，在原OPEN仍为DRAFT时额外提供exit对象：opening_plan_id为原计划，execution_session为明确退出日。先生成OPEN和退出草案，再在hedge-native-plans.stock_stages中明确绑定OPEN和CLOSE；CLOSE直接依赖原OPEN。数量是原数量的反向，不能通过月末权重修订改写。退出日须晚于OPEN假设结算日，可晚于原父新增交易窗口。

hedge-stock-activate按草案用途检查：OPEN未完成或未结算时，CLOSE不能激活；新的风险/对账合格后，激活保存独立执行前缀。原冻结快照不覆盖。只有原OPEN财务推进可沿用退出草案，入出金、公司行动或其他未关联变化需要明确重规划。原价变化也会阻断，尚未实现任意价格和单位行动的退出修订。

18实际CLI及独立往返/完整恢复验证：

```bash
python scripts/verify_hedge_stock_close.py --workspace reports/my-stock-close-check
```

此脚本创建合成demo账户/行情，展示原SPY100卖40后买回40；两笔费用共5.6、最终现金19994.4、权益29994.4。已验记录reports/v19-implementation/hedge-stock-close-cli-20261012/verification.json，不是实际投资或券商成交。

目前仅支持事先激活的独立 `purpose=hedge_stage` 股票计划。风险请求显式加入 `execution_replay`，字段为 `plan_kind="stock"`、原 `plan_id`、原成交收盘 `execution_at`、实际处理时点 `processing_at`；`as_of` 等于前者，`knowledge_cutoff` 等于后者。报价及Greek观察仍不得晚于原成交时点，数据接收可晚到；未来交易日价格不会进入原日估值或Beta。

用 `hedge-exposure --archive` 保存风险，再以其 exposure_id 生成本次阶段请求。`simulate` 同时提供 `--as-of` 实际处理时点、`--state-as-of` 原计划成交收盘、`--hedge-stage-check` 本次请求。未事先激活、过去补建计划、计划外时点或不合格行情仍拒绝。真实账户禁止simulate；导入真实晚到成交不等同于模拟补算。

模拟凭据与阶段审计在同一事务保存；审计失败则成交及预留推进全部回滚。重跑不重复成交。完整备份及运行状态检查原财务前缀、冻结数量、费用、报价和时钟。旧风险归档缺少option_positions时，只允许独立重建的期权持仓为空，不补写或覆盖旧归档。

迟到CLI复现脚本（只复制synthetic工作区，destination必须不存在）：

```bash
python scripts/verify_hedge_stock_late_replay.py --workspace reports/v19-implementation/hedge-stock-draft-cli-20261012-verified --destination reports/my-stock-late-verification
```

期权原生阶段和所有旧月度绑定的迟到风险入口尚未整体接入，不能套用这份股票契约。

### 组内期权OPEN的迟到报价

已绑定执行组且原收盘前已激活的期权OPEN可明确传execution_replay，plan_kind为option，其余时钟字段与股票一致。风险as_of是原激活valid_until收盘，knowledge_cutoff是实际处理时点；唯一原激活/月度/金融前缀与原阶段审计独立检查。不允许未绑定计划借此放宽普通风险时点。

`options --action plan-simulate --file REQUEST.json --commit` 的JSON额外提供state_as_of原冻结收盘及本次hedge_stage_check。组内超过一天迟到而缺原时钟时拒绝；报价观察不能晚于原收盘，接收可以晚到。此入口当前只处理明确demo/合成成熟引擎归档，禁止真实账户模拟成交。组内CLOSE迟到见下节；旧月度股票绑定的迟到风险入口仍待。

已验证11条公开CLI，报告records位于reports/v19-implementation/bound-option-late-cli-20261012-third/verification.json。复现需已经通过8模板资格的实际LEAN机械引擎verification.json：

```bash
python scripts/verify_bound_option_late.py --workspace reports/my-bound-option-late --engine-evidence /path/to/qualified-engine/verification.json
```

演示资金100000、原SPY100已持有；只新增一张Put和2费用，按报价中间价估值后权益99993。不是期权真实历史收益；测试预期不构成真实资金或风险参数。

### 代理Put与股票篮子的共同资金研究

monthly-compare扩展JSON显式提供signals、packages、stock_basket和execution_path。long_put未持有代理股票且存在股票篮子时，无对冲stock控制仅持有原篮子；不会额外买入代理标的。保护性Put/备兑/领口仍比较对应股票份数及篮子。纯期权无篮子时stock控制为明确的每包100股基准。

已通过的合成例为SPY60、IEF50、GLD Put两期2/3包，同初始资金100000，股票费用2bps、每张期权费2。独立股票盈亏173.1304、期权增量45.00；报告见reports/v19-implementation/proxy-basket-compare-cli-20261012/comparison/report.md，不代表真实收益或对冲有效性。复现需源码仓库中的测试样本及已验证的LEAN/SDK：

```bash
python scripts/verify_proxy_basket_compare.py --workspace reports/my-proxy-basket-check --engine-root .tools/lean --dotnet .tools/dotnet/dotnet
```

当前支持多个股票标的及单一期权标的；多个期权标的同时持有/共同资源仍未完成。


### 组内期权CLOSE的迟到报价

退出须事先通过完整review及原组CLOSE阶段压力检查，用公开exit-freeze预检取得preview_hash，再显式--commit --expected-hash提交。迟到风险execution_replay增加exit_id，必须引用唯一原FROZEN退出、同账户/plan_id和execution_at；已取消退出拒绝。原review、阶段压力的时点与财务前缀独立核对，重算内容哈希不能代替这些引用检查。

风险as_of为原execution_at市场收盘，knowledge_cutoff为实际处理时点。当前持有期权必须提供完整option_valuation和显式Greeks；所有观察时点不得晚于原收盘，迟到接收时间不得晚于处理截止。普通风险、退出review和冻结都不因这项能力放宽事前可用性。

exit-simulate JSON增加state_as_of=原冻结execution_at及本次hedge_stage_check。阶段风险须引用确切exit_id，不能借其他退出的压力检查。示例命令：

```bash
python -m personal_quant.cli --config configs/demo.toml options --action exit-freeze --file exit-freeze.json
python -m personal_quant.cli --config configs/demo.toml options --action exit-freeze --file exit-freeze.json --commit --expected-hash <preview_hash>
python -m personal_quant.cli --config configs/demo.toml options --action exit-simulate --file exit-simulation.json --commit
```

原生公开往返验证脚本：

```bash
python scripts/verify_bound_option_late.py --include-close --workspace reports/my-bound-option-roundtrip --engine-evidence /absolute/path/to/qualified-engine/verification.json
```

workspace须不存在，脚本使用源码tests中的固定工程样本与已实际核验A8引擎证据，不取得真实期权数据/账户权限。新样例只模拟一张保护Put；基础SPY100股保持，开仓/平仓各2费用加10价差，终值99986。直接往返回归含缺/错时钟拒绝、原退出时间重哈希拒绝、平仓审计故障整批回滚、重复执行和完整恢复；公开CLI/相关回归是否终止通过见PROGRESS，不把运行中任务算已验。

该往返公开第三轮20CLI和13专项/40相关回归已经全部通过，最新b6106a7f源码。归档reports/v19-implementation/bound-option-roundtrip-cli-20261012-third/verification.json；完整命令及失败历史见PROGRESS。此为组内期权迟到批次证据，未完成股票报价/单位修订、多个期权主标的和最终全量验收。

## 股票对冲计划的显式报价及剩余修订

`hedge-stock-reprice --account-id <账户> --file <请求.json>`预检，追加`--commit`提交草案。请求字段：schema_version=1、request_id、plan_id、group_id、expected_group_hash、expected_resource_hash、exposure_id、as_of、execution_session、reason。引用当前执行组及同决策时点的完整current_risk；保留原执行配置。预检不修改资源，提交只新增DRAFT，不生成成交或自动激活。

操作顺序：确认原人工订单结束 → 明确取消原未执行部分并释放预留 → 归档当前风险 → 预检/提交修订 → hedge-group-revise替换同一阶段确切剩余 → 新阶段风险检查与hedge-stock-activate → 人工成交导入或demo模拟。实际成交切片保留；OPEN关闭依赖同时包含已成交和替代阶段。部分CLOSE可再次修订，但所有切片共享原关闭义务，不能重复恢复持仓。

修订只更新当前合格原价、费用和原方向剩余。外部入出金、单位行动或计划外交易须独立重新决策，不能沿用旧数量。组内成交及有凭据的内部费用/分红可进入当前风险。CLOSE窗口固定为原关闭起点及execution_window_sessions，不随重报价延长；OPEN仍受原父窗口约束。失败保持阻断。

本批验证使用合成账户/行情，不证明实际证券价格、账户权限或自然前向资格。公开37CLI证据：reports/v19-implementation/hedge-stock-reprice-cli-20261012-fifth/verification.json；源码319af364…，合成账本最终现金19393.98、SPY100、权益31393.98。复现脚本scripts/verify_hedge_stock_reprice.py，--workspace须使用新目录。

## 期权CSV事实与中间风险审计

`options --action import-facts`预检后显式提交，统一调用逐凭据审计。提交结果保留原added、duplicates、pending_events等字段，并返回receipt_audit_id和has_intermediate_anomaly。原批次按文件内容/预检序号冻结；使用原预检重跑返回原批次结果，原added表示该批次最初新增数。重新预检同文件后提交则added=0，已有异常不消失。

中间负股票交割即使已被后续事实抵销，也须使用option-incident-review结合恢复事件、同序号对账和冻结凭据审查。原生机械公开17CLI证据：reports/v19-implementation/native-incident-recovery-cli-20261012/verification.json；源码a985f7ca…，中间SPY -100、最终现金100386/零股，完整恢复一致。复现脚本scripts/verify_native_incident_recovery.py需--workspace新目录及--engine-evidence匹配当前适配器的原生A8 verification.json。这些是合成行情下实际引擎事件，不是实际券商记录。

通用`import-events`、看板标准事件CSV和日常账单提交也使用共享审计适配层。允许混合股票、资金、费用与期权事实；v19账户涉及期权后，各批财务前缀继续保留。原覆盖声明与事实/审计同事务。底层Ledger.import_events仍是内部事实写入接口，用户操作使用这些审计入口。

最新6af81084同源码验证：79回归、通用原生17CLI及实际浏览器7项。证据reports/v19-implementation/native-generic-recovery-cli-20261012/verification.json和native-generic-ui-20261012/browser-verification.json；四页截图在后者同目录。浏览器只在恢复的合成demo副本运行，重复上传不改变5笔金融事实或现金100386。复现原生脚本追加--generic选择通用入口。恢复配置runtime_dir是相对目录，启动时先cd恢复工作区，再指定configs/recovered.toml；避免读取其他工作区账本。


### 股票拆股后的显式剩余重规划

`hedge-stock-unit-rebase --account-id <账户> --file <请求.json>` 为只读预检；加 `--commit` 只保存 DRAFT，不预留或成交。请求沿用 `hedge-stock-reprice` 的 schema1、request_id、plan_id、group_id、expected_group_hash、expected_resource_hash、exposure_id、as_of、execution_session、reason，并新增必填 `unit_actions` 数组。每项精确指定已入账拆股的 `event_id`、`seq`、`content_hash`；哈希是该规范化 active_event 去除 seq 后的 canonical 内容哈希，原始 CSV 的文件哈希不能替代它。行动集合、原价行动日期/比例、财务前缀和风险必须共同一致。

先确认人工订单结束并显式关闭原未执行计划。分别预检/保存所有受影响未成交 OPEN/CLOSE 的新单位草案，再用同一次 `hedge-group-revise` 替换全部相应 stage_id。只替换 OPEN、留下旧单位 CLOSE 会被拒绝。已全部成交的阶段由组修订换算其展示单位；原计划、原成交与费用不改写，也不产生新的 OPEN 订单。随后以新组、当前风险及阶段压力显式激活，模拟仍复用原统一账户入口。

仅覆盖已有规范股票拆股事实的纯股票独立 hedge_stage 组；含期权组或当前期权持仓须另行核实证券/交割条款，不能按股票比例缩放期权。冲销、更正、外部资金或无关交易要求重新核实决策。逆向拆股产生非交易单位的剩余数量时保留精确账务和阻断状态，不截掉零碎资产。退出沿用原关闭窗口，不因拆股或新报价延长期限；报价再次变化需要普通显式修订。

本批独立样例已验证完整单位链和部分 CLOSE 后的拆股。公开 CLI/扩大回归/最终备份仍按 PROGRESS 的当前批次状态，不将历史通过项当作本版最终验收。


## 多期权标的共享月度研究（2026-10-12阶段验证）

`options --action monthly-compare`的`monthly_signals`支持月度二维矩阵，每个月1–10个独立冻结信号；`packages`为同形状整数矩阵。旧单标的一维输入兼容。每月各信号必须同决定/执行时点、退出规则，跨月保持相同有序标的/模板。原四个冻结信号均保留，不能将多个独立账户的收益相加。

公开复现脚本：`.conda/v19-clean/bin/python scripts/verify_monthly_portfolio.py --workspace /tmp/lyrax-monthly-new --engine-root .tools/lean --dotnet .tools/dotnet/dotnet`。提供新空目录；此脚本全部为合成研究，并检查原账户序号0及完整恢复。已验证报告：`reports/v19-implementation/multi-option-cli-20261012-third/runtime/demo/options/monthly-research/basket-comparison/report.md`。两个月SPY/GLD Put、张数[[2,1],[3,2]]、IEF50共享100000研究现金；最终100518.834000。实际C#事件包含标的，旧缺标的事件只在唯一匹配时接受，跨标的相同执行价/日期/方向不得误配。

当前适配的A8证据为`/tmp/lyrax-multi-native-20261012/engine/verification.json`，旧适配证据不能替代。42项及5CLI为阶段证据；最终全量验收仍待。


## 证券与来源关联、账户期权操作凭据（2026-10-12）

`security-assess --account-id <账户> --file request.json`为只读，字段为security_versions、security_ids、as_of、knowledge_cutoff、valuation_snapshot_id、ledger_seq。声明中的来源hash会解析实际已归档证据；行动引用为同账户已生效未冲销的SPLIT/DIVIDEND_ACCRUAL/DIVIDEND_PAYMENT event_id。缺凭据、测试来源、未绑定当前资格、撤销或未来登记明确阻断；不因price_basis标签获得资格。父决定可增加成对tool_security_ids/tool_security_versions，对工具单独绑定，不改变保护范围。

`options --action permissions-register --file permissions.json --destination <证据目录> --commit`归档操作权限资料。`permissions-assess`只读请求包括account_id、template_id、operation、as_of、contract_count、physical_cash、exit_days。登记完整字段和工程格式见src/personal_quant/options/permissions.py的FIELDS；series_id用series_id(account_id,environment)计算；不使用券商密钥，不联网下单。

`options --action greek-register --file greek-proof.json --destination <证据目录> --commit`归档一笔供应商Delta观察值；`options --action greek-assess --file greek-check.json`只读核验。登记字段见`hedging/greek_evidence.py`的FIELDS：contract为完整冻结条款，observation为原Greek字段且不含qualification_id，series_id由source和contract_version计算；证据目录至少含与observation逐字段一致的`observation.json`及独立的供应商原始资料文件，JSON内evidence_files列出各文件SHA256。核验请求严格为item、contract、knowledge_cutoff；item增加登记返回的qualification_id。只有登记/核验时间已到、有效期内、最新结论QUALIFIED、证据类型actual且文件完整时，逐笔供应商观察值才可被评为QUALIFIED；真实/前向账户还需实际合约单位凭据。自述actual需要用户提供可核验真实资料；本项目的工程样本全部标记为测试，不能替代真实来源接入。模型Greek仍需独立输入资格与重算方案，不可用该入口伪装供应商观察值。OPEN阶段和冻结审计重验已有持仓及Beta目标候选的Greek；必要CLOSE仍按完整估值及直接情景检查处理。

权限范围限制A8及OPEN/CLOSE/EXERCISE/ASSIGNMENT，现金无保证金；数量、交割资金和最小提前退出天数显式配置。evidence_type=test只验证工程，不能授予paper/real或实际资格。权限核验输出不是可执行计划，成功也须独立满足真实来源、合约、前向、账户/风险条件。

必要CLOSE遇Beta/Delta缺项可使用直接逐标的情景，benchmark_return×beta_multiplier必须明确为0；residual_returns列出每个标的的价格变动假设。权益/行情/账务仍需完整，不自动修补缺模型。非零基准情景仍要求完整Beta。

实跑12CLI/完整恢复：reports/v19-implementation/qualification-links-cli-20261012-third/verification.json。复现：`.conda/v19-clean/bin/python scripts/verify_qualification_links.py --workspace /tmp/lyrax-qualification-new`，使用新空目录，全部合成/测试，预期资格受阻且账户金融序号0。最终工程验收未完成。

## 期权月度前向信号（2026-10-12）

前向账户先导入已核验的真实期权链及合约单位凭据，在月末实际收盘加配置发布延迟后运行：`lyra --config <paper或real配置> options --action monthly-forward --account-id <账户> --snapshot-id <链快照ID> --file <固定选约规则.json> --publication-delay-minutes 30 --max-generation-delay-minutes 10 --commit`。规则JSON沿用select的template_id、underlying、decision_at、parameters；数值是配置示例，应按账户条件显式填写。输出schema2、generation_mode=forward_observed的冻结研究信号，归档在该账户的`options/monthly-forward/`。晚于生成窗口、缺实际来源资格、快照采集时间早于其中报价接收时间均拒绝发布；重跑同月同输入返回原归档，改输入报冲突。不能用historical_reconstruction改标签充当前向信号。

随后用已归档信号生成同账户草案，并在下一交易日以新报价快照调用`options --action plan-activate --file <激活请求.json> --commit`。READY仅是人工执行建议；实际成交仍由账单导入。工程测试使用冻结时钟和伪造但清楚标记的资料，不能算自然前向观察，也不能证明用户真实期权行情、券商许可或账户对账已经具备。
