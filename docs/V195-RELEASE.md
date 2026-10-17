# v1.95 发布与提交准备

当前发布版本1.95.0，业务源码3a057618cbe19480abeddba7f3292db263800833cf4e49a91da25f1cbb6ac18d。本地S0–S7验收完成；真实账户暂缓，外部来源与自然前向未验。本文件不触发Git操作。

## 发布身份

- Python/C#自有源码、策略规格、模板、5份依赖/发布文件与验证入口均随源码保留。
- 普通wheel：reports/v195-validation/release-wheel-3a05/wheels/lyra_personal_quant-1.95.0-py3-none-any.whl。
- wheel SHA256：e776195007a493ecc22b8fe09136efe8989446016d98e4713194fa58858ef335。
- 清洁安装身份及依赖检查：同目录installed.json；C#资源只读，不在site-packages编译。
- 完整回归保存440项输入哈希，最终verification.json确认完整1045项、无跳过/xfail且输入未变。
- 最终发布归档/manifest在验收及文档完成后生成，文件名与核验范围见下节。

## Git准备清单

当前main无HEAD，文件未提交；没有可推送的提交/标签。不执行commit、tag或push。用户将来明确授权后，可依次审阅并提交以下组，任何一组提交前先检查实际diff：

1. 项目元数据：.gitignore、pyproject.toml、environment.yml、Conda与两份pip锁。
2. 业务及适配：src/personal_quant、engines/lean内自有C#项目与源码。
3. 可复现输入：configs内工程样例、examples内小型固定测试样本、templates。
4. 验证：tests、scripts。
5. 文档：README.md、agents.md、docs；GOAL.md仅保留用户原始内容，不作为本轮修改。

标签建议为v1.95.0，但须在实际审阅/提交并重新核对发布清单后再创建。没有HEAD时，以业务源码指纹和逐文件SHA256识别版本，不虚构提交号。

## 不提交与不分发

.gitignore排除reports、runtime、.conda、.tools、SQLite/WAL/SHM、日志、密钥、local配置及编译输出。实际行情、真实账单、SDK、LEAN工具副本、浏览器及本机字体不纳入Git或项目wheel。当前未忽略候选文件均不足1MiB，完整清单须在最终交付前再核对。

源码与wheel无需真实账号；LEAN/SDK作为单独明确版本的本地工具准备。开源代码、行情使用权与券商权限分别核验，见[依赖许可](DEPENDENCIES.md)。没有自动下单或付费开通。

## 升级与回退

停止自有任务→完整备份→实际核验→新目录恢复演练→独立环境安装→新建模拟实验。历史账本和只读报告保留；源码变化时不在原run_id上静默继续。回退使用原源码/锁/工具身份和对应备份，不用旧程序直接写入未知新schema。

## 最终本地发布产物

目录：`reports/v195-validation/release-final/`（不提交Git）。

- `lyrax-1.95.0-source.tar.gz`：候选文件白名单的源码、测试、样例、模板、锁和文档；无运行数据、数据库、SDK或浏览器。
- `lyra_personal_quant-1.95.0-py3-none-any.whl`：已清洁安装验证的同一普通wheel。
- `lyrax-1.95.0-validation.tar.gz`：完整/核心逐阶段日志、收集清单、输入哈希及本轮安装/浏览器/真实ETF/恢复/兼容/新策略证明。
- `manifest.json`：业务指纹、全部源码文件及证据SHA256、归档/wheel哈希、实际测试范围；没有HEAD则明确null。
- `SHA256SUMS`：除自身外上述交付文件的SHA256，可在该目录执行`sha256sum -c SHA256SUMS`验证。

归档生成后逐成员读回并对原文件SHA256；wheel内Python、自有C#和5份锁/发布资源逐字节与当前文件核对。源码归档包含创建工作区所需的configs/examples，真实行情通过在线流程重新获取。验证归档只证明本轮运行，不向新环境伪授引擎/来源资格；当地重新构建及资格核验仍适用。
