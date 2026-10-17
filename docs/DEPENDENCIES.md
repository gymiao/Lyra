# 依赖来源、许可证与验证状态

## v2.0 安装环境（2026-10-17）

版本2.0.0，独立Conda `.conda/v20-clean-install`，Python3.11.15；基础/QuantLib/Conda锁与v1.95归档逐字节一致，没有新增重叠回测框架或收费依赖。当前r5普通wheel已安装，pip check与185个Python文件/自有C#来源核验通过，见`reports/v20-validation/installed-final-r5/verification.json`。14模板及未验证边界见[V20支持矩阵](V20-SUPPORT-MATRIX.md)。Playwright1.62.0与Chromium151仅作隔离验收工具，不是运行依赖。

只读应用补验位于Linux /tmp的venv，依赖来自上述独立Conda；实际应用/自有适配目录不可写且原生三周期通过。WSL/DrvFS仅chmod未阻止写入的失败保留，不把它称为已验证的只读文件系统。

## v1.95 历史发布环境（2026-10-16）

基础锁仍为77包，另加QuantLib1.43，共78个哈希锁定发行包；Conda基础为26包显式锁。当前普通wheel独立安装于`.conda/v195-clean-install`，未共享base；安装身份和pip check见`reports/v195-validation/release-wheel-3a05/installed.json`。ETF抽象组合复用bt/ffn，含期权组合复用固定LEAN；单个组合不拼接两个引擎净值。当前12模板、原生资格和模拟边界见[V195支持矩阵](V195-SUPPORT-MATRIX.md)，下文“只有引擎烟雾”是v1.9初始阶段的历史记录。

wheel只分发本项目Python、自有C#适配源码和5份依赖/发布文件；LEAN、SDK、本机浏览器、Windows字体、行情缓存、账户和密钥均不随包分发。许可证依据仍为固定版本本地元数据与源码LICENSE；没有升级依赖或开通收费服务。

## V1及v1.9依赖验证历史

2026-10-09。Python 3.11.15；直接依赖在 `pyproject.toml` 精确固定，77个直接/传递发行包在 `requirements-linux-py311.lock` 按版本及实际 wheel SHA256 锁定。目标为 Linux x86_64 / CPython3.11；本机独立 Conda 清洁前缀已重装、导入及 `pip check` 通过。其他平台不能直接沿用平台 wheel 哈希，需要另行验证锁文件。

| 依赖 | 来源 / 用途 | 实测版本 | 许可证依据 |
|---|---|---|---|
| pandas | [项目](https://pandas.pydata.org/) / 数据处理 | 2.3.3 | BSD-3-Clause，本地发行元数据 |
| NumPy | [项目](https://numpy.org/) / 数值计算 | 2.4.6 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0，本地License-Expression |
| PyArrow | [项目](https://arrow.apache.org/) / Parquet | 24.0.0 | Apache-2.0，本地License-Expression |
| bt | [官方文档](https://pmorissette.github.io/bt/) / 唯一主回测 | 1.3.0 | MIT，本地发行元数据 |
| ffn | [官方文档](https://pmorissette.github.io/ffn/) / 绩效、回撤和年化 | 1.3.0 | MIT，本地License-Expression |
| Streamlit | [官方文档](https://docs.streamlit.io/) / 四页看板 | 1.65.0 | Apache-2.0，本地License-Expression |
| yfinance | [项目](https://ranaroussi.github.io/yfinance/) / Yahoo下载 | 1.7.0 | Apache-2.0，本地发行元数据 |
| exchange-calendars | [项目](https://github.com/gerrymanoim/exchange_calendars) / XNYS交易日历 | 4.13.2 | Apache-2.0，本地License-Expression |
| pytest | [官方文档](https://docs.pytest.org/) / 回归测试 | 9.1.1 | MIT，本地License-Expression |
| pyxirr | [项目](https://github.com/Anexen/pyxirr) / 可选个人现金流回报 | 0.10.8 | Unlicense，本地元数据和classifier |
| SQLite | [官方许可](https://www.sqlite.org/copyright.html) / Python sqlite3事务账本 | 随Python运行库 | SQLite核心为公有领域；Python发行许可另随其发行 |

实际元数据、发行版本及依赖路径记录在 `reports/environment/clean-20261009/imports.json`。锁文件包含 pytest 与 personal-return 扩展；本项目源码另以 editable 安装，不把本项目源码目录当作其他环境污染。环境和 wheelhouse 不提交Git。

源码许可不授予 Yahoo 行情使用权；适配器用于个人研究演示，不承诺数据免费、可商用或持续可用。实际下载未使用收费接口或密钥。Close是供应商拆股调整口径，不自动认证为实际成交价；分红支付日需凭据/CSV补齐。行情权限、券商接口及代码许可分别评估。

Playwright/Chromium仅用于本机验收，放在 `/tmp` 或既有浏览器缓存；不加入应用依赖。缺少的浏览器动态库仅解包到 `/tmp`，中文字体只引用本机已有字体进行测试，不在项目中分发字体或修改系统安装。日常计算与信号不调用大模型。

## v1.9新增隔离工具（2026-10-10）

- QuantLib 1.43：Python可选options扩展；本地发行元数据为BSD-3-Clause，官方Linux abi3 wheel经实际下载SHA256锁定于requirements-options-linux-py311.lock。用途仅理论定价/Greeks/IV，不替代成交报价或回测引擎。
- LEAN：官方仓库固定80e7843f645673bcbeaab963049f76f20f6785e1，源码LICENSE为Apache-2.0；项目内.tools/lean隔离克隆和编译，未修改第三方核心；官方附带期权样例实际运行。官方CLI的商业条件和行情授权与源码许可分别处理，当前没有安装收费CLI或购买数据。
- .NET SDK10.0.100：官方脚本安装于.tools/dotnet，工具目录不提交。LEAN编译通过但上游NuGet依赖存在审计警告，保留lean-build.log；本次只验证隔离样例，不承诺其依赖已适合生产账户。
- ETF历史研究仍使用bt；未来期权混合研究通过LEAN适配。现阶段只有LEAN引擎烟雾验证，不能把官方回归样例当成LyraX八策略验收。

新增清洁环境为.conda/v19-clean，原环境不升级；77个基础发行包保持旧哈希锁，QuantLib单独锁。安装失败历史和成功重试日志保留于reports/v19-implementation/。没有全局软件修改或付费授权。
