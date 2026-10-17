# LyraX v1.5 使用说明

Python 3.11.15、Linux/WSL、Conda。依赖沿用V1锁文件；项目版本1.5.0。CLI仍为 `lyra`。界面和业务计算无需调用大模型。

## 最快复现

在项目根目录激活 `.conda/lyra` 后：

```bash
python -m pytest -q
python scripts/verify_v15.py
lyra --config configs/demo.toml ui
```

验证脚本自动建立新的隔离工作目录，完成六策略扣费研究、重复提交/显式重跑/比较、后台合成因子研究、入金预检与导入、月末绑定、计划、模拟成交及v3备份恢复。输出含报告位置；`reports/v15-validation/latest.json`指向最新完整验证。不需要密钥或真实账户。模拟入金10000 USD只在该次测试目录中，不影响已有账户。

使用已核验的真实行情缓存研究六类价格策略：

```bash
python scripts/verify_v15.py --real-price-cache reports/manual-online/runtime/demo/data
```

该命令复制已有真实快照进行历史研究，不下载新数据，不生成真实账户成交。先按README的在线流程获取行情才能建立缓存。价值/质量测试因子仍为合成数据，报告明确标记 `mixed_test_factors`，不是ETF真实基本面。

## 中文工作台

进入「策略研究」：

1. 旧目录点击「备份并启用策略工作台」。升级前完整备份到当前工作目录的 `reports/v15-migrations/`，不写资金事件。
2. 「策略编辑」选择模板、标的、参数和预算，可保存独立草稿、预检完整月份及首个决策/成交日，再冻结版本；从已有版本编辑会显示差异。示例按钮一次冻结六个95%预算的演示版本；相同ID/修订不能覆盖不同内容。修改参数使用新修订；展示名称可单独修改，规格可以下载。
3. 「实验与任务」选一个基准和1至6个候选，填写统一区间、资金、费用。提交后台研究后可以刷新查看任务；页面刷新不提交任务。完全相同输入返回已有尝试，勾选显式重跑才产生新尝试。
4. 下方查看净值、回撤、成本、换手、平均现金权重、交易和逐月决策原因。同模板不同修订不会覆盖。不同数据、区间、代码或费用的运行不做正式收益排名。
5. 「账户绑定」选择已建立的账户及冻结版本，提交下一合格月末绑定。研究中的选择不改变账户。截止后不能追溯切换，旧在途计划会阻断切换；受阻切换不自动顺延。
6. 「因子数据」导入标准CSV和来源JSON。未核验真实来源不能用于正式研究，合成因子不能用于paper/real前向决策。

「账户总览」还提供价格CSV及日历的预检/提交入口；原快照保留，现金/成交不因价格导入变化。「调仓计划」可分别选择信号和核验执行快照，按账户生效版本生成信号和计划；「运行状态」展示研究/日常任务、失败和对账差异。有效规则全部现金且没有持仓时归档NO_ACTION，不制造空订单。计划需要核验原价、完整行情、明确账户参数及有效对账；Yahoo拆股调整Close只支持研究，不能直接生成真实证券份额。

## CLI入口

在各工作目录执行，配置的运行目录固定为 `runtime/<environment>`：

| 命令 | 作用 |
|---|---|
| `lyra workbench-init` | 完整备份并显式升级v3；再次执行不重复升级 |
| `lyra strategies` | 查看六模板和冻结版本 |
| `lyra strategies --file configs/strategies/momentum_rotation.json` | 校验并发布精确版本 |
| `lyra import-factors --file test_factors.csv --metadata factor_metadata.json` | 增量因子导入、冲突校验、保留第一次取得时间 |
| `lyra research --experiment experiment.json` | 同步执行冻结多成员实验 |
| `lyra research --experiment experiment.json --background` | 当前Conda解释器后台执行 |
| `lyra research --experiment experiment.json --rerun` | 保留新的尝试历史 |
| `lyra research-status` | 查询尝试状态及错误 |
| `lyra research-recover` | 核实进程、恢复完整发布、修复latest；损坏产物失败不发布 |
| `lyra compare --runs RUN1 RUN2` | 核验口径并输出比较JSON，可重定向保存 |
| `lyra strategy-bind --account-id ACCOUNT --strategy-id momentum_rotation --revision 1` | 下一合格月末绑定；真实/前向使用系统时钟 |
| `lyra monthly-decision --account-id ACCOUNT --session YYYY-MM-DD --bundle bundle.json` | 账户冻结版本、信号及计划闭环 |

所有命令接受全局 `--config PATH`，放在子命令之前。旧的无实验 `research`、`signals`、`plan`、`daily`、账本和备份命令保留。`research-worker`为内部固定入口，不需要人工调用。demo绑定/决策可用明确的 `--as-of` 历史样本时钟，paper/real禁止该参数。

实验请求引用已发布的精确版本：

```json
{
  "members": {
    "baseline": {"strategy_id": "fixed", "revision": 1},
    "candidate_63": {"strategy_id": "momentum_rotation", "revision": 2}
  },
  "benchmark_member_id": "baseline",
  "purpose": "validation",
  "data_bundle": {
    "signal_snapshot_id": "替换为64位行情内容哈希",
    "calendar_hash": "替换为该快照的64位日历哈希",
    "execution_snapshot_id": null,
    "factor_snapshot_id": null
  }
}
```

这是结构说明，替换哈希/版本后才能运行。验证脚本生成可直接运行的 `experiment.json` 和 `bundle.json`。没有执行原价不阻断研究；计划数据包必须引用核验执行快照。schema及所有输入冻结到SQLite实验记录，输出带源码/依赖/数据版本及文件哈希。已看过的区间只能标为探索/验证，不宣称未见的最终评估。

## 因子CSV与资格

标准字段：`asset_id,factor_name,value,unit,period_end,published_at,available_at,value_as_of,source,source_record_id,revision,currency,data_type,definition_version`。

目前价值/质量使用 `book_to_market` 和 `roe_ttm`，以ratio表达。来源JSON必须说明source、source_reference、permission_note、availability_evidence、qualification及每个因子的unit/version/description。`qualification`为test、unverified或reviewed_source；真实资格需要来源、权限、定义和历史可用性凭据，不能仅靠改标签获得证明。

系统自行记录首次取得时间 `recorded_at`，CSV不能自填。按决策可用时间选择最新报告期，再选择该期估值日期和已知修订；晚到的旧季度更正不覆盖新季度。默认财报年龄180日、估值年龄7日；参数可以调整。缺失、过期、冲突或未核验会阻断相应月份，不能跳过月份再称完整回测。

## 恢复与升级

- 更新源码/依赖后**停止并重新启动Streamlit**；浏览器刷新不能清空旧Python模块缓存。
- CREATED且尚无工作进程的任务可再次明确提交同一输入启动。RUNNING原进程确已退出时恢复为INTERRUPTED，再显式重跑。活跃锁不按超时抢占。
- 完整目录已发布但数据库未登记，恢复校验输入和逐文件指纹后补登记；已登记但latest未更新则修复指针。损坏产物保留诊断并标FAILED，继续保留最近成功结果。
- `backup-bundle / verify-backup / restore`覆盖新策略、绑定、实验、信号、价格及因子引用。恢复只写新空目录；来源缓存和pending产物不属于成功结果。外部原始凭据与密钥需自行单独备份。
- 本机每个运行目录一个研究计算任务，不使用任务队列或额外服务；每天的市场数据计算仍由现有 `daily` 和系统调度执行。

## 使用边界

六类模板仍为日线/月度、USD、只做多、无杠杆。波动率倒数配置不等同严格风险平价；研究复权抽象份额不等同真实证券数量。真实价值/质量来源未提供合格样本，保持受阻；真实原价、公司行动支付/税费、账户账单及费用/单位/结算/风险也需要用户资料。未部署自动调度或自动下单，没有真实前向投资收益验收。
