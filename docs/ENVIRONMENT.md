# Conda 环境、依赖锁与恢复会话

## v1.95 当前候选环境（2026-10-16）

当前普通wheel验证前缀为`.conda/v195-clean-install`，Python3.11.15、26包Conda显式锁与全部哈希wheel独立安装；-I导入不加载用户site或其他前缀，pip check通过。业务源码3a057618…，版本1.95.0；当前证据见reports/v195-validation/release-wheel-3a05与installed-final，最终全量尚未通过。

源码构建使用可写暂存目录，安装普通wheel到明确的小写--prefix，避免本机沙箱把大小写别名解析为只读路径。没有修改全局权限。下文2026-10-09的前缀和180项数量属于V1历史记录。

2026-10-09。主环境 `.conda/lyra`，先前清洁环境 `.conda/verify-install`、最终清洁环境 `.conda/readme-install`；Python3.11.15，Linux x86_64 / WSL。原 `.venv` 仅保留历史，不加载其依赖。

## 使用现有环境

```bash
conda activate "$PWD/.conda/lyra"
python -m pip check
python -m pytest -q
python scripts/verify_offline.py
lyra --help
```

Conda尚未加入shell时，先source自己安装目录的 `etc/profile.d/conda.sh`。本机为 `/home/mgy/miniconda3/etc/profile.d/conda.sh`。激活按完整路径，避免全局环境名称混淆；environment.yml设置PYTHONNOUSERSITE=1。

未激活的自动化命令显式排除污染：

```bash
env -u PYTHONPATH -u PYTHONHOME PYTHONNOUSERSITE=1 .conda/lyra/bin/python -m personal_quant --help
```

MPLCONFIGDIR可指向可写缓存目录；受控测试使用 `/tmp/lyra-matplotlib`。不要引入其他环境的site-packages。大小写敏感的沙箱路径按实际 `/mnt/c/quant/project/lyra` 使用；本机WSL物理路径显示Lyra时，通过显式小写cd和绝对路径写入，不改系统权限。

## 依赖锁与清洁重装

`pyproject.toml`精确声明直接依赖；`requirements-linux-py311.lock`固定77包和实际wheel SHA256，含test/personal-return扩展。对应Python/平台外的环境须重新生成并验证平台锁。

```bash
conda create --prefix "$PWD/.conda/lyra" --file conda-linux-64.lock --no-default-packages --yes
conda env config vars set --prefix "$PWD/.conda/lyra" PYTHONNOUSERSITE=1
conda activate "$PWD/.conda/lyra"
python -m pip install --require-hashes -r requirements-linux-py311.lock
python -m pip install --no-deps --no-build-isolation -e .
python -m pip check
```

当前清洁验收先用本机已校验Conda包归档新建26基础包，随后实际运行 `pip install --no-index --find-links .conda/wheelhouse --require-hashes -r requirements-linux-py311.lock` 与项目安装；不是克隆现有环境。普通YAML创建的索引dry-run实际超时，不算安装成功；显式 `conda-linux-64.lock` 已实际创建第三个独立基础前缀并退出0。Conda本机关闭插件时应显式 `CONDA_SOLVER=classic`，否则其默认libmamba不可用；这是进程配置，不修改全局配置。

最终180项pytest、imports-final.json、pip-check、CLI和离线验证日志在 `reports/environment/clean-20261009/`。独立前缀没有其他环境依赖位置，本项目editable源码路径单独列明。环境/包缓存/wheelhouse不提交Git；真实资料仍按demo/paper/real独立配置与账本隔离。

## 已解决的旧网络阻塞

此前Codex沙箱创建socket返回errno1，本次网络允许会话已实际连接PyPI、安装全部依赖并下载Yahoo数据。历史失败保留在 `reports/environment/conda-20261009/`，不能作为当前状态。若以后再失败，先核对实际socket与代理错误，不推定数据源不可用。

退出受限会话后，可以恢复同一次对话并启用网络：

```bash
cd /mnt/c/quant/project/lyra
codex resume 01a11b34-fa36-7c70-9ab7-ac739f03d830 --sandbox workspace-write -c sandbox_workspace_write.network_access=true
```

通用恢复最近一次会话：`codex resume --last --sandbox workspace-write -c sandbox_workspace_write.network_access=true`。已按本机 `codex resume --help` 核对参数。新会话仍需实测网络；聊天授权不修改沙箱。恢复后先读agents第8节、核对工作区及存活进程，不依靠旧日志推定任务仍在执行。
