# 调度、备份与恢复

## 日常顺序

获取并校验完整日线 → 导入实际账单或推进已有模拟计划 → 估值及独立对账 → 合格月末生成信号/计划 → 人工查看 → 发布报告。统一 daily 已通过固定样例及中断恢复；实际在线调度仍未验收。

信号实际归档位于该环境账户SQLite的strategy_signals表，重复请求保留首次生成时间；signals.json只是导出。可用list-signals查询，备份数据库包含这些归档。前向只能按系统实际时钟，demo固定时钟不得用于paper/real。

系统定时任务仅调用 CLI；V1 无券商下单，真实成交由用户导入。不要用固定北京时间推断美股收盘。日历、发布延迟、信号有效期和数据新鲜度由业务接口检查；正常等待、风控阻断和系统失败分别展示。

以下 Linux cron 示例调用日常流程，**示例尚未安装到实际crontab，也没有长期在线调度凭据**。脚本绝对路径、配置路径和区间需按本机安装调整，避免手动任务重叠。资金写入由 SQLite 事务及唯一约束保护。

```cron
30 * * * * cd /path/to/Lyra && .conda/lyra/bin/python -m personal_quant --config configs/local-paper.toml daily --account-id paper-account --fetch-start 2023-01-01 --fetch-end $(date -u -d tomorrow +\%F) >> runtime/paper/daily.log 2>&1
```

paper 配置需显式设置 environment=paper、runtime_dir=runtime/paper，先建立 paper-account 并显式初始化在线系列。下载 end 不包含，使用次日 UTC 日期容纳当天已完整收盘的美股数据；适配器丢弃尚未完整发布的日线。网络重试有上限；WAITING 为正常等待，BLOCKED/FAILED 返回非零，阶段及原因持久保存。

在已有测试缓存中启动在线系列需一次显式 --new-series；后续同系列更新省略该参数，通常回看14个日历日，新行动/复权修订触发历史刷新。可显式 --full-refresh；不同系列不能静默拼接。daily 使用进程锁保护完整任务；其他共享写入由事务/唯一约束/版本复核保护。账单需另行预检或导入，不从网络推定资金、公司行动或结算凭据。

纸面/真实流程不允许手工历史时钟；demo 可用 --as-of 重放测试。已有冻结计划的延迟模拟处理分别记录假设成交时点和实际处理时点；不能事后创建新计划再回填成交。数据阶段等待时不生成新可执行计划。

## SQLite 备份

```bash
PYTHONPATH=src .conda/lyra/bin/python -m personal_quant backup --destination /your/backup/account.sqlite
```

该接口实际已在离线验证脚本执行。备份不覆盖原数据库；同时归档对应配置、数据目录不可变版本、报告及清单。真实备份属于私人资料，不能提交 Git。

## 完整备份及恢复

README 的“日常任务与完整恢复”给出已实际执行的无密钥示例，验证脚本同时记录具体命令。

```bash
PYTHONPATH=src .conda/lyra/bin/python -m personal_quant --config configs/local-paper.toml backup-bundle --destination /your/private-backup/paper-001
PYTHONPATH=src .conda/lyra/bin/python -m personal_quant verify-backup --source /your/private-backup/paper-001 --environment paper
PYTHONPATH=src .conda/lyra/bin/python -m personal_quant restore --source /your/private-backup/paper-001 --destination /your/new-workspace --environment paper
```

这些路径是用户本地占位值，不是已存在的服务。完整包保存 configs/recovered.toml、runtime/<environment>/account.sqlite、已发布数据/报告/测试样本及逐文件哈希；历史配置保留在信号、计划和报告中。版本、逻辑事实哈希、表行数、账户快照与行情引用均校验。备份使用 daily 同一进程锁，另外监测其他连接提交及文件变化；发现改变则退出 BACKUP_SOURCE_CHANGED，不发布混合版本，也不在长事务内复制文件。

verify-backup 和 restore 无需工作目录中的源配置，不创建源数据库。目标必须不存在或为空目录；环境必须显式匹配。先在临时目录验证，再发布；已发布包按明确路径查找，未完成临时包不作为可恢复结果。敏感备份不提交 Git。运行目录之外的原始券商凭据、外部行情授权文件和密钥需另行备份；本包不能替代这些资料。

恢复后进入新工作目录，使用 --config configs/recovered.toml。根目录 manifest.json 是恢复时的校验凭据，运行后文件自然会变化；若需新的可恢复版本，重新执行 backup-bundle，不能继续把修改过的工作目录当作原始备份。

## 恢复演练

1. 先停止可能写入的 CLI/看板，保留原运行目录和现有 SQLite WAL/SHM；恢复到新目录，不覆盖原账户。
2. 将一致性备份数据库及对应环境的配置、行情快照和报告复制到隔离目录，校验内容哈希。
3. 用同一环境打开数据库，核对现金、数量、事件数及账本序号，再重导同一测试账单确认 added=0。
4. 重新生成报告或处理未发布的完整文件；不能因报告缺失重记已提交成交。

`scripts/verify_offline.py` 已覆盖完整包校验/新目录恢复、保存的行情和信号/报告、恢复后 daily 与账单重跑不增加事实。专项测试另验部分成交与人工在途预留恢复、缺文件/坏哈希/符号链接/跨环境/路径越界拒绝，以及并发提交不发布备份。数据库1→2升级在独立回归中验证升级前一致备份、失败事务回滚、未知高版本拒绝；浏览器四页刷新及标准账单重复提交已经实测；实际独立快照差异/解决、失败任务展示及服务重启恢复亦通过（reports/ui-validation/20261009/current/）。

账户报告的versions/<report_id>/包含不可变内容及哈希；latest.json只引用完整发布版本。读取前校验文件及账户内容，损坏版本不可作为当前估值；报告生成失败只重建文件，不重放成交。完整迁移需同时复制这些版本及引用的行情快照，不能只复制顶层account.json。

## 错误处理

- MISSING_BACKTEST_DEPENDENCY / MISSING_UI_DEPENDENCY / MISSING_DEPENDENCY：补依赖后再验，不将信号或账户模拟冒充已完成回测。
- STALE_PREVIEW / EVENT_CONFLICT：重新预检或核对来源 ID，不能覆盖已入账事件。
- 数据缺失、价格口径未知或对账差异：保留诊断，阻断计划；研究及历史记录仍可查看。
- RECONCILIATION_RULES_CHANGED：对账容差或规则版本变化，按当前配置重新独立核对；旧记录保留，不能手改旧通过结果。
- UNARCHIVED_SIGNAL / CORRUPT_SIGNAL：前向计划缺归档或归档损坏，查看实际前向数据与归档凭据；不能从历史研究补造信号。
- 人工订单在途：本地取消不代表券商撤单。确认无在途后才释放剩余预留。
- 已完成任务重复运行：按稳定 ID 返回已有事实；参数变更建立新版本，不覆盖旧报告。
- BACKUP_SOURCE_CHANGED / DAILY_ALREADY_RUNNING：其他操作正在改变来源或任务运行中，完成后用新空目录重试；不强行解锁存活进程。
- CORRUPT_BACKUP / MISSING_BACKUP_REFERENCE：包或引用损坏，不恢复；查找经过验证的完整备份，不能删掉清单项目绕过检查。
- NONEMPTY_DESTINATION / ENVIRONMENT_MISMATCH / NEWER_DATABASE_SCHEMA：保留原资料，选空目录/正确环境/兼容版本，不降级或覆盖。
- MISSING_DATA_QUALITY_CONFIG / DATA_QUALITY_BLOCKED：明确配置price_jump_threshold，核对相邻行情、价格单位及公司行动；原证据与诊断保留，补充核验后的数据版本或显式修订参数，不删异常行。单价估值不代表历史转换检查完整。
- tracking_gaps：分别查看NO_ARCHIVED_SIGNAL/NO_PLAN/SIGNAL_BLOCKED/PLAN_BLOCKED；只记录已知跟踪起点之后的缺口，不回补历史成交，不把没有成交的全现金月误报漏跑。
