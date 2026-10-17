# v2.0规划阶段（历史）

## 本轮：v2.0规划（已完成文档，编码未开始）

- 用户要求继续审查并形成v2.0计划；已写[lyraX-v2.0.md](lyraX-v2.0.md)。本版本号不启动原GOAL券商自动交易，真实账户继续暂缓。
- 沿用上一轮3项复现：日历4日预算实际5检查点、坏任务记录阻断列表/提交、发布入口忽略外部SDK；启动登记窗口仅故障注入确认。尚未修复业务代码。
- 本轮新增实际复现：ETF同run_id混用前后快照，比较仍声明旧快照；父进程-I但工作区子进程加载继承PYTHONPATH中的无害sitecustomize。均仅临时模拟账户，只有初始入金。
- 实际命令：`MPLCONFIGDIR=/tmp/lyrax-review-mpl PYTHONNOUSERSITE=1 .conda/v195-clean-install/bin/python -I reports/v20-planning/reproduce-input-binding.py`和同目录`reproduce-worker-environment.py`，均退出0。首个脚本曾把SQL列output误写outputs，修正复现脚本后成功，不算产品错误。
- 计划固定P0–P8本地范围：修复→输入/任务契约→数据/场景→中文工作台→期权研究→资金分配预演→铁鹰/铁蝶完整模拟→维护/验收。真实源、自然paper、多策略执行等条件分支独立标注。
- 仅修改计划及README/agents/PROGRESS/DECISIONS；业务、测试、配置、依赖锁、GOAL不改，未重跑1045项。链接/阶段映射/保护文件结果见`reports/v20-planning/verification.json`。
- 下一项：用户要求编码时，先将R20复现转正式回归并实施P0；当前不启用新策略、不安装调度、不提交Git。

