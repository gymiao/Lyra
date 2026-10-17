# LyraX v1.8 交付记录

2026-10-10（Asia/Shanghai）。版本1.8.0；P0–P5核心工程交付完成。实际资金执行、基本面来源资格、长期前向和自动交易单独列明，未以测试替代外部凭据。

## 已交付

1. D01修复：signal/execution/valuation/factor显式用途、独立系列与不可变快照；月度绑定和旧fixed/trend规则、daily、CLI、UI、模拟、估值和对账共享解析。长期研究数据不会被近期原价导入顺序覆盖。
2. D02修复：价格/因子读合并发布使用线程及进程文件锁；保留首次收到时间，同批次幂等，坏快照不替换有效头；与报告发布和备份协作。
3. v4备份迁移、乐观用途修订、失败回滚和完整恢复，旧实验/报告继续可读。
4. 白名单源码+锁+输入+报告研究包；校验/还原与执行分开；原实现隔离重算、依赖及额外文件校验。
5. 固定规则分段、成本压力、协议登记；后台子实验、明确INCOMPLETE、限额、成功复用与中断恢复；独立窗口汇总及连续持仓年度切片。
6. 只读执行复盘与CSV，实际/建议数量、参考价差、估计/实际费用、拆股/冲销、修订与未关联/异常关联成交。
7. doctor、去重本地提醒和确认/解决/再次发生状态；四页中文集成、Linux/WSL调度模板；模板未安装。

源码最终指纹：`1437f4c6dc8fd8ccbc1af71cf0a7b23fd4acc3bcc0ecbfd2fa7fc94c0b56381b`。GOAL保持原SHA256：`4d5112d886f784ca8f9c962342ff7c0a6ca9c841ae3129e5b35b84e486b9d31c`。仓库main尚无提交；源码/锁文件归档提供无提交条件下的复现依据。

## 实际执行证据

| 检查 | 结果 | 文件 |
|---|---|---|
| 清洁Conda | 新`.conda/v18-clean`，26个显式基础包、77个SHA256锁定依赖，安装1.8.0；pip check无冲突；主要库导入成功 | reports/v18-implementation/clean-conda-final.log、clean-pip.log、clean-project.log、clean-check.log、clean-import-final.log |
| 最终全量 | **257 passed，无跳过**；包含并发、双来源、资金、费用、分红/拆股、时点、预留、对账、迁移回滚、归档、套件恢复与输入拒绝 | reports/v18-implementation/accepted-tests.log |
| v1.8完整CLI | **34条通过**；新目录研究包重算、后台套件、测试入金/对账/计划/模拟/复盘、备份恢复 | reports/v18-implementation/accepted-cli.log；reports/v18-validation/latest.json |
| 旧流程兼容 | **32条通过**，手算账户、生命周期、幂等、daily和恢复 | reports/v18-implementation/accepted-legacy-cli.log；reports/offline-validation/0bea518d875c42678c0912ac3094eb71/verification.json |
| 真正v1.5实现重算 | 旧源码770fa175…的原报告，归档后用旧代码在新目录重算；净值、交易、回撤CSV和指标精确相同 | reports/v18-implementation/legacy-replay-comparison.json、legacy-package-replay.json |
| 新在线下载 | Yahoo增量请求成功，2835行，SPY/IEF/GLD，2023-01-03至2026-10-08；来源real_market、provider_split_adjusted | reports/v18-implementation/online-update.log |
| 最终真实行情验证 | 两窗口×两成本×两成员，4个子实验成功；无账户资金/计划写入 | reports/v18-implementation/accepted-real-validation.log |
| 实际工作区升级 | 完整v3备份后v4，明确signal绑定；accounts/events/plans均0 | reports/v18-implementation/actual-migration.json、actual-binding.json |
| 浏览器操作 | 真实行情四页、demo复盘CSV下载/提醒、用途绑定/后台验证/研究包导出；刷新及重启后账户事实不增加 | reports/v18-implementation/browser/verification.json、demo-verification.json、actions-verification.json；截图及accepted-*.log |

早期日志保留包括失败复现、开发中的SQL/导入错误、Conda默认channel ToS拒绝与浏览器缺动态库等；已分别修复或使用已锁conda-forge渠道/现有浏览器库验证。最终证据按上述文件及源码指纹判断，不能将旧250项、早期源码和规划检查混成最终验收。

## 启动与报告

- 安装及统一CLI：[README](../README.md)。新安装验证环境为`.conda/v18-clean`；既有`.conda/lyra`可按锁及editable安装更新项目版本。
- 无密钥：`python scripts/verify_v18.py`，自动生成隔离演示；详细入口及占位符说明见[操作说明](V18-USAGE.md)。
- 真实行情工作区：进入`reports/manual-online`，使用`configs/research-current.toml`。`lyra --config configs/research-current.toml ui`启动默认8501；本轮检查使用8503，避免占用已有服务。
- 已生成的示例报告由`reports/v18-validation/latest.json`和最终真实行情日志指向。`runtime/demo/reports/validation/<suite_id>/summary.csv`及每个子实验的report.md/nav.csv/trades.csv可直接核对。
- 数据/锁/迁移/资金边界见[契约](V18-CONTRACTS.md)、[决策](DECISIONS.md)和[备份恢复](OPERATIONS.md)。

## 本次报告位置

- [离线演示研究报告](../reports/v18-validation/f98a93e65870430ca8209497d7531611/workspace/runtime/demo/reports/research/53c9da8459f14a199e76dc61ffe5088a/report.md)。
- [离线套件汇总](../reports/v18-validation/f98a93e65870430ca8209497d7531611/workspace/runtime/demo/reports/validation/3093b82217519829d4da22f1bb21821f1e736de0789417181c5710c078a5c97b/summary.csv)。
- [真实行情套件汇总](../reports/manual-online/runtime/demo/reports/validation/cd1ddb4f3f1c5dab2ab824f7c2f9a7d283489ec0ffe131fd2269c3b51c5498d3/summary.csv)，以及[第一子实验报告](../reports/manual-online/runtime/demo/reports/research/582f242e74ff457c9e8b13f07eabcbdb/report.md)。
- [最终证据清单](../reports/v18-implementation/delivery-integrity.json)。

## 已知限制与下一阶段输入

- Yahoo当前价格为供应商拆股调整单位，适合标注后的研究；没有核验原价凭据，实际工作区execution/valuation未分配，doctor如实BLOCKED，不制造可执行计划。
- 真实基本面需要来源/权限、定义、历史发布时间、修订和首次收到凭据；当前合成因子只用于测试。每个工作区固定一套因子来源/定义，换来源用独立工作区。
- 协议验证报告属于历史重建；未来登记仅锁定本项目规则，不证明其他地方未观察数据。真实前向需要独立paper、合格原价和持续归档，不能今天补造过去信号。
- 分段从同额现金独立开始，不拼接净值、不自动选赢家；连续切片保留持仓。抽象复权份额不等于证券份额，参考价差不等于精确券商滑点。
- 源码/输入包可同平台重算，不包含安装wheel缓存；缺旧源码报告仅可查看。外部导出包、券商原始凭据与密钥另行备份。
- 调度模板未安装，长期运行证据未获取；本地提醒不发送外部消息。没有自动下单或券商接口。
- 下一阶段实际使用需明确市场/篮子、券商与脱敏账单/快照、资金事件、费用/交易单位/结算/风险参数及合格原价/公司行动。V2另需明确自动交易请求及接口权限。
- 费用统计：模型输入/缓存/输出/推理token、套餐用量及API实际费用均**未获取**，没有购买数据或开通收费服务；日常计算由Python执行，不依赖模型调用。
