# LyraX 个人量化投资系统

**整体需求仍有未完成项：** 见[未完成能力清单](docs/UNFINISHED-FEATURES.md)。v2.0限定范围完成不等于全部路线图完成；待开发与待外部验证分开追踪。

中文日线研究、月度策略、模拟跟踪、调仓建议、账户记录及四页看板。Python3.11.15，Linux / WSL；ETF回测复用bt/ffn，期权模拟复用固定版本LEAN，模型报价使用QuantLib。

**当前2.0.0：v2.0本地P0–P8编码及验收完成。** 完整1110项逐阶段覆盖，无跳过/xfail；独立Conda普通wheel、真实ETF研究/固定快照复现、实际浏览器及完整恢复均通过。完整回归包含按源码/测试作用域和哈希核验的阶段续跑，原失败/取消整轮保留。证据及边界：[PROGRESS](docs/PROGRESS.md) · [验收](docs/V20-ACCEPTANCE.md) · [交付说明](docs/V20-DELIVERY.md)。真实账号已暂缓，没有券商自动下单。

## v2.0 功能

- ETF多类规则与扣费回测；固定用途输入、日检查点和实际版本比较。
- 通用数据包/CSV预览导入；可配置多月价格/IV模型场景，完整期权链与可用时点核验。
- 14种月度期权模板，新增铁鹰、铁蝶；持续持股滚动与按实际交割切换的Wheel。
- 预声明开发/评估窗口、成本压力和同资本股票/现金基准，不自动搜索参数。
- 持久后台任务、稳定请求、总预算、阶段记录、人工核实/重试、任务索引。
- 四页工作台、独立实验窗口、后台备份/恢复/导出、只读多策略资金预演。

真实ETF研究、合成样本、模型期权、历史回放、模拟账本和真实账户分开标识。示例资金不是用户资产；工资/奖金入金不计为投资盈利。

## 安装

使用新的Conda前缀，依赖锁适用于Linux x86_64 / CPython3.11。当前实际独立安装环境`.conda/v20-clean-install`，不共享base依赖。

```bash
CONDA_NO_PLUGINS=true CONDA_SOLVER=classic conda create --prefix "$PWD/.conda/v20-clean-install" --file conda-linux-64.lock --no-default-packages --yes
conda activate "$PWD/.conda/v20-clean-install"
export PYTHONNOUSERSITE=1
python -m pip install --require-hashes -r requirements-linux-py311.lock -r requirements-options-linux-py311.lock
python -m pip install --no-deps reports/v20-validation/release-final/wheel/lyra_personal_quant-2.0.0-py3-none-any.whl
python -I -m pip check
```

wheel为本地构建产物，不在Git中；新机器需复制普通wheel、锁、configs及源码验证脚本。完整源码归档包含代码/配置/测试/文档，第三方LEAN/SDK另行准备。构建可用`python -m pip wheel --no-deps --no-build-isolation --wheel-dir /新目录 .`，发布与验收见V20-USAGE。WSL本机写入使用小写路径`/mnt/c/quant/project/lyra`；历史归档不覆盖。

## 无密钥ETF模拟

选择全新目录；样例入金100000USD仅属于模拟账户。同规格重复初始化不重复入金。

```bash
python -I -m personal_quant --config configs/demo.toml workspace init --workspace reports/my-v20/etf --spec configs/v195-etf-workspace.json
python -I -m personal_quant workspace status --workspace reports/my-v20/etf
python -I -m personal_quant simulation start --workspace reports/my-v20/etf
```

用返回的`run_id`推进；交易日、时间和磁盘预算分别生效，预算停止不表示全部完成。

```bash
python -I -m personal_quant simulation batch --workspace reports/my-v20/etf --run-id <run_id> --through 2024-12-31 --max-sessions 256 --max-seconds 3600
python -I -m personal_quant ui --workspace reports/my-v20/etf --port 8501
```

前台启动后打开`http://localhost:8501`，Ctrl+C退出；地址不表示已经安装常驻服务。四页：账户总览、策略研究、调仓计划、运行状态。查看日期与刷新不推进模拟。

## 三周期期权完整演示

先准备固定LEAN Launcher及.NET10.0.100。支持外部/空格路径，不要求仓库存在.tools；自有C#适配源码随wheel提供，第三方核心源码不修改。

```bash
export LYRAX_TEST_ENGINE_ROOT='/绝对路径/LEAN'
export LYRAX_TEST_DOTNET='/绝对路径/dotnet'
python -I scripts/verify_v20_quarter.py --destination /绝对路径/新的三月演示目录 --engine-root "$LYRAX_TEST_ENGINE_ROOT" --dotnet "$LYRAX_TEST_DOTNET"
```

该脚本实际执行8条公开CLI：生成并核验多月非恒价模型输入、建立独立工作区、冻结3周期long_call、启动/批次/重复及诊断。固定样本7事件/99633USD是工程断言，不是收益目标。看板打开生成的`workspace`子目录即可。

14模板、滚动/Wheel配置和资金预演见[V20-USAGE](docs/V20-USAGE.md)、[支持矩阵](docs/V20-SUPPORT-MATRIX.md)。铁鹰/铁蝶按全额履约资金保守预留，不假设经纪商组合保证金；不完整报价/未结算/未解决对账差异阻断新增风险。

## 真实行情研究与独立离线核对

Yahoo实际ETF下载与bt研究单独存放，行情截至2026-10-16；当前源码2853行、9CSV固定快照复现通过，见`reports/v20-validation/online-r4/verification.json`。真实期权尚无供应商/使用权验证；Yahoo拆股调整Close不直接计算真实证券份额。

独立手算账户核对（无需密钥，不修改已有工作区）：

```bash
python scripts/verify_offline.py
```

当前源码的结果在`reports/offline-validation/latest.json`所指目录；报告包含入出金、分红/拆股、费用、计划、实际模拟成交及重复导入核对。真实账户仍为空，不把模拟账单写成实账。

## 维护和开发

- [V20-USAGE](docs/V20-USAGE.md)：输入、任务预算、研究协议、四腿规则及验证命令。
- [V20-MIGRATION](docs/V20-MIGRATION.md)：完整备份、异目录恢复、旧输入阻断、人工核实、调度预检和首提交审阅。
- [V20-SUPPORT-MATRIX](docs/V20-SUPPORT-MATRIX.md)：当前能力及未开放场景。
- [DECISIONS](docs/DECISIONS.md)：数据/成交/资金/依赖口径。
- [依赖及许可证](docs/DEPENDENCIES.md)：代码许可证与行情使用权分别评估。

```bash
python scripts/check_v20.py --scope fast --destination /绝对路径/新的快速验证目录
python scripts/check_v20.py --scope release --destination /绝对路径/新的完整验证目录 --timeout-seconds 28800
```

快速组当前60项28.05秒；不能替代完整发布门禁。最终发布必须全部节点逐阶段覆盖、无跳过/xfail并保持输入不变。未知旧单进程pytest -11根因未定，失败记录保留。

E1真实期权源、E2自然前向/实际调度、E3同账户多策略执行独立未验证；多策略只有只读预演。跨期/对角、非标准合约、卖空、多币种和自动交易需单独立项。未自动安装调度、购买服务、外发账户材料或Git提交。模型/API/工具实际费用未获取。

历史交付：[v1.95](docs/V195-DELIVERY.md) · [v1.9](docs/V19-DELIVERY.md) · [v1.8](docs/V18-DELIVERY.md) · [v1.5](docs/V15-DELIVERY.md)；旧归档保持原样。
