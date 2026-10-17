# v1.9 模型 Delta 凭据接口

状态：2026-10-13，当前主源码7849da9a已完成802项无跳过、模型11CLI/完整恢复及同源安装/UI验收，真实输入资格仍独立待资料；最终状态以 PROGRESS.md 为准。

## 用途与边界

模型资格说明能用冻结输入和锁定 QuantLib 重新计算该份 Delta；不能证明预测正确、报价可成交或用户有交易权限。供应商观察值与模型输出使用不同命名空间。缺真实期权数据及账户资料时，测试资料保持 UNQUALIFIED。

## 完整输入

顶层 observation 包含 contract_version、unit、value、signed_contracts、source、data_type、as_of、available_at、received_at、model_inputs。模型 data_type 为 model，unit 必须 position_total；张数为非零有符号整数，整份 Delta 只归一一次。

model_inputs 必须包含 pricing、model、engine、model_version、pricing_source_hash、input_observations；后四个模型字段从已锁 options.pricing 返回值及源码 SHA256 获取。

pricing 必须显式给出 right、style、spot、strike、valuation_date、expiry、volatility、rate、dividend_yield、multiplier、contracts、market_price、discrete_dividends。market_price 必须 null，不能隐式用现价求 IV；其他参数按确切合约和观察时点提供。模型标的 spot 必须等于本次风险或候选归档的实际原价。

input_observations 对 spot、volatility、rate、dividend_yield、discrete_dividends 各保存 value、source、as_of、available_at、received_at、max_age_seconds、data_type、raw_file。即使分红假设为空，也要提供独立依据，不能悄悄填默认值。

- 每项值与 pricing 对应值一致；观察、发布、收到时间有序，并在模型输出时已经可用，年龄不超过显式上限。
- actual 凭据的每项输入类型必须 real_market；不能通过改标签把测试文件变成真实数据。
- raw_file 引用随凭据归档的独立原始文件，不能指向规范 observation.json 或 model-inputs.json。
- Delta 固定容差为 1e-8 × max(1, abs(重新计算的 Delta))；不根据测试结果扩大容差。

## 注册与核对

复用 options 的 greek-register / greek-assess 动作。凭据 asset_type 为 OPTION_MODEL_GREEK_OBSERVATION；series_id 使用 option-model-greek: 加来源及确切合约版本的内容哈希。schema_version 为 2，其他审核字段沿用供应商凭据接口。

目录至少保存 observation.json、model-inputs.json 和独立原始资料；evidence_files 列出文件 SHA256。实际账户另需确切标准合约单位凭据、最新有效审核及相关数据/账户权限，模型资格不能替代这些检查。

可运行工程验证：

```bash
PYTHONDONTWRITEBYTECODE=1 MPLCONFIGDIR=/tmp/lyrax-mpl \
  .conda/v19-clean/bin/python scripts/verify_model_greek.py \
  --workspace /mnt/c/quant/project/lyra/reports/model-greek-check
```

该目录必须未存在。脚本仅生成明确标识的合成凭据，检查重复注册、伪造 Delta、未来输入及备份恢复；最终 UNQUALIFIED、账户金融序号 0 是预期结果。隔离源码已有 11 条命令和恢复证据；主源码命令验证由最终全量入口执行。

## 失败处理

INVALID_MODEL_GREEK_INPUT 表示缺失、过期、未来输入或模型/合约/源码不匹配；MODEL_GREEK_MISMATCH 表示输出不能复算；MODEL_GREEK_PRICE_MISMATCH 表示模型原价与冻结风险原价不同。资料文件变化仍按 CORRUPT_SOURCE_EVIDENCE 处理。

新增 OPEN 不能绕过这些错误。必要 CLOSE 可以在完整估值、实际财务事实和直接情景独立通过时继续展示，不把不合格模型用于新增风险。
