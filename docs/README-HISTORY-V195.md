# LyraX 个人量化投资系统

中文日线研究、月度策略、模拟跟踪、调仓建议及账户账本。Python 3.11.15，Linux / WSL；ETF研究复用bt/ffn，期权机械模拟复用固定版本LEAN，界面为Streamlit。

**v2.0（2.0.0）编码已进入最终验收，尚未宣称整版完成。** 新增冻结输入与任务恢复、通用多月场景、研究协议、只读资金分配、铁鹰/铁蝶完整模拟及后台维护。当前状态见[PROGRESS](docs/PROGRESS.md)，使用入口见[V20-USAGE](docs/V20-USAGE.md)，范围见[v2.0计划](docs/lyraX-v2.0.md)。

v1.95历史验收与归档保留：[V195-DELIVERY](docs/V195-DELIVERY.md)。下方v1.95路径是历史可复现入口；v2.0候选和最终证据单独保存，不覆盖旧发布。真实账户已暂缓，真实期权来源及自然前向仍未验证。

用户选择先使用模拟账户。工程样例的资金和期权数据明确为合成，真实行情研究单独存放；没有券商自动下单接口。

## 安装

选择新的Conda前缀；已有本机验证环境`.conda/v195-clean-install`可直接使用。依赖锁适用于Linux x86_64 / CPython 3.11：

```bash
CONDA_NO_PLUGINS=true CONDA_SOLVER=classic conda create --prefix "$PWD/.conda/v195-clean-install" --file conda-linux-64.lock --no-default-packages --yes
conda activate "$PWD/.conda/v195-clean-install"
export PYTHONNOUSERSITE=1
python -m pip install --require-hashes -r requirements-linux-py311.lock -r requirements-options-linux-py311.lock
python -m pip install --no-deps reports/v195-validation/release-wheel-3a05/wheels/lyra_personal_quant-1.95.0-py3-none-any.whl
```

上面的wheel路径为本机已生成发布包；新机器需一并复制wheel、锁文件和仓库内的configs示例目录，不能假设Git仓库包含本地验收产物。完整源码归档提供CLI/测试及样例输入。源码构建在可写暂存目录完成，避免本机沙箱大小写路径限制。

当前实际验证使用26包显式Conda锁、本地哈希wheel缓存及普通项目wheel独立安装，非共享base依赖；`-I`导入和pip check通过。发布包与来源清单：`reports/v195-validation/release-wheel-3a05/`。安装细节及本机大小写路径限制见[环境说明](docs/ENVIRONMENT.md)。

## 首次ETF模拟

以下流程无需密钥，创建独立的100000 USD模拟资金账户。工作区应选择新路径；相同规格重复初始化不再入金。

```bash
python -I -m personal_quant --config configs/demo.toml workspace init --workspace reports/my-v195/etf --spec configs/v195-etf-workspace.json
python -I -m personal_quant workspace status --workspace reports/my-v195/etf
python -I -m personal_quant simulation start --workspace reports/my-v195/etf
```

将start返回的run_id填入后续命令：

```bash
python -I -m personal_quant simulation batch --workspace reports/my-v195/etf --run-id <run_id> --through 2024-12-31 --max-sessions 256 --max-seconds 3600
python -I -m personal_quant ui --workspace reports/my-v195/etf --port 8501
```

看板前台启动后访问`http://localhost:8501`；Ctrl+C退出。文档中的地址不表示后台服务已安装。查看日期只改变展示，不推进模拟。

## 期权模拟

12种月度模板、持续持股滚动、Wheel状态、公共计划/预留、生命周期和异常恢复的实际边界见[支持矩阵](docs/V195-SUPPORT-MATRIX.md)。固定两月合成配置可由中文向导或CLI冻结：

```bash
python -I -m personal_quant --config configs/demo.toml workspace init --workspace reports/my-v195/options --spec configs/v195-options-workspace.json
python -I -m personal_quant simulation prepare --workspace reports/my-v195/options --file configs/v195-option-setup.json
python -I -m personal_quant ui --workspace reports/my-v195/options --port 8501
```

期权执行还需[V19-USAGE](docs/V19-USAGE.md)中匹配的LEAN Launcher与.NET SDK 10.0.100；普通wheel包含自有C#适配源码，不捆绑整个SDK/LEAN。界面选择已冻结配置，显式填写本地工具路径后建立/推进。CLI格式、成交/费用/结算和真实资格要求见[操作说明](docs/V195-USAGE.md)及[期权规则](docs/V195-OPTION-RULES.md)。

已验证的完整安装流程：`reports/v195-validation/installed-3a05/verification.json`，ETF完整/重复和期权prepare→开平→结算/重复均通过；期权7笔事实、99978 USD。它是工程样例，不是收益承诺或实际账户记录。

## 真实行情研究

Yahoo实际数据独立于合成工作区。当前源码通过下载、增量重跑及固定快照双策略复现；截至2026-10-15，证据`reports/v195-validation/online-3a05/verification.json`，报告路径记录在该文件中。

原始数据来源、下载时间、版本和价格口径随快照保存。Yahoo拆股调整Close不直接计算真实证券份额；实际期权链/使用权、核验原价及真实账户权限仍须分别验证。不会用合成结果解除这些检查。

## 日常、恢复和维护

- [操作路径与CLI](docs/V195-USAGE.md)：首次模拟、日常使用、失败恢复、增加策略、迁移与工具换路径。
- [计划与验收范围](docs/lyraX-v1.95.md)：S0–S7，包含新增期权闭环。
- `workspace diagnostic`导出白名单元数据；不含账单、密钥、投资参数或数据库。
- `workspace backup-review`和`workspace recovery-drill`实际核验并记录时间；状态页不在刷新时重验全部备份。
- `backup-maintenance`提供清单/预览/显式轮换。行情、原账单和历史实验不按年龄自动删除。
- 调度使用系统任务调用CLI；模板存在不表示已经安装或完成自然前向观察。

## 开发与验证

```bash
python scripts/check_v195.py --scope core --destination reports/check-core-new
python scripts/check_v195.py --scope release --destination reports/check-release-new
```

目标目录必须是新的。release需要本地原生工具，完整回归不接受跳过；保存源码、锁、输入和结果。通过LYRAX_TEST_ENGINE_ROOT/LYRAX_TEST_DOTNET可显式选择经过内容核验的工具副本；LYRAX_ADAPTER_CACHE为可选的哈希校验构建缓存，每个业务输入仍独立运行。

大行情、真实账单、密钥、运行目录、Conda和SDK均不提交Git。当前没有Git提交/推送；旧版本验收与技术说明保留在[V1](docs/DELIVERY.md)、[v1.5](docs/V15-DELIVERY.md)、[v1.8](docs/V18-DELIVERY.md)、[v1.9](docs/V19-DELIVERY.md)和[旧README](docs/README-HISTORY-20261016.md)，历史测试数量不作为当前版本验收。
