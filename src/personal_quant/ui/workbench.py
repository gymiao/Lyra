"""Chinese research editor. Buttons call the same persistent CLI services."""
from dataclasses import replace
import json
from pathlib import Path

import pandas as pd
import streamlit as st

from personal_quant.common import QuantError, canonical
from personal_quant.data.factors import FactorStore
from personal_quant.research.compare import compare_runs
from personal_quant.research.experiments import ResearchSpec
from personal_quant.research.service import ResearchService
from personal_quant.strategies.bindings import BindingService
from personal_quant.strategies.registry import definitions
from personal_quant.strategies.spec import DataBundle, StrategySpec
from personal_quant.strategies.store import StrategyStore, enable_workbench
from personal_quant.strategies.drafts import DraftStore, differences


def guarded(function):
    try:
        return function()
    except (QuantError, ValueError, OSError) as exc:
        st.error(str(exc))
        return None


def render(ledger, config, config_path, metadata, calendar):
    st.subheader("LyraX v1.5 策略工作台")
    st.caption("六类月度只做多规则 · 已观察历史研究 · 策略资金与账户资金独立")
    if ledger.connection.execute("SELECT version FROM schema_version").fetchone()[0] < 3:
        st.info("首次启用将备份当前运行数据及账本，再升级策略记录；不写入资金或成交。")
        if st.button("备份并启用策略工作台"):
            result = guarded(lambda: enable_workbench(ledger, config_path))
            if result:
                st.session_state["workbench_notice"] = result
                st.rerun()
        return
    if "workbench_notice" in st.session_state:
        st.success("工作台已启用：" + canonical(st.session_state["workbench_notice"]))
    library = StrategyStore(ledger)
    editor, runner, tracking, factors = st.tabs(["策略编辑", "实验与任务", "账户绑定", "因子数据"])
    with editor:
        versions = library.list()
        options = {f"{v['strategy_id']}@{v['revision']}": v for v in versions}
        draft_store = DraftStore(Path(config.runtime_dir) / "drafts")
        drafts = {f"草稿 {value['spec']['strategy_id']}@{value['spec']['revision']}": value for value in draft_store.list().values()}
        choice = st.selectbox("编辑来源", ["新建"] + list(options) + list(drafts), key="strategy-edit-source")
        draft = drafts.get(choice)
        if st.session_state.get("draft_editor_choice") != choice:
            st.session_state["draft_editor_choice"] = choice
            st.session_state["draft_editor_hash"] = draft["hash"] if draft else None
        original = draft["spec"] if draft else options.get(choice)
        all_templates = definitions()
        default_template = original["template_id"] if original else "trend"
        template = st.selectbox("策略模板", list(all_templates), index=list(all_templates).index(default_template),
            format_func=lambda key: all_templates[key].name, key="template-" + choice)
        item = all_templates[template]
        st.write(item.description)
        base = original if original and original["template_id"] == template else {}
        prefix = "spec-" + choice + "-" + template
        with st.form(prefix):
            strategy_id = st.text_input("策略 ID", base.get("strategy_id", template), key=prefix + "id")
            name = st.text_input("展示名称", base.get("display_name", base.get("name", item.name)), key=prefix + "name")
            revision = st.number_input("新修订号", min_value=1, value=base.get("revision", 1) if draft else base.get("revision", 0) + 1, step=1, key=prefix + "revision")
            basket = st.text_input("标的（逗号分隔）", ",".join(base.get("symbols", config.symbols)), key=prefix + "symbols")
            budget = st.number_input("投资预算比例", 0., 1., float(base.get("invested_budget", .95)), key=prefix + "budget")
            cap = st.number_input("目标单标的上限", .001, 1., float(base.get("weight_cap", .60)), key=prefix + "cap")
            params = {}
            for key, param in item.parameters.items():
                value = base.get("parameters", {}).get(key, param.default)
                if param.kind == "choice":
                    params[key] = st.selectbox(param.label, param.choices, index=param.choices.index(value), key=prefix + key)
                elif param.kind == "int":
                    params[key] = st.number_input(param.label, int(param.minimum), int(param.maximum), int(value), step=1, key=prefix + key)
                else:
                    params[key] = st.number_input(param.label, float(param.minimum), float(param.maximum), float(value), key=prefix + key)
            weights = None
            if template in {"fixed", "trend", "mean_reversion"}:
                initial_weights = base.get("weights") or {symbol: .95 / len(config.symbols) for symbol in config.symbols}
                weight_json = st.text_area("基础权重 JSON（不会自动归一化）", canonical(initial_weights), key=prefix + "weights")
            submitted = st.form_submit_button("校验并冻结新版本")
            save_draft = st.form_submit_button("校验并保存草稿")
            preflight = st.form_submit_button("预检行情与决策时点")
        if submitted or save_draft or preflight:
            def build():
                weights = json.loads(weight_json) if template in {"fixed", "trend", "mean_reversion"} else None
                spec = StrategySpec.create(template, [x.strip().upper() for x in basket.split(",")],
                    strategy_id=strategy_id, name=name, revision=revision, parameters=params, weights=weights,
                    invested_budget=budget, weight_cap=cap, publication_delay_minutes=config.publication_delay_minutes,
                    price_jump_threshold=config.price_jump_threshold)
                return spec
            spec = guarded(build)
            if spec:
                if original:
                    st.dataframe(pd.DataFrame(differences(StrategySpec.from_dict({k: v for k, v in original.items()
                        if k not in {"display_name", "created_at"}}).content(), spec.content())))
                if submitted:
                    published = guarded(lambda: library.publish(spec))
                    if published:
                        st.success(f"已冻结 {strategy_id}@{revision}；{spec.spec_hash}")
                elif save_draft:
                    saved = guarded(lambda: draft_store.save(spec, expected_hash=st.session_state.get("draft_editor_hash") if draft else None))
                    if saved:
                        st.session_state["draft_editor_hash"] = saved["hash"]
                        st.success("草稿已保存；重新选择草稿继续编辑，不影响已发布版本或账户。")
                elif metadata is None:
                    st.error("缺少行情；可先保存草稿。")
                else:
                    from personal_quant.research.preview import preview
                    factor_latest = Path(config.runtime_dir) / "factors/latest.json"
                    factor_id = json.loads(factor_latest.read_text())["snapshot_id"] if factor_latest.exists() else None
                    result = guarded(lambda: preview(config, spec, DataBundle(metadata["snapshot_id"], calendar.hash, factor_snapshot_id=factor_id)))
                    if result:
                        st.write("数据预检、预热及首次决策/成交", result)
        st.dataframe(pd.DataFrame([{k: v[k] for k in ("strategy_id", "revision", "display_name", "template_id", "spec_hash")} for v in library.list()]))
        if st.button("冻结六类演示版本（预算95%）"):
            def defaults():
                with ledger.transaction():
                    return [library.publish(StrategySpec.create(key, config.symbols,
                        weights={s: .95 / len(config.symbols) for s in config.symbols} if key in {"fixed", "trend", "mean_reversion"} else None,
                        publication_delay_minutes=config.publication_delay_minutes, price_jump_threshold=config.price_jump_threshold))
                        for key in definitions()]
            result = guarded(defaults)
            if result:
                st.success("六个示例版本已冻结；没有变更账户绑定。")
        refs = {f"{v['strategy_id']}@{v['revision']}": v for v in library.list()}
        if refs:
            exported = st.selectbox("导出或重命名版本", list(refs), key="export-version")
            value = refs[exported]
            st.download_button("导出冻结规格 JSON", canonical(library.get(value["strategy_id"], value["revision"]).export()),
                file_name=exported + ".json", mime="application/json")
            new_name = st.text_input("新的展示名称", value["display_name"], key="rename-" + exported)
            if st.button("保存展示名称"):
                guarded(lambda: library.rename(value["strategy_id"], value["revision"], new_name))
                st.rerun()
            if original:
                st.caption("参数改动会产生新修订；旧版本内容保持不变。当前选中的冻结规格：")
                st.json(original if draft else library.get(original["strategy_id"], original["revision"]).export())
        upload = st.file_uploader("导入策略规格 JSON", type="json", key="strategy-import")
        if upload and st.button("校验并冻结导入规格"):
            value = guarded(lambda: library.publish(StrategySpec.from_dict(json.loads(upload.getvalue()))))
            if value:
                st.success(value.spec_hash)
    with runner:
        research = ResearchService(ledger)
        versions = library.list()
        refs = {f"{v['strategy_id']}@{v['revision']}": v for v in versions}
        if len(refs) < 2 or metadata is None:
            st.info("先冻结基准与候选两个不同计算规格，并导入行情。")
        else:
            benchmark = st.selectbox("实验基准", list(refs), key="experiment-baseline")
            selected = st.multiselect("候选版本（最多6个）", [ref for ref in refs if ref != benchmark], key="experiment-members")
            with st.form("research-settings"):
                start = st.text_input("评估开始日期", config.evaluation_start)
                end = st.text_input("评估结束日期", config.evaluation_end)
                capital = st.number_input("研究初始资金 USD", min_value=.01, value=float(config.research_capital))
                commission = st.number_input("佣金 bps", min_value=0., value=float(config.commission_bps or 0))
                slippage = st.number_input("滑点 bps", min_value=0., value=float(config.slippage_bps or 0))
                fixed_fee = st.number_input("每笔固定费用 USD", min_value=0., value=float(config.fixed_fee or 0))
                purpose = st.selectbox("研究用途", ["exploratory", "validation"], format_func=lambda x: "探索（已观察）" if x == "exploratory" else "验证（已观察）")
                factor_id = st.text_input("因子快照 ID（价值/质量模式必填）", key="research-factors")
                rerun = st.checkbox("显式重跑，保留新的尝试记录")
                submit = st.form_submit_button("提交后台研究")
            if submit:
                def run():
                    settings = replace(config, evaluation_start=start, evaluation_end=end, research_capital=capital,
                        commission_bps=commission, slippage_bps=slippage, fixed_fee=fixed_fee)
                    members = {f"member_{i}": library.get(refs[ref]["strategy_id"], refs[ref]["revision"])
                               for i, ref in enumerate([benchmark] + selected)}
                    bundle = DataBundle(metadata["snapshot_id"], calendar.hash, factor_snapshot_id=factor_id or None)
                    spec = ResearchSpec.create(settings, members, "member_0", bundle, purpose=purpose)
                    attempt = research.submit(spec, rerun=rerun)
                    return research.launch(attempt["attempt_id"])
                result = guarded(run)
                if result:
                    st.success("已登记任务：" + result["attempt_id"])
        if st.button("刷新研究任务"):
            st.rerun()
        if st.button("核实并恢复中断研究"):
            guarded(research.recover)
        st.dataframe(pd.DataFrame(research.list()))
        st.caption("运行中任务不超时抢占；中断尝试保留，需明确重跑。页面刷新不提交任务。")
    with tracking:
        if metadata and set(metadata["price_basis"]) != {"unadjusted"}:
            st.warning("跟踪受阻：当前只有研究价格，缺少核验执行原价/行动。可以保存待生效绑定，不能将其显示为可成交计划。")
        accounts = [row[0] for row in ledger.connection.execute("SELECT id FROM accounts")]
        if not accounts or calendar is None:
            st.info("先在账户总览建立空账户并导入行情；工作台不会注入模拟资金。")
        else:
            account = st.selectbox("绑定账户", accounts)
            binding_service = BindingService(ledger, config)
            refs = {f"{v['strategy_id']}@{v['revision']}": v for v in library.list()}
            if refs:
                selected = st.selectbox("待绑定的冻结版本", list(refs), key="bind-version")
                clock = st.text_input("绑定时钟（仅固定样本demo）", "2024-07-01T20:30:00Z") if config.environment == "demo" else None
                seq, account_seq = binding_service.sequence(account), ledger.sequence(account)
                st.caption(f"绑定序号 {seq} · 账户序号 {account_seq}；按提交时的合格月末生效。")
                if st.button("提交下个合格月末绑定"):
                    guarded(lambda: binding_service.request(account, refs[selected]["strategy_id"], refs[selected]["revision"], calendar,
                        as_of=clock, expected_binding_seq=seq, expected_account_seq=account_seq))
                st.dataframe(pd.DataFrame(binding_service.list(account)))
            st.dataframe(pd.DataFrame([dict(row) for row in ledger.connection.execute("SELECT decision_session,binding_seq,spec_hash,outcome,updated_at FROM monthly_decisions WHERE account_id=? ORDER BY decision_session DESC", (account,))]))
    with factors:
        st.info("价值/质量需要带财报期、发布时间、可用时间、估值日期、来源与定义版本的因子。未核验来源会阻断研究；合成因子只用于工程演示。")
        data_upload = st.file_uploader("标准因子 CSV", type="csv", key="factor-csv")
        meta_upload = st.file_uploader("因子来源与定义 JSON", type="json", key="factor-meta")
        if data_upload and meta_upload and st.button("校验并缓存因子"):
            def import_factors():
                frame = pd.read_csv(data_upload)
                if config.environment == "real" and set(frame.data_type) != {"real_factors"}:
                    raise QuantError("ENVIRONMENT_MISMATCH", "真实目录不能保存合成因子")
                return FactorStore(Path(config.runtime_dir) / "factors").save(frame, json.loads(meta_upload.getvalue()))
            result = guarded(import_factors)
            if result:
                st.success(canonical(result))
        latest = Path(config.runtime_dir) / "factors/latest.json"
        if latest.exists():
            frame, meta = FactorStore(latest.parent).load()
            st.json(meta)
            st.dataframe(frame.tail(12))
