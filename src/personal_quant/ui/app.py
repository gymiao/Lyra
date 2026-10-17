from __future__ import annotations

import argparse
import json
from pathlib import Path
import pandas as pd
import streamlit as st

from personal_quant.common import QuantError, canonical, digest, now_utc
from personal_quant.config import Config
from personal_quant.data.store import DataStore
from personal_quant.execution.plans import PlanService
from personal_quant.portfolio import Ledger
from personal_quant.portfolio.reconciliation import ReconciliationRules
from personal_quant.portfolio.imports import event_csv, snapshot_csv
from personal_quant.portfolio.report import report_from_store, load_account_report
from personal_quant.cli import references
from personal_quant.strategies import Signal, decode_signal
from personal_quant.strategies.archive import SignalArchive


def display_time(value):
    return str(pd.Timestamp(value).tz_convert("Asia/Shanghai"))


def display_records(rows):
    frame = pd.DataFrame([dict(row) for row in rows])
    for name in ["as_of", "updated_at", "recorded_at", "started_at", "finished_at", "generated_at"]:
        if name in frame:
            frame[name] = frame[name].map(lambda value: display_time(value) if value else "")
    return frame


def application():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/demo.toml")
    args, _ = parser.parse_known_args()
    config = Config.load(args.config)
    root = Path(config.runtime_dir)
    st.set_page_config(page_title="LyraX 个人投资系统", layout="wide")
    st.title("LyraX 个人投资系统")
    st.caption(f"账户环境：{config.environment} · USD · 展示时区 Asia/Shanghai")
    if config.environment != "real":
        st.info("当前为测试/模拟环境，资金、成交和报告不代表真实账户。")
    page = st.sidebar.radio("页面", ["账户总览", "策略研究", "调仓计划", "运行状态"],
                            index=1 if st.query_params.get("view") == "research" else 0)
    metadata = None
    frame, calendar = None, None
    if (root / "data/latest.json").exists():
        try:
            frame, metadata, calendar = DataStore(root / "data").load_role("signal" if page in {"策略研究", "运行状态"} else "execution" if page == "调仓计划" else "valuation")
            st.caption(f"行情来源：{metadata['data_type']} / {', '.join(metadata['source'])} · 数据截至 {metadata['end']}")
            st.caption(f"行情获取时间：{display_time(metadata['acquired_at'])} · 交易日期使用市场时区 {config.market} / America/New_York")
        except QuantError as exc:
            st.error(f"当前行情不可用：{exc}。已发布报告和历史账本仍可查看。")
    else:
        managed=root/'simulation/workspace.json'
        if managed.exists() and json.loads(managed.read_text()).get('kind')=='options':
            st.info('期权模拟工作区使用明确冻结的期权链和执行路径；未绑定ETF行情。已有账户报告和模拟检查点仍可查看。')
        elif list((root/'options/monthly-research').glob('*/report.json')):
            st.info("ETF用途行情尚未绑定；已有期权月度报告可在策略研究中查看。")
        else:
            st.warning("尚无行情数据。请先运行离线演示或导入/下载行情。")
    ledger = Ledger(root / "account.sqlite", config.environment)
    try:
        from personal_quant.ui.context import view_context, field
        context = view_context(config,args.config,root)
        clock = now_utc()
        if config.environment == "demo":
            clock = field(context,"固定样本查看时点（带时区）","clock","view-clock",sidebar=True)
        if page != "策略研究":
            st.sidebar.caption("真实/前向账户使用当前时钟；历史样本时钟只在 demo 生效。")
        from personal_quant.ui.v18 import controls
        controls(ledger,config,Path(args.config),page,clock)
        if page == "账户总览":
            account = field(context,"账户 ID","account","view-account")
            notice = st.session_state.pop("import_notice", None)
            if notice and notice["account_id"] == account:
                st.success(canonical(notice["result"]))
                st.info("账本及关联计划已同步更新，报告已重建；请核对实际成交与独立快照。")
            if st.button("建立空账户"):
                ledger.account(account)
                st.success("空账户已建立，没有自动写入任何资金。")
            prices = references(frame, clock) if frame is not None else {}
            if st.button("更新账户报告"):
                report_from_store(ledger, account, clock, DataStore(root / "data"), config, root / "reports/account-latest")
                st.success("报告已按指定时点和当前账本重建。")
            report_file = root / "reports/account-latest/account.json"
            if not report_file.exists():
                report_file = root / "reports/account-demo/account.json"
            if report_file.exists():
                report = load_account_report(report_file.parent)
                if report["account_id"] != account:
                    st.warning("已发布报告属于其他账户，请确认账户 ID 后更新报告。")
                    report = None
            else:
                report = None
            if report is not None:
                from personal_quant.portfolio.report_state import report_state
                freshness = report_state(ledger,report,account,clock)
                if freshness['status'] != 'CURRENT':
                    st.warning(freshness['reason'])
                st.caption("账户估值截至：" + str(pd.Timestamp(report["as_of"]).tz_convert("Asia/Shanghai")))
                st.write("估值质量与价格截至", report.get("valuation", {}))
                values = st.columns(4)
                for column, label, key in zip(values, ["总资产", "净投入", "已结算现金", "投资盈亏"], ["equity", "net_contributions", "settled_cash", "investment_pnl"]):
                    column.metric(label if freshness['status']=='CURRENT' else '报告'+label, report[key] if report[key] is not None else "估值不完整")
                st.write("累计入金", report["deposits"], "累计出金", report["withdrawals"])
                st.dataframe(pd.DataFrame([{"标的": s, "实际份额": q, "参考价格": report["prices"].get(s, "缺失")} for s, q in report["positions"].items()]))
                st.write("XIRR", report["xirr"]["value"] if report["xirr"]["value"] is not None else report["xirr"]["reason"])
            else:
                known = ledger.connection.execute('SELECT 1 FROM accounts WHERE id=?',(account,)).fetchone()
                if known and ledger.sequence(account):
                    st.info("已有账户事实，尚无已发布报告；请更新报告以核对资产与估值。")
                else:
                    st.info("暂无已发布账户报告；已建立的空账户资产与现金为零。")
            upload = st.file_uploader("标准事件 CSV（成交/资金/公司行动）", type="csv")
            if upload is not None:
                rows = event_csv(upload.getvalue())
                if st.button("预检导入"):
                    st.session_state["import_preview"] = ledger.preview(account, rows, clock, prices)
                    st.session_state["preview_account"] = account
                preview = st.session_state.get("import_preview")
                if preview:
                    st.write(preview)
                    if st.button("提交已预检的账单"):
                        if st.session_state.get("preview_account") != account or preview["batch_hash"] != digest(rows):
                            raise QuantError("STALE_PREVIEW", "账户或文件已变化，请重新预检")
                        from personal_quant.options.receipts import import_statement
                        result = import_statement(ledger,account,rows,preview["expected_sequence"],clock)
                        st.session_state.pop("import_preview", None)
                        report_from_store(ledger, account, clock, DataStore(root / "data"), config, root / "reports/account-latest")
                        st.session_state["import_notice"] = {"account_id": account, "result": result}
                        st.rerun()
            expected_upload = st.file_uploader("独立账户快照 CSV", type="csv", key="reconciliation-upload")
            if expected_upload is not None and st.button("核对独立快照"):
                expected = snapshot_csv(expected_upload.getvalue())
                result = ledger.reconcile(account, expected, references(frame, expected["as_of"]) if frame is not None else {},
                                          rules=ReconciliationRules.from_config(config))
                st.write(result)
            with st.expander("研究与核验执行价格 CSV 导入"):
                st.caption("CSV包含原始OHLCV、adj_close、分红/拆股、来源/口径和available_at；价格不会直接写入资金/成交账本。实际公司行动凭据仍通过标准事件CSV导入。")
                price_upload = st.file_uploader("标准价格 CSV", type="csv", key="raw-price-upload")
                calendar_upload = st.file_uploader("对应日历 CSV（合成样本必填）", type="csv", key="raw-calendar-upload")
                kind = st.selectbox("价格日历资格", ["verified_market_sessions", "synthetic_test_sessions"])
                if price_upload:
                    from personal_quant.data.imports import price_csv_preview
                    preview, normalized, imported_calendar = price_csv_preview(price_upload.getvalue(),
                        calendar_content=calendar_upload.getvalue() if calendar_upload else None,
                        calendar_kind=kind, environment=config.environment)
                    if st.button("预检价格 CSV"):
                        st.session_state["price_preview_hash"] = preview["input_hash"]
                        st.write(preview)
                    if st.button("提交已预检价格 CSV"):
                        if st.session_state.get("price_preview_hash") != preview["input_hash"]:
                            raise QuantError("STALE_PRICE_PREVIEW", "价格文件/日历/环境已改变，请先预检")
                        st.write(DataStore(root / "data").save(normalized, imported_calendar))
                        st.session_state.pop("price_preview_hash", None)
                        st.success("价格快照已缓存；旧快照保留。请在计划中明确选择研究及核验执行快照。")
        elif page == "策略研究":
            from personal_quant.ui.workbench import render
            from personal_quant.research.compare import published_runs, compare_runs
            render(ledger, config, Path(args.config), metadata, calendar)
            directory = root / "reports/research"
            published = published_runs(directory, ledger)
            runs = [item["run_id"] for item in published]
            if not runs:
                st.info("暂无 bt 回测报告；信号或账户模拟不能代替策略比较。")
            else:
                selected = st.selectbox("研究运行", runs)
                run = directory / selected
                manifest = json.loads((run / "manifest.json").read_text())
                st.caption(f"历史回测 / {manifest['data_type']} · {display_time(manifest['generated_at'])}")
                st.line_chart(pd.read_csv(run / "nav.csv", index_col=0))
                st.line_chart(pd.read_csv(run / "drawdowns.csv", index_col=0))
                st.dataframe(pd.DataFrame(manifest["metrics"]).T)
                st.dataframe(pd.read_csv(run / "trades.csv"))
                if (run/"continuous-slices.json").exists():
                    st.expander("连续持仓年度切片（不重新建仓）").dataframe(pd.DataFrame(json.loads((run/"continuous-slices.json").read_text())))
                if (run/'contributions.json').exists():
                    st.expander('无外部资金流的研究收益贡献（金额桥接）').json(json.loads((run/'contributions.json').read_text()))
                if (run/'rolling.json').exists():
                    st.expander('共同完整窗口的滚动表现').dataframe(pd.DataFrame(json.loads((run/'rolling.json').read_text())))
                st.expander("参数与成交假设").json(manifest["assumptions"])
                if manifest.get("schema_version") == 2:
                    st.expander("冻结策略、现金占比与实验身份").json({key: manifest[key] for key in
                        ("members", "research_context", "data_bundle", "cash_policy", "completeness")})
                    st.expander("逐月决策、评分及原因").json(json.loads((run / "signals.json").read_text()))
                compare = st.multiselect("比较已发布运行（相同区间及口径）", runs)
                if len(compare) >= 2 and st.button("核验并比较运行"):
                    result, nav = compare_runs(directory, compare, ledger=ledger)
                    st.caption(result["comparison"])
                    st.line_chart(nav)
                    st.dataframe(pd.DataFrame(result["metrics"]).T)
        elif page == "调仓计划":
            service = PlanService(ledger, config)
            account = field(context,"计划账户 ID","account","view-plan-account")
            session = st.text_input("月末决策交易日", "2024-12-31" if config.environment == "demo" else "")
            option_file=st.file_uploader('本次期权估值依据 JSON（持有期权时必需）',type=['json'],key='stock-plan-option-valuation')
            option_valuation=json.loads(option_file.getvalue()) if option_file is not None else None
            st.caption('需明确报价快照及检查参数；不继承旧计划估值。中价用于权益核对，不是期权成交价格。')
            price_snapshots = sorted(p.name for p in (root / "data").iterdir() if p.is_dir() and len(p.name) == 64) if metadata else []
            signal_snapshot = execution_snapshot = metadata["snapshot_id"] if metadata else None
            if ledger.connection.execute("SELECT version FROM schema_version").fetchone()[0] >= 3 and price_snapshots:
                signal_snapshot = st.selectbox("信号价格快照", price_snapshots, index=price_snapshots.index(metadata["snapshot_id"]))
                execution_snapshot = st.selectbox("核验执行价格快照", price_snapshots, index=price_snapshots.index(metadata["snapshot_id"]))
            managed_file=root/'simulation/workspace.json'
            option_workspace=managed_file.exists() and json.loads(managed_file.read_text()).get('kind')=='options'
            if option_workspace:
                st.info('当前工作区使用冻结期权信号推进；请在模拟工作台查看期权运行及其依据。')
            if st.button("生成月度计划",disabled=option_workspace):
                if frame is None:
                    raise QuantError("NO_DATA", "请先导入或获取行情")
                if ledger.connection.execute("SELECT version FROM schema_version").fetchone()[0] >= 3 and ledger.connection.execute(
                        "SELECT 1 FROM strategy_bindings WHERE account_id=?", (account,)).fetchone():
                    from personal_quant.strategies.bindings import BindingService
                    from personal_quant.strategies.spec import DataBundle
                    factor_latest = root / "factors/latest.json"
                    factor_id = json.loads(factor_latest.read_text())["snapshot_id"] if factor_latest.exists() else None
                    _, signal_meta, signal_calendar = DataStore(root / "data").load(signal_snapshot)
                    bundle = DataBundle(signal_snapshot, signal_calendar.hash, execution_snapshot_id=execution_snapshot, factor_snapshot_id=factor_id)
                    if ledger.connection.execute('SELECT version FROM schema_version').fetchone()[0] >= 4:
                        from personal_quant.data.selection import bundle_for
                        bundle = bundle_for(DataStore(root/'data'))
                    st.write(BindingService(ledger, config).decide(account, bundle, session, as_of=clock if config.environment == "demo" else None,option_valuation=option_valuation))
                else:
                    signal_frame, signal_meta, signal_calendar = DataStore(root/"data").load_role("signal")
                    record = SignalArchive(ledger).generate(signal_frame, signal_meta, signal_calendar, config, session,
                                                            decision_time=clock if config.environment == "demo" else None,
                                                            account_state=ledger.snapshot(account, clock))
                    value = decode_signal(record["signal"])
                    st.write(service.create(account, value, frame, metadata, calendar, clock,option_valuation=option_valuation))
            ids = [r[0] for r in ledger.connection.execute("SELECT plan_id FROM plans ORDER BY rowid DESC")]
            if not ids:
                st.info("暂无计划，空账户或非调仓日不会自动产生交易。")
            else:
                plan_id = st.selectbox("计划", ids)
                plan = service.get(plan_id)
                body = plan["payload"]
                from personal_quant.execution.review import execution_review, review_csv
                if st.button('查看实际执行偏差'):
                    review=execution_review(ledger,config,plan_id,clock)
                    st.dataframe(pd.DataFrame(review['lines']));st.caption(review['description'])
                    st.download_button('下载计划及执行复盘 CSV',review_csv(review),file_name=plan_id[:12]+'.csv',mime='text/csv')
                    st.expander('修订和待核实事件').json(review)
                st.write("执行状态", plan["execution_status"], "检查结果", plan["check_status"])
                st.write("模拟股票阶段" if body.get('purpose')=='simulation_stock' else "对冲阶段状态" if body.get("purpose") == "hedge_stage" else "月度意图状态", body.get("intent_status", "旧版本待核对"))
                if st.button("同步剩余数量与检查状态"):
                    service.refresh(plan_id, clock)
                    st.rerun()
                if body.get("purpose") not in {'hedge_stage','simulation_stock'} and st.button("按冻结月末目标修订未完成部分"):
                    if frame is None:
                        raise QuantError("NO_DATA", "请先更新行情")
                    st.write(service.revise(plan_id, frame, metadata, calendar, clock,option_valuation=option_valuation))
                st.caption(f"参考日期 {body['reference_session']} · 适用日 {body.get('execution_session')} · 版本 {body['revision']}")
                if body.get('purpose')=='simulation_stock':
                    st.write('冻结模拟周期',body['simulation_context'])
                    st.caption('合成模拟的股票准备/清理；不提交券商订单，也不是股票选股信号。')
                elif body.get("purpose") == "hedge_stage":
                    st.caption("父对冲意图：" + body["hedge_context"]["hedge_id"])
                    st.write("调整原因", body["hedge_context"]["reason"])
                else:
                    st.write("目标权重", body["signal"]["target_weights"])
                    st.write("策略决策说明", body["signal"]["reasons"])
                st.write("当前实际持仓", (body.get("snapshot") or {}).get("positions", {}))
                st.dataframe(pd.DataFrame((body.get("sizing") or {}).get("lines", [])))
                if body.get("sizing"):
                    st.write("预计执行后权重", body["sizing"]["projected_weights"])
                    st.write("预计费用", body["sizing"]["estimated_fee"])
                st.write("检查与原因", body["checks"])
                if body.get("remaining"):
                    st.write("剩余建议", body["remaining"])
                st.download_button("导出计划 JSON", canonical(plan), file_name=f"{plan_id}.json", mime="application/json")
                action = st.selectbox("人工状态记录", ["已自行下单，尚未回报", "已确认无在途订单", "取消未执行部分"])
                if st.button("保存人工状态"):
                    if action == "取消未执行部分":
                        service.cancel(plan_id)
                    else:
                        service.manual_pending(plan_id, action == "已自行下单，尚未回报", clock)
                    st.rerun()
        else:
            st.write("数据版本", metadata or "暂无数据")
            st.subheader("任务状态")
            if ledger.connection.execute("SELECT version FROM schema_version").fetchone()[0] >= 3:
                from personal_quant.research.service import ResearchService
                st.subheader("策略研究尝试与失败原因")
                st.dataframe(pd.DataFrame(ResearchService(ledger).list()))
            st.dataframe(display_records(ledger.connection.execute("SELECT * FROM tasks ORDER BY updated_at DESC")))
            st.subheader("日常任务尝试与恢复步骤")
            st.dataframe(display_records(ledger.connection.execute("SELECT * FROM daily_attempts ORDER BY started_at DESC LIMIT 20")))
            latest_attempt = ledger.connection.execute("SELECT details FROM daily_attempts ORDER BY started_at DESC LIMIT 1").fetchone()
            if latest_attempt:
                gaps = json.loads(latest_attempt[0]).get("tracking_gaps")
                if gaps:
                    st.write("月度跟踪完整性", gaps)
                    if gaps.get("months"):
                        st.warning("存在漏跑或阻断月份；历史信号、计划和成交不会自动补造。")
            st.subheader("导入与失败原因")
            st.dataframe(display_records(ledger.connection.execute("SELECT status,details,recorded_at FROM imports ORDER BY id DESC LIMIT 20")))
            st.subheader("对账差异")
            st.dataframe(display_records(ledger.connection.execute("SELECT status,as_of,details FROM reconciliations ORDER BY id DESC LIMIT 10")))
        from personal_quant.ui.v19 import controls as v19_controls
        v19_controls(ledger,config,Path(args.config),page,clock)
        from personal_quant.ui.v195 import controls as v195_controls
        v195_controls(ledger,config,Path(args.config),page,clock)
    finally:
        ledger.close()


if __name__ == "__main__":
    try:
        application()
    except (QuantError, ValueError, OSError) as exc:
        st.error(str(exc))
