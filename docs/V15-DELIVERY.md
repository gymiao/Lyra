# LyraX v1.5 交付与验收

2026-10-10最终证据核对，Asia/Shanghai（运行证据采集于2026-10-09）。项目版本1.5.0，Python3.11.15/Linux x86_64/WSL。

## 已实现

- 六类月度只做多规则：固定配置、趋势、动量轮动、均值回归、波动率倒数、价格多因子。价值/质量复用多因子接口及标准PIT因子CSV；真实来源资格单独受阻。
- 注册表、不可变策略规格/修订、计算哈希、兼容旧/新信号解码、共同配置解析。模板/策略修订/实验成员分别标识，同模板多版本不覆盖。
- 同一bt/ffn扣费引擎支持基准加1至6候选；共同区间、资金、费用、完整月份、延迟成交。输出净值/回撤/交易/持仓/决策/现金占比及可追溯清单；不自动搜索参数或选择账户策略。
- 中文草稿/行情预检/版本差异/编辑/冻结/导入导出、后台研究提交/刷新/恢复、比较、账户绑定、因子导入；原四个主页面保留。
- 精确实验和独立attempt历史、跨提交幂等、单研究工作进程、原进程身份核验、文件/数据库/latest断点恢复及损坏报告保护。
- 月末版本截止、并发序号复核、旧在途占用保护、受阻切换不顺延、NO_ACTION月度记录及按账户绑定检查缺口。daily数据门槛使用绑定篮子/发布政策，旧成交仍按旧计划假设。
- 研究价格与执行原价独立引用；未核验原价阻断份额计划。示例入金、模拟成交及真实事件继续隔离，实际账本只由凭据更新。
- 显式v3迁移前完整备份，扩展因子/草稿/策略/实验/绑定/信号引用闭合，恢复到新空目录；可重建provider-cache和未发布产物排除。

## 实际验证

最终源码指纹：`770fa17584ce2ecf9d0da3728e8e7052c2b5cc3d12cf81928f9dda7be123a8c1`。最终全量、新41条CLI、旧数值兼容及浏览器证据对应此指纹；旧32条CLI单独标明较早源码。旧V1结果保留为历史基线。

| 验收 | 命令/结果 | 证据 |
|---|---|---|
| 新清洁Conda | 26包conda-forge显式锁离线创建 `.conda/v15-clean`；77包wheel SHA256锁安装；项目1.5.0editable安装；pip check通过 | reports/v15-validation/clean-conda-create.log、clean-pip-install.log、clean-project-install.log、clean-pip-check.log |
| 关键回归 | 清洁环境 `python -m pytest -q`：**231 passed、0 skipped，88.51s** | reports/v15-validation/clean-final-pytest.log |
| 新完整流程 | `python scripts/verify_v15.py --real-price-cache reports/manual-online/runtime/demo/data`：**41条CLI通过** | reports/v15-validation/91b39254ed444ff19bf34273c832e535/verification.json |
| 旧CLI兼容（较早源码830511334e9b6551e4696b56c46d5cd7172c0ecd100de60742ea5e934cc0811d） | 清洁环境 `python scripts/verify_offline.py`：32条通过，独立账本手算/重复导入/生命周期/daily/恢复通过 | reports/offline-validation/f6bca4d39a2f49a5ad25092f68c56761/verification.json |
| 旧引擎兼容 | 最终fixed/trend与开发前同一真实快照基线：全部数值CSV及指标一致 | reports/v15-validation/final-legacy.json；新run b0815697ee00439c96218afb600ec50d |
| 真实六策略复现 | 同一Yahoo快照及配置两次新attempt，指标和数值CSV一致；仅历史研究 | 新run ed43907b77f24739a30d2833e92a15c9及同目录第二次运行，端到端verification.json记录 |
| 模拟账户闭环 | 入金10000；月末绑定/信号/计划、下一交易日模拟成交、费用、结算及报告；重复计划和成交不记账 | 同端到端记录；结算现金630.0637177095350、净投入10000 |
| 因子/后台/恢复 | 后台合成价值/质量研究31c87ac267774d8999c5dcf29d110c8c明确mixed_test_factors；v3完整备份/校验/恢复通过 | 同端到端目录workspace和backup/restored；独立测试覆盖发布时间/修订/首次取得/过期/前向资格 |
| 实际目录升级 | 原研究目录完整备份后v2→v3，六模板研究b4246c0f40f74d01bf204e527e0253d6；账户/事件均0 | reports/v15-validation/current-workspace.json；原始迁移备份reports/manual-online/reports/v15-migrations/60e5d8e505b14868974bad64405c24f8 |
| 浏览器 | Chromium实际编辑/保存草稿/预检/冻结、后台提交、成功报告、刷新幂等及四页切换 | reports/v15-validation/browser/verification.json、real-research-workbench.png |

新增测试以独立手算和状态预期验证：权重/排名/边界、126收益需要127价格、未来数据不改变先前信号、未知规格/冲突、受阻月份不跳过、费用/公平条件、因子修订与时间、克隆/改名、迁移回滚、PID启动身份、发布两个断点、损坏恢复、月末截止/占用、NO_ACTION、绑定篮子及漏跑归属。原资金、分红/拆股、对账和执行测试继续通过。

## 启动与报告

```bash
conda activate "$PWD/.conda/lyra"
python scripts/verify_v15.py
lyra --config configs/demo.toml ui
```

已准备的真实行情研究看板：从项目根目录激活后进入工作目录启动：

```bash
cd reports/manual-online
lyra --config configs/research-current.toml ui
```

浏览器进入 `http://localhost:8501/?view=research`。更新源码/依赖后停止并重新启动服务，不能仅刷新浏览器。使用步骤、全部新增CLI与因子字段见[V1.5操作说明](V15-USAGE.md)。既有在线fetch流程见[README](../README.md)。

示例六策略报告：

- 实际工作目录：`reports/manual-online/runtime/demo/reports/research/b4246c0f40f74d01bf204e527e0253d6/report.md`。
- 清洁验证的真实行情：`reports/v15-validation/91b39254ed444ff19bf34273c832e535/real-price-research/runtime/demo/reports/research/ed43907b77f24739a30d2833e92a15c9/report.md`。
- 无密钥样本：`reports/v15-validation/91b39254ed444ff19bf34273c832e535/workspace/runtime/demo/reports/research/a9c4fced2c824531bd9d881d2ff4b727/report.md`。

行情来源为此前实际验证的Yahoo下载，数据2023-01-03至2026-10-08、2835行、每标的945日。评估2024-07-01至2026-10-08，571个日线观察。此次复现使用冻结缓存，不宣称重新下载了行情。固定规则/95%预算在观察新研究结果前定义，未搜索最优参数。V1原有100%固定配置仍保持原数值。

## 已解决的失败与限制

- 真实缓存完整升级初次失败：provider-cache被误当作快照。已排除可重建缓存、补测试，并在真实目录升级及完整流程复验。
- 新清洁前缀首次遇默认Anaconda频道ToS检查。使用明确conda-forge频道与已验证锁/缓存完成安装，未自动接受其他频道条款。
- 旧持续服务缓存V1模块导致decode_signal导入失败。停止原服务后重启新版本；文档明确升级重启步骤。浏览器脚本等待表单切换完成后再输入，避免在旧DOM上填字段。
- 真实价值/质量来源**尚未取得合格样本**。缺少适用于所选证券的定义、来源权限、历史发布/修订、估值日期和首次收到证据；保持UNQUALIFIED/MISSING受阻状态。合成ETF因子是工程测试，不能证明真实ETF有这些基本面字段。
- Yahoo Close为供应商拆股调整口径，研究可用，实际份额计划须另提供核验原价/行动、分红支付及税费。真实费用、交易单位、结算、风险、入出金和券商对账还需要用户资料；无真实账户交易或真实前向收益验收。
- 每个目录单研究工作进程，无任务队列、自动券商下单或已部署cron。反复改变参数仍属于观察历史探索，不成为独立未见评估。
- V1.5模板无逐步账户记忆；短卖、杠杆、套利/市场中性、多币种、多市场、复杂行动、机器学习和自动交易仍在后续范围。仅验证Linux x86_64/WSL/Python3.11，其他平台需重验锁文件。
- 未提交/推送Git，原有文件保留；GOAL不变。模型/API详细用量和实际费用未获取，不编造账单。

## 下一阶段输入

实际投资跟踪需要：选定市场/证券、可用的核验执行原价/公司行动源、账户费用/单位/结算/风险配置、实际资金与成交CSV、独立券商快照。真实价值/质量研究需要满足PIT契约的合格来源及权限。自动交易V2还需要券商、官方接口/API权限及明确开发请求；软件开发不构成真实自动下单授权。

最后逐条对照计划补齐独立草稿保存、预热/首个决策及成交日预检、版本差异和价格CSV预检导入；调仓页支持独立研究/执行快照。补齐后重新执行清洁环境231项全量、新41条CLI、最终旧数值兼容及实际浏览器，源码指纹一致。新测试还覆盖独立两来源原价数量及草稿备份恢复。实际研究目录最后完整备份位于reports/v15-validation/current-final-backup（不含外部密钥/原始凭据）。

2026-10-10最终只读核对：代码指纹、最终测试/41条CLI/浏览器/旧数值兼容一致；完整备份168个文件哈希全部匹配，看板健康检查HTTP200。汇总记录：`reports/v15-validation/final-verification.json`。旧32条CLI保留较早源码证据，未混称最终源码验收。
