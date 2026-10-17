"""Daily guidance and explicit v1.9 imports; rerenders never write facts."""
import json
from pathlib import Path
import pandas as pd
import streamlit as st
from ..common import QuantError, canonical, digest
from ..diagnostics import doctor
from ..portfolio.mapping import mapped_import
from ..portfolio.upgrade import enable_v19

ACTIONS={'dependency':'在独立Conda安装锁定依赖；运行pip check',
         'configuration':'补齐本账户费用、交易单位、结算与风险配置',
         'database':'确认工作区，先备份再显式升级',
         'data':'更新对应用途行情并核对原始单位/来源资格',
         'history':'补齐生效策略所需的连续交易日窗口',
         'plan':'核对计划检查及人工在途记录后再处理剩余部分',
         'reconciliation':'导入独立账户快照，逐项解决现金/持仓差异',
         'task':'查看失败阶段；同一任务恢复成功后再消除告警',
         'report':'核对报告输入/源码及文件指纹，不覆盖损坏证据',
         'schedule':'核对系统定时任务安装及实际运行日志'}


def today(ledger,config,clock):
    diagnostic=doctor(config,clock)
    items=[{'事项':check['kind']+'/'+check['id'],'状态':check['status'],
            '原因':check.get('reason','检查未通过，详见运行状态'),
            '下一动作':ACTIONS.get(check['kind'],'查看完整诊断')}
           for check in diagnostic['checks'] if check['status'] in {'BLOCKED','FAILED','WARNING','UNINITIALIZED','UNVERIFIED'}]
    bindings=[];next_decision=None;calendar_reason=None
    version=ledger.connection.execute('SELECT version FROM schema_version').fetchone()[0]
    if version>=3:
        bindings=[dict(row) for row in ledger.connection.execute('SELECT account_id,strategy_id,revision,effective_session,status FROM strategy_bindings ORDER BY binding_seq DESC')]
    try:
        from ..data.store import DataStore
        if diagnostic.get('workspace_kind')=='options':
            calendar_reason='期权模拟使用冻结信号的决策/适用日期，见生命周期日历；不要求ETF月末日历'
        else:
            _,_,calendar=DataStore(Path(config.runtime_dir)/'data').load_role('signal')
            candidates=[session for session in calendar.month_ends() if calendar.close(session)+pd.Timedelta(minutes=config.publication_delay_minutes)>pd.Timestamp(clock)]
            if candidates:
                session=candidates[0];next_decision={'market_session':str(session.date()),
                    'available_at_shanghai':str((calendar.close(session)+pd.Timedelta(minutes=config.publication_delay_minutes)).tz_convert('Asia/Shanghai'))}
            else:calendar_reason='当前日历未覆盖下一个完整月末；先更新日历，不推测调仓日期'
    except (QuantError,OSError,ValueError) as exc:calendar_reason=str(exc)
    pending=[]
    from ..hedging.monitor import monitor
    hedging=[]
    for account in ledger.connection.execute('SELECT id FROM accounts'):
        result=monitor(ledger,account[0],clock);hedging.append(result)
        items.extend({'事项':'对冲/'+r['code'],'状态':'BLOCKED','原因':r['message'],
                      '下一动作':'核对原父/计划、实际凭据和保护引用；保持原占用，解决差异后复核'} for r in result['checks'])
    if version>=5:
        pending=[dict(row) for row in ledger.connection.execute('SELECT event_id,account_id,reason,created_at FROM pending_option_events ORDER BY created_at')]
        items.extend({'事项':'期权凭据/'+r['event_id'],'状态':'BLOCKED','原因':r['reason'],
                      '下一动作':'补齐合约单位/行动/实际凭据并核实；事实未被自动丢弃'} for r in pending)
        from ..options.exit_tasks import pending_exits
        for account in ledger.connection.execute('SELECT id FROM accounts'):
            items.extend({'事项':'期权退出/'+identity,'状态':'PENDING',
                          '原因':'已有冻结退出意图，暂停新增调仓建议；实际持仓担保仍保留',
                          '下一动作':'核对冻结报价和执行条件，完成合成退出或显式取消未执行意图'}
                         for identity in pending_exits(ledger,account[0],clock))
    return {'as_of':clock,'environment':config.environment,'read_only':True,
            'status':'BLOCKED' if any(h['status']=='BLOCKED' for h in hedging) else diagnostic['status'],
            'accounts':diagnostic['accounts'],'bindings':bindings,
            'next_decision':next_decision,'calendar_reason':calendar_reason,'todo':items,'hedging':hedging,
            'backup':'近期备份尚未自动核验；运行backup-maintenance预览/创建，再做隔离restore'}


def controls(ledger,config,config_path,page,clock):
    from .hedging import controls as hedge_controls
    hedge_controls(ledger,page,clock)
    if page=='策略研究':
        with st.expander('期权月度比较：合成机械验证报告'):
            from ..options.monthly_report import load_monthly_report
            root=Path(config.runtime_dir)/'options/monthly-research'
            reports=sorted(path.parent for path in root.glob('*/report.json'))
            if not reports:st.info('暂无月度比较报告；可用options monthly-compare生成到本工作区options/monthly-research/<运行ID>。')
            else:
                selected=st.selectbox('期权月度报告',reports,format_func=lambda path:path.name)
                try:
                    report=load_monthly_report(selected)
                    generated=pd.Timestamp(report['generated_at']).tz_convert('Asia/Shanghai').strftime('%Y-%m-%d %H:%M:%S %Z')
                    st.caption(f"合成行情 / 历史重建 / 工程机械验证 · 纽约交易日期截至{report['as_of']} · 报告生成{generated}")
                    if report.get('option_underlyings'):st.caption('期权标的：'+', '.join(report['option_underlyings'])+' · 同一研究现金账户')
                    st.line_chart(pd.read_csv(selected/'equity.csv',index_col=0))
                    st.line_chart(pd.read_csv(selected/'drawdowns.csv',index_col=0))
                    st.dataframe(pd.DataFrame(report['metrics']).T)
                    st.dataframe(pd.read_csv(selected/'transactions.csv'))
                    st.json({'统一条件':report['policy'],'成交与指标口径':report['assumptions']})
                except (QuantError,OSError,ValueError,KeyError) as exc:st.error('期权月度报告核验失败：'+str(exc))
    with st.expander('今日待办与下一次决策'):
        summary=today(ledger,config,clock)
        st.caption('只读摘要；刷新不下载、不生成信号、不导入事件。数据、账户及报告的截至时间分别核对。')
        if summary['next_decision']:st.write('下一合格月末',summary['next_decision'])
        else:st.info(summary['calendar_reason'] or '尚无合格月末日历')
        st.json(summary)
    version=ledger.connection.execute('SELECT version FROM schema_version').fetchone()[0]
    if version<5:
        with st.expander('启用v1.9账单适配与期权凭据'):
            st.caption('显式操作：先验证完整备份再迁移v5；不写入资金或成交。')
            if st.button('备份并启用 v1.9'):
                try:st.success(canonical(enable_v19(ledger,config_path)));st.rerun()
                except (QuantError,OSError,ValueError) as exc:st.error(str(exc))
        return
    if page=='账户总览':
        with st.expander('独立模拟组合只读汇总'):
            st.caption('各paper工作区独立资金和事件；只有同一估值时点且报告完整时才合计金额，不合并收益率。')
            request=st.file_uploader('模拟工作区清单JSON',type=['json'],key='v19-paper-summary')
            if request is not None and st.button('读取隔离组合摘要'):
                try:
                    from ..portfolio.aggregate import aggregate
                    st.json(aggregate(json.loads(request.getvalue()),clock))
                except (QuantError,OSError,ValueError,KeyError) as exc:st.error(str(exc))
        accounts=[row[0] for row in ledger.connection.execute('SELECT id FROM accounts')]
        if accounts:
            with st.expander('券商CSV声明式映射：预检后提交'):
                account=st.selectbox('映射目标账户',accounts)
                statement=st.file_uploader('原始券商CSV（需脱敏）',type=['csv'],key='v19-statement')
                mapping=st.file_uploader('声明式映射JSON（不执行代码）',type=['json'],key='v19-mapping')
                if statement is not None and mapping is not None:
                    try:
                        content=statement.getvalue();definition=json.loads(mapping.getvalue())
                        basis=digest({'account':account,'statement':content.hex(),'mapping':definition})
                        if st.button('预检映射账单'):
                            st.session_state['v19-mapping-preview']={'basis':basis,'as_of':clock,'result':mapped_import(ledger,account,content,definition,clock)}
                        frozen=st.session_state.get('v19-mapping-preview')
                        if frozen and frozen['basis']==basis:
                            result=frozen['result'];st.json(result)
                            if result.get('preview') and st.button('提交已预检映射账单'):
                                outcome=mapped_import(ledger,account,content,definition,frozen['as_of'],commit=True,
                                    expected_hash=result['expected_hash'],expected_sequence=result['preview']['expected_sequence'])
                                st.session_state.pop('v19-mapping-preview',None)
                                st.success(canonical(outcome));st.info('事实已提交；重新生成报告并与券商独立快照核对。')
                    except (QuantError,OSError,ValueError,KeyError) as exc:st.error(str(exc))
        with st.expander('期权实际持仓与履约资源'):
            st.caption('未提供可靠期权估值报价时，不把缺失价格记为零或显示完整净资产。')
            for row in ledger.connection.execute('SELECT id FROM accounts'):
                snapshot=ledger.snapshot(row[0],clock,{})
                st.json({key:snapshot.get(key) for key in ['account_id','as_of','option_positions','option_cash_collateral',
                    'option_covered_shares','reserved_cash','pending_option_exits','missing_prices','anomalies']})
        with st.expander('期权估值报价与来源核验'):
            from ..portfolio.report import load_account_report
            directory=Path(config.runtime_dir)/'reports/account-latest'
            if (directory/'latest.json').exists():
                try:
                    report=load_account_report(directory);valuation=report.get('valuation',{}).get('options')
                    if valuation:
                        kind='合成报价' if valuation.get('data_type')=='synthetic' else '来源待核验报价' if not valuation.get('source_assessment',{}).get('actual_source_qualified') else '已核验来源报价'
                        st.caption(f"{kind}；账户类型：{report['environment']}；报告截至：{pd.Timestamp(report['as_of']).tz_convert('Asia/Shanghai')}；账本序号：{report['ledger_seq']}")
                        rows=[]
                        for symbol,item in valuation.get('quotes',{}).items():
                            quote=item.get('quote') or {}
                            rows.append({'合约':symbol,'报价状态':item['status'],'出价':quote.get('bid'),'要价':quote.get('ask'),
                                '每报价单位中价':valuation.get('prices',{}).get(symbol),
                                '报价截至':str(pd.Timestamp(quote['exchange_timestamp']).tz_convert('Asia/Shanghai')) if quote else '缺失'})
                        if rows:st.dataframe(rows,use_container_width=True)
                        st.json({'估值状态':valuation['status'],'来源核验':valuation.get('source_assessment'),'检查结果':valuation.get('checks',[])})
                    else:st.info('已发布报告没有期权估值记录。')
                except (QuantError,OSError,ValueError,KeyError) as exc:st.error('期权估值报告核验失败：'+str(exc))
            else:st.info('尚无账户报告；先用显式报价快照生成估值报告。')
    if page=='运行状态':
        with st.expander('期权链与待核实凭据'):
            root=Path(config.runtime_dir)/'options/chains'
            st.json([json.loads(path.read_text()) for path in sorted(root.glob('*/manifest.json'))] if root.exists() else [])
            st.caption('链快照存在不等于真实来源合格；按决策时点运行options check-chain检查。')
            st.json([dict(row) for row in ledger.connection.execute('SELECT event_id,account_id,reason,created_at FROM pending_option_events')])
            st.caption('补齐同一原凭据缺失的合约/关系后，可用options pending-list及resolve-pending核实入账；不支持的公司行动仍保持阻断。')
            st.json([json.loads(row[0]) for row in ledger.connection.execute("SELECT details FROM tasks WHERE task_id LIKE 'option-resolution:%' ORDER BY updated_at DESC LIMIT 20")])
    if page=='调仓计划':
        with st.expander('期权计划、执行进度与阻断原因'):
            st.caption('草案不预留资源；合成历史demo A8须显式检查激活，READY不代表券商下单或真实交易权限。明确关联成交及实际担保单独记录；资金变化关闭未提交部分，保留在途订单与成交。以下为保存记录，执行前须按当前时点重新审阅。')
            for row in ledger.connection.execute('SELECT status,payload FROM option_plans ORDER BY created_at DESC'):
                st.json({**json.loads(row['payload']),'status':row['status']})
        with st.expander('期权退出冻结、取消与合成成交审计'):
            st.caption('仅合成历史演示。取消不释放实际持仓担保，平仓不自动卖出基础股票；保护撤除不表示风险已经下降。')
            for row in ledger.connection.execute("SELECT task_id,details FROM tasks WHERE task_id LIKE 'option-exit-%' ORDER BY updated_at DESC LIMIT 30"):
                st.json({'task_id':row['task_id'],**json.loads(row['details'])})
