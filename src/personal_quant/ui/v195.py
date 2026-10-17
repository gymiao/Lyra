"""Managed simulation controls and per-subsystem data readiness."""
import json
from pathlib import Path
import pandas as pd
import streamlit as st
from ..common import QuantError


def controls(ledger,config,config_path,page,clock):
    if page=='策略研究':
        from .risk_lab import controls as risk_controls
        risk_controls()
        from .experiment_browser import controls as experiment_controls
        experiment_controls()
    runtime=Path(config.runtime_dir)
    if not (runtime/'simulation/workspace.json').exists():return
    from ..workspace.service import status,worker
    from ..workspace.jobs import list_jobs
    from .v20_workbench import launch_simulation as launch
    workspace=Path(config_path).absolute().parent
    if workspace.name=='configs':workspace=workspace.parent
    state=status(workspace)
    from .v20_workbench import controls as workbench_controls
    workbench_controls(workspace,config,page,clock)
    if state['identity']['kind']=='options':
        from .option_setup import controls as setup_controls
        setup_controls(workspace,config)
    with st.expander('模拟工作台',expanded=page=='运行状态'):
        st.caption(str(state['identity']['data_type'])+' · 独立模拟资金 · 查看日期不会推进模拟运行')
        st.write('初始模拟资金',state['identity']['initial_cash'],'账户',state['identity']['account_id'])
        if state['identity']['kind']=='options' and page in {'运行状态','调仓计划'}:
            from ..workspace.lifecycle_calendar import calendar_view
            lifecycle=calendar_view(ledger,state['identity']['account_id'],clock)
            st.subheader('期权生命周期日历')
            display=lambda value:str(pd.Timestamp(value).tz_convert('Asia/Shanghai')) if value else '待核实'
            names={'OPEN_RECORDED':'已记账持仓','CLOSED_RECORDED':'已记账关闭','PAST_CUTOFF_REQUIRE_RECEIPT':'已过截止，需核对凭据'}
            st.caption(lifecycle['meaning']+'；查看截至 '+display(lifecycle['as_of']))
            st.dataframe(pd.DataFrame([{'合约':c['contract_id'],'标的':c['underlying'],'实际张数':c['recorded_contracts'],
                '到期日（市场日期）':c['expiry'],'最后交易（上海时间）':display(c['last_trade_at']),
                '行权截止（上海时间）':display(c['exercise_cutoff_at']),'状态':names[c['status']]} for c in lifecycle['contracts']]))
            st.write('已记账凭据的待结算项目')
            st.dataframe(pd.DataFrame([{'凭据编号':e['event_id'],'类型':e['kind'],'标的':e['symbol'],
                '结算（上海时间）':display(e['settlement_at']),'状态':'待结算' if e['status']=='PENDING' else '时点未知'} for e in lifecycle['pending_settlements']]))
            st.write('已知决策与计划适用时间')
            st.dataframe(pd.DataFrame([{'来源':e['source'],'计划/信号':e.get('plan_id') or e.get('monthly_signal_id'),
                '决策（上海时间）':display(e['decision_at']),'适用日（市场日期）':e.get('applicable_session') or '未知',
                '适用收盘（上海时间）':display(e.get('applicable_close'))} for e in lifecycle['decisions']]))
            st.write('分红凭据与到账事项')
            st.dataframe(pd.DataFrame([{'标的':e['symbol'],'应收确认（上海时间）':display(e['accrual_at']),
                '金额':e['amount'],'预计到账（上海时间）':display(e['expected_payment_at']),
                '实际到账（上海时间）':display(e['paid_at']),'状态':e['status']} for e in lifecycle['dividends']]))
            if lifecycle['dividend_evidence']=='UNKNOWN_NO_RECEIPTS':st.caption('分红资料未知：尚无已记账凭据。')
            if lifecycle['calendar_checks']:st.warning('部分历史决策索引缺失或未核验，保留未知状态。')
            if lifecycle['account_checks']:st.warning('；'.join(lifecycle['account_checks']))
        option_args={}
        if state['identity']['kind']=='options':
            from ..processes import native_tools
            try:
                engine,sdk=native_tools()
                st.session_state.setdefault('v195-engine',str(engine))
                st.session_state.setdefault('v195-dotnet',str(sdk))
            except QuantError:pass
            st.caption('期权工作台需冻结合成信号、执行价格路径和本地 LEAN；这些输入不能作为真实行情凭据。')
            option_args={'input_file':st.text_input('冻结期权请求文件（绝对路径）',key='v195-option-file'),
                         'engine_root':st.text_input('LEAN 源码目录（绝对路径）',key='v195-engine'),
                         'dotnet':st.text_input('dotnet 可执行文件（绝对路径）',key='v195-dotnet'),
                         'fee_per_contract':st.number_input('每张期权每次成交费用（USD）',min_value=0.0,value=2.0,key='v195-option-fee')}
        if st.button('建立模拟运行',key='v195-start'):
            try:st.success(launch(workspace,'start',**option_args)['job_id'])
            except QuantError as exc:st.error(str(exc))
        if state['runs']:
            identity=st.selectbox('模拟运行',[r['run_id'] for r in state['runs']],key='v195-run')
            end=st.date_input('推进至交易日',value=pd.Timestamp(config.evaluation_end).date(),key='v195-through')
            with st.expander('批量运行预算'):
                sessions=st.number_input('每批最多交易日',min_value=1,max_value=10000,value=128,key='v195-batch-days')
                seconds=st.number_input('子任务最长秒数',min_value=.1,max_value=86400.,value=3600.,key='v195-batch-time')
                free=st.number_input('剩余空间保留 MiB',min_value=0,value=64,key='v195-batch-disk')
                st.caption('达到预算保留已提交检查点；可继续同一目标。超时只停止本批自有进程组，最多5秒结束宽限。')
            if st.button('后台继续模拟',key='v195-resume'):
                try:
                    paths={}
                    if state['identity']['kind']=='options' and st.session_state.get('v195-relocate-tools'):
                        paths={key:option_args[key] for key in ('engine_root','dotnet')}
                    st.success(launch(workspace,'batch',identity,str(end),max_sessions=sessions,max_seconds=seconds,min_free_bytes=free*1024**2,**paths)['job_id'])
                except QuantError as exc:st.error(str(exc))
            if state['identity']['kind']=='options':
                st.checkbox('更换外部引擎路径（继续任务）',key='v195-relocate-tools',help='勾选后使用上方LEAN及dotnet路径，内容须与原运行一致；未勾选时沿用已绑定路径')
            if st.button('请求安全暂停',key='v195-pause'):
                try:st.info('已请求在提交边界暂停' if worker(workspace,'pause',identity).get('pause_requested') else '已暂停')
                except QuantError as exc:st.error(str(exc))
            st.dataframe(pd.DataFrame(state['runs']))
        job_status(workspace,list_jobs(workspace))
        if st.button('刷新模拟状态',key='v195-refresh'):st.rerun()
    if page=='运行状态':
        from ..workspace.readiness import describe
        try:st.dataframe(pd.DataFrame(describe(workspace)))
        except (QuantError,OSError,ValueError,KeyError) as exc:st.error('无法读取状态元数据：'+str(exc))
        maintenance_controls(workspace)
        if st.button('准备脱敏诊断',key='v195-diagnostic'):
            from ..workspace.diagnostic import view
            try:st.session_state['v195-diagnostic-data']=view(workspace)
            except (QuantError,OSError,ValueError,KeyError) as exc:st.error('诊断失败：'+str(exc))
        from ..common import digest
        diagnostic=st.session_state.get('v195-diagnostic-data')
        if diagnostic and diagnostic.get('workspace_hash')==digest(state['identity']['workspace_id']):
            st.caption('诊断快照截至 '+diagnostic['generated_at']+'；白名单元数据，不含账单/数据库/配置值。调度安装未核验。')
            st.download_button('下载脱敏诊断JSON',json.dumps(diagnostic,ensure_ascii=False,indent=2),
                file_name='LyraX-diagnostic.json',mime='application/json',key='v195-diagnostic-download')


def job_status(workspace,initial):
    """Poll receipts only; finishing a job refreshes the parent controls once."""
    from ..workspace.jobs import list_jobs
    active=any(row['status']=='RUNNING' for row in initial)
    @st.fragment(run_every='3s' if active else None)
    def render():
        rows=list_jobs(workspace)
        from .v20_workbench import job_rows
        st.dataframe(pd.DataFrame(job_rows(rows)),hide_index=True)
        if active and not any(row['status']=='RUNNING' for row in rows):st.rerun()
    render()


def maintenance_controls(workspace):
    from ..workspace.maintenance import summary,verify
    with st.expander('备份核验与隔离恢复演练'):
        st.caption('显式核验完整备份；恢复到新目录，不新增入金或交易。历史核验不能保证备份以后未变。')
        source=st.text_input('当前工作区完整备份目录',key='v195-backup-source')
        target=st.text_input('隔离恢复的新目录',key='v195-recovery-target')
        for label,destination in [('完整核验备份',None),('核验并隔离恢复',target)]:
            if st.button(label,key='v195-maintenance-'+str(destination is not None)):
                try:
                    if not source or (destination is not None and not destination):
                        raise QuantError('BACKUP_ARGUMENT_REQUIRED','填写备份目录；演练还需新的恢复目录')
                    result=verify(workspace,source,destination=destination)
                    if result['status']=='VERIFIED':st.success('完整验证通过，已登记实际时间')
                    else:st.warning('验证/恢复已完成，但记录未写入；不要覆盖已有恢复目录，请检查存储。')
                except (QuantError,OSError,ValueError,KeyError) as exc:st.error(str(exc))
        try:
            result=summary(workspace)
            rows=[{**row,**{field:str(pd.Timestamp(row[field]).tz_convert('Asia/Shanghai'))
                    for field in ('verified_at','backup_created_at') if row.get(field)}} for row in result['records']]
            if rows:st.dataframe(pd.DataFrame(rows))
            else:st.info('尚无本工作区的完整备份核验或隔离恢复记录。')
            st.caption(result['meaning']+'；展示时区 Asia/Shanghai')
        except (QuantError,OSError,ValueError,KeyError) as exc:st.error('无法读取维护记录：'+str(exc))
