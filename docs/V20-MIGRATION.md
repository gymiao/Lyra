# v2.0 升级、备份与恢复

更新：2026-10-17。本地v2.0已完成验收，当前证据见[PROGRESS](PROGRESS.md)。

## 升级原则

1. 停止自己拥有的推进/维护任务，核实进程身份及已提交检查点；UNKNOWN任务先核实，不根据超时假定没有成交。
2. 用原版本对原工作区做完整备份并核验，包含SQLite一致快照、行情/规则/计划/报告/工具引用。仅复制account.sqlite不是完整恢复包；运行中的SQLite不能靠裸文件复制保证一致。
3. 新建独立Conda，按锁安装依赖及普通wheel；不要覆盖旧环境/归档。LEAN/SDK为外部固定工具，轮子只带自有适配源码。
4. 在新目录恢复备份，先只读查看原事实及凭据。当前账本schema仍5，本次任务/输入元数据复用原表和文件，**没有启用schema6或虚构5→6迁移成功**。既有低版本schema升级由原事务迁移器处理，备份/回滚/重复迁移继续在完整回归覆盖。
5. 来源/规则/工具/依赖改变时旧运行可能严格阻断；这是保护已有事实的预期行为。另建当前版本实验，不改旧run的源码哈希、不把现有latest补成旧输入、不清空旧账本。
6. 旧ETF逐日证据完整且一致时可识别冻结依据；不完整/混用显示LEGACY_INPUTS_UNVERIFIED，保留只读历史，不能自动续跑或严格比较。

## 当前统一维护入口

运行状态页“v2.0 后台备份、核验、恢复与导出”会持久登记任务。CLI同样读取显式JSON请求：

```json
{"operation":"backup","destination":"/绝对路径/全新备份目录"}
```

```bash
python -I -m personal_quant workspace operation --workspace /绝对路径/工作区 --file /绝对路径/backup.json --request-id backup-001 --max-seconds 600
python -I -m personal_quant workspace tasks --workspace /绝对路径/工作区 --limit 20 --offset 0
```

提交返回不表示备份已完成，必须检查对应result.json。核验请求使用`{"operation":"verify","source":"/绝对路径/备份"}`；恢复使用`{"operation":"restore","source":"/绝对路径/备份","destination":"/绝对路径/全新恢复目录"}`。各用独立稳定request-id；重复相同请求返回原任务，不因刷新再执行。

完整备份可能包含自身仍在途的备份任务。恢复副本中的原owner不能直接转成成功；核实实际原任务已停止、备份manifest/恢复账户一致后，针对原始文件哈希显式登记人工核实。保留job/result/原始日志，核实不增加/删除任何资金事件。先看tasks/task-files，再用界面核实表单；不要手工修改原job.json。

旧`backup-bundle`依赖cwd的行为保留兼容；新workspace operation明确工作区，不要求操作者cd。恢复失败保留已创建目录及错误，先核实是否已产生恢复结果，再选择新的目标；不覆写非空目录。

## 保留、调度与Git

- 现有`backup-maintenance preview`按已核验备份显示保留/删除候选；显式保护ID用于被审计/恢复引用的包。未知、损坏或在途文件保留。managed-backup先新备份成功，再立即重验候选身份才轮换；不要直接按文件年龄删除运行目录。
- 调度仅`workspace schedule-preview --file ...`检查精确run/输入/源码/cron/预算，installed=false，不修改crontab。停用/恢复只针对精确LyraX tag行；历史回放定时运行仍不是自然前向。
- 首提交前审阅.gitignore及显式文件清单：源码、测试、配置模板、锁、文档、自有适配源码可审阅；runtime/reports、行情/账单/密钥/.env、Conda、SDK/LEAN构建、浏览器不入Git。当前未提交，无HEAD；不自动commit/tag/push。
- 源码包、普通wheel、SHA256清单及六类回执复制到独立备份介质；本地reports不属于Git自动交付。归档解包到全新目录，先运行release_v20 verify核验，外部工具另按版本准备。
