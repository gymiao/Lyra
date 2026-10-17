# LyraX v1.8 操作说明

Linux / WSL、Python 3.11.15；继续使用bt/ffn和四页Streamlit。依赖及安装方法见[README](../README.md)。升级保留原账本和旧报告，不替用户创建资金或交易。

## 1. 无密钥复现

在项目根目录，用已安装项目的Conda环境执行：

```bash
python scripts/verify_v18.py
python -m pytest -q
```

演示自动建立新的隔离工作目录，验证34条CLI：显式用途、协议、分段/成本、后台工作进程、源码研究包校验/恢复/重算、测试入金/对账、月度计划、模拟成交、复盘CSV、提醒与完整恢复。输出目录由`reports/v18-validation/latest.json`指向；其中行情、账单和账户是明确标记的测试数据。源码指纹及每条命令/结果保存于verification.json。

## 2. 升级已有工作区

进入**包含runtime目录的工作目录**。配置路径与工作目录必须对应。先完成已有任务，再执行：

```bash
lyra --config configs/local.toml v18-init
lyra --config configs/local.toml data-series
lyra --config configs/local.toml data-status
```

v18-init先保存完整v3备份，再事务升级v4；重复执行返回已有版本。故障回退使用[完整备份恢复](OPERATIONS.md)，恢复到新空目录，不能用旧程序写v4数据库。用途最初未分配，避免把最后导入的数据误作原价。

data-series输出系列与快照身份，核对来源、单位、币种和截至日期后明确绑定：

```bash
lyra --config configs/local.toml data-bind --role signal --identity SIGNAL_SERIES_OR_SNAPSHOT_HASH --expected-revision 0
lyra --config configs/local.toml data-bind --role execution --identity RAW_SERIES_OR_SNAPSHOT_HASH --expected-revision 0
lyra --config configs/local.toml data-bind --role valuation --identity RAW_SERIES_OR_SNAPSHOT_HASH --expected-revision 0
```

上例哈希是占位符，需替换为实际data-series结果。之后修改时传当前revision；过期页面或命令会被拒绝。valuation可以明确复用合格execution系列。factor用途同样显式绑定；未绑定时基本面策略缺少输入而受阻，价格策略无需因子。研究可以有长期复权历史，执行可以仅有近期核验原价。历史信号与计划继续引用自己的冻结快照。

原有CSV及fetch入口保留。fetch更新signal绑定系列；Yahoo数据标为provider_split_adjusted，**不能绑定execution/valuation**。原价、公司行动或其他来源CSV需自行提供及核验，不自动换供应商。因子导入保持同来源/定义合并；更换因子来源需独立工作区，不静默混合定义。v4统一使用用途解析；旧v2/v3仅保留明确兼容路径。

## 3. 验证套件与协议

验证请求JSON包含以下字段：

- `members`：成员名对应`strategy_id`及`revision`，一个基准、1至6个候选。
- `benchmark_member_id`：其中一个成员名。
- `data_bundle`：signal_snapshot_id、calendar_hash、execution_snapshot_id、factor_snapshot_id；无需要的用途用null。
- `windows`：按时间排序且不重叠的start/end，格式YYYY-MM-DD。
- `cost_scenarios`：id、commission_multiplier、slippage_multiplier、fixed_fee_multiplier；倍数0至10。

完整可执行实例由verify_v18生成在工作目录validation.json；实际行情示例是`reports/manual-online/v18-validation.json`。

```bash
lyra --config configs/local.toml research-validate --file validation.json --background
lyra --config configs/local.toml research-validate --suite-id SUITE_ID
lyra --config configs/local.toml research-validate --suite-id SUITE_ID --recover
lyra --config configs/local.toml research-validate --suite-id SUITE_ID --retry --background
```

最多48个成员回测，顺序调用既有bt服务。同步查询命令会继续未完成项；`--recover`先核实工作进程死亡，`--retry`明确重跑失败项并保留attempt历史。成功项校验后复用。任一必要项失败，套件为INCOMPLETE。输出`runtime/<环境>/reports/validation/<suite_id>/summary.json`与summary.csv；每项关联独立bt报告。

窗口从相同初始现金开始，不拼接净值；跨费用场景不进行严格排名。每个连续报告另有continuous-slices.json年度切片，保留原持仓，不能混成独立窗口表现。

协议文件为`name`、`specification`（完整验证请求）、`future_start`：历史验证填null，未来观察填实际登记后的带时区时间，所有窗口不得早于该起点。

```bash
lyra --config configs/local.toml research-protocol --file protocol.json
lyra --config configs/local.toml research-validate --file validation.json --protocol-id PROTOCOL_ID
```

未来起点前返回WAITING_FOR_DATA；新价格可来自相同系列的新快照，规则、窗口、成本及因子冻结。验证仍明确标为历史重建；真正前向证据须来自paper工作区在当时收到的数据和已归档信号。协议不能证明用户未在其他地方观察数据，不自动选择收益最高策略。

## 4. 可还原研究包

```bash
lyra --config configs/local.toml research-package --action export --run-id RUN_ID --destination package
lyra --config configs/local.toml research-package --action verify --source package
lyra --config configs/local.toml research-package --action restore --source package --destination restored-package
lyra --config configs/local.toml research-package --action replay --source package --destination replayed-package
```

目标目录必须不存在。verify/restore不执行归档代码；replay才显式执行已验证的归档源码，在独立目录重算研究，不载入账户数据库、不修改原包。包包含源码、依赖锁、精确价格/因子/日历、配置和报告。依赖安装及wheel缓存不打进包，按锁在同平台安装后再重算。

新实验提交时归档源码。旧报告缺原源码返回SOURCE_UNAVAILABLE；允许`--source-archive`提供与原指纹匹配的基线，不能拿当前工作树替代。未登记文件、损坏内容、路径/链接不安全或依赖不兼容会拒绝。只改依赖声明而保持源码身份时返回SOURCE_LOCK_CHANGED，需明确更新实现版本，不静默沿用旧锁。本地导出不意味着拥有公开分发行情的权限；研究包不自动带密钥或账户账单。

## 5. 日常诊断与执行复盘

```bash
lyra --config configs/local.toml doctor
lyra --config configs/local.toml notices --sync
lyra --config configs/local.toml notices
lyra --config configs/local.toml execution-review --plan-id PLAN_ID --output review.csv
```

doctor只读，不创建账户、迁移、下载或解锁风控；检查依赖、配置、用途、历史长度、价格质量、报告、计划和对账。READY_FOR_REVIEW仅表示所列检查可供审阅，不保证可下单。未安装调度显示UNVERIFIED。无工作区显示UNINITIALIZED。

notices --sync是显式写入本机提醒，按稳定键去重。`--acknowledge NOTICE_ID`只确认已读，不解决差异；原因解决后同步变RESOLVED，再发生时清除旧确认。没有邮件或外部消息发送。

复盘使用有效事件、明确plan_id及本修订；显示参考价差、估计/实际费用、剩余数量、拆股换算、冲销、修订、未关联与异常关联成交。关闭计划的剩余数量是历史未完成量，不是新可执行订单。参考价差不是精确券商滑点，也不再次记账。输出路径必须不存在，CSV包含环境、时点、有效期与当前检查状态。

## 6. 看板与调度

进入指定工作目录：

```bash
lyra --config configs/local.toml ui
```

四页增加数据来源与用途、验证套件/协议、研究包、执行复盘下载、环境诊断与本地待办。写操作均需按钮提交；刷新不重记资金或成交。研究及诊断仍可查看受阻状态。

[调度模板](../templates/scheduling/README.md)仅为可审阅样例，未安装服务；请填写绝对路径与账户后再单独启用。关机/休眠不运行，不能把补算历史研究冒充当时前向生成。备份默认携带runtime中的源码归档、快照、报告和v4数据库；外部导出的研究包、原始券商凭据及密钥另行备份。
