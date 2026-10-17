# LyraX v1.95 操作说明

2026-10-16；版本1.95.0，最终发布验证进行中。最新源码与验证终态见[PROGRESS](PROGRESS.md)。以下均使用隔离环境的Python；完整期权模拟还需固定版LEAN和.NET SDK。安装见[README](../README.md)。历史开发说明另存[阶段记录](V195-USAGE-HISTORY-20261016.md)，其中“未完成”属于当时状态。

## 1. 首次模拟

从仓库根目录运行，工作区选新目录。示例为合成历史、100000 USD模拟入金，与真实行情研究及真实账户分开。

```bash
python -I -m personal_quant --config configs/demo.toml workspace init --workspace reports/my-v195/etf --spec configs/v195-etf-workspace.json
python -I -m personal_quant simulation start --workspace reports/my-v195/etf
```

保存返回的`run_id`，替换下面的`<run_id>`：

```bash
python -I -m personal_quant simulation batch --workspace reports/my-v195/etf --run-id <run_id> --through 2024-12-31 --max-sessions 128 --max-seconds 3600 --min-free-bytes 67108864
python -I -m personal_quant ui --workspace reports/my-v195/etf --port 8501
```

浏览器打开本机8501端口，Ctrl+C停止服务。查看日期只影响展示。重复初始化同规格不再次入金；更换资金/规则创建独立实验。使用未分割批次的高级`resume`接口时，调用者自行控制任务范围。

期权向导无需密钥：

```bash
python -I -m personal_quant --config configs/demo.toml workspace init --workspace reports/my-v195/options --spec configs/v195-options-workspace.json
python -I -m personal_quant simulation prepare --workspace reports/my-v195/options --file configs/v195-option-setup.json
python -I -m personal_quant ui --workspace reports/my-v195/options --port 8501
```

运行状态页选择冻结配置，填写LEAN源码目录、dotnet可执行文件，费用明确为2 USD/合约。CLI等价入口：

```bash
python -I -m personal_quant simulation start --workspace reports/my-v195/options --file <prepare返回的request_file> --engine-root <LEAN目录> --dotnet <dotnet文件> --fee-per-contract 2
python -I -m personal_quant simulation batch --workspace reports/my-v195/options --run-id <run_id> --through 2025-01-14 --max-sessions 128 --max-seconds 3600 --min-free-bytes 67108864
```

批次先停在2025-01-13行情终点，返回`BATCH_MARKET_BOUNDARY`，再次执行同一命令处理有凭据的2025-01-14现金结算。不能跨过缺报价日虚构成交。标准两月示例最终7条财务事实、99978 USD；这只是工程核对样本。每批交易日上限、子进程时间预算、剩余磁盘下限均可配置；时间到达后只终止本次自有进程组，另有最多5秒结束宽限，已提交事实保留。

## 2. 日常使用

```bash
python -I -m personal_quant workspace status --workspace <工作区>
python -I -m personal_quant simulation batch --workspace <工作区> --run-id <run_id> --through <支持区间内交易日> --max-sessions 20 --max-seconds 600 --min-free-bytes 67108864
```

检查当前时钟、最后检查点、预留/应收应付、未解决事项和批次原因。运行状态页异步提交并显示任务结果，刷新不重跑引擎。暂停使用`simulation pause --workspace <目录> --run-id <ID>`，到安全提交边界生效；继续仍使用原run_id，不重新入金。

生命周期日历显示冻结信号的决策/适用日期、合约截止、实际待结算事项及有凭据的分红。旧运行缺少可信日期索引时标未验证；分红支付日期未知不估算。到期日期本身不产生交割事实。

## 3. 失败恢复

先查看状态/任务原因，再补缺失输入。容量不足先处理空间；预算用完可以提高下次预算。报价、资金、覆盖或对账失败先解决具体原因，不跳过检查。

```bash
python -I -m personal_quant workspace diagnostic --workspace <工作区> --destination <新的诊断目录>
python -I -m personal_quant simulation batch --workspace <工作区> --run-id <原run_id> --through <目标交易日> --max-sessions 20 --max-seconds 600
```

诊断只导出版本、哈希、白名单错误代码、状态及脱敏配置身份，不含完整数据库、账单、密钥或自由错误文本。`REPORT_PENDING`重跑补发布已提交事实，不新增成交。源码或冻结输入改变时保留旧工作区，新建实验，不能用新源码静默重算旧账本。

## 4. 增加策略实验

```bash
python -I -m personal_quant experiment clone --workspace <已有工作区> --destination <新工作区>
```

复制的是规格和独立账户，不复制旧成交再入金。期权在新工作区向导选择12种已支持模板之一，预览并冻结期限、选约、数量、费用、风险及退出规则，再建立运行；修改旧冻结请求不能继续原run_id。持续持股滚动/Wheel使用显式冻结请求，见[期权规则](V195-OPTION-RULES.md)及[支持矩阵](V195-SUPPORT-MATRIX.md)。

如果新增的是程序尚无的策略，需要实现策略接口、独立规则测试、对应原生资格、计划/部分成交/生命周期/恢复验证，更新支持矩阵后再开放执行；新增目录名称不能自动获得资格。实验比较只接受资金、区间、输入及执行口径一致的独立已完成运行，拒绝跨引擎公平排名。

## 5. 升级与迁移

先停止自有任务，在工作区目录中用现有完整备份入口创建备份，备份放运行目录外；不要直接复制运行中的SQLite单文件。旧backup-bundle命令按当前工作目录解析配置里的runtime_dir，因此必须先cd到工作区；workspace系列则使用明确的--workspace。实际入口：

```bash
cd <工作区>
python -I -m personal_quant --config config.json backup-bundle --destination <新的完整备份目录>
python -I -m personal_quant workspace backup-review --workspace <源工作区> --source <完整备份目录>
python -I -m personal_quant workspace recovery-drill --workspace <源工作区> --source <完整备份目录> --destination <新的恢复目录>
```

状态页显示真实核验/恢复操作时间，不把服务模板当已安装调度。恢复保留事实和检查点，不重复初始入金。工具换路径需同时提供`--engine-root`和`--dotnet`，内容身份须相同；不等于允许更换引擎版本。旧源码归档用于核对，不自动执行。

普通wheel包含自有C#适配源码和依赖锁；LEAN与SDK独立提供。升级代码时新建模拟实验；历史报告保持只读，不默认获得新资格。空间清理先预览，保留运行/计划/报告引用，不按年龄自动删行情或实验。

## 验证与边界

实际命令证据保存在`reports/v195-validation/`，最终对应源码见[验收追踪](V195-ACCEPTANCE.md)。完整安装脚本`verify_installed_v195.py`在仓库外使用`-I`运行ETF/期权公开CLI；浏览器脚本实际操作四页。最终完整回归须无跳过。

真实ETF行情研究可用；真实期权数据及使用权、核验执行原价、真实券商账号和自然前向观察未验证。用户已暂缓真实账号；不自动下单、不把合成样本标成真实行情或实盘收益。调度仍未安装。
