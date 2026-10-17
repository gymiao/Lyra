"""Explicit read-only simulation index; UI refresh never starts an experiment."""
import json
import pandas as pd
import streamlit as st
from ..common import QuantError
from ..workspace.experiment_index import index


def controls():
    with st.expander('独立模拟实验目录'):
        st.caption('只读索引ETF和期权工作区；资金不合并，列表不是收益排名。')
        # Streamlit drops widget keys when their page is absent. Keep submitted
        # inputs in non-widget state, then restore before constructing widgets.
        for key,value in st.session_state.get('v195-index-context',{}).items():
            st.session_state.setdefault(key,value)
        with st.form('v195-experiment-index'):
            paths=st.text_area('实验工作区绝对路径（每行一项）',key='v195-index-paths')
            kind=st.selectbox('实验类型',['全部','etf','options'],key='v195-index-kind')
            state=st.text_input('运行状态筛选（留空为全部）',key='v195-index-status')
            template=st.text_input('策略模板代码筛选（留空为全部）',key='v195-index-template')
            version=st.text_input('已记录规则版本（留空为全部）',key='v195-index-version')
            start=st.text_input('区间开始不早于（YYYY-MM-DD，留空不限）',key='v195-index-start')
            end=st.text_input('区间结束不晚于（YYYY-MM-DD，留空不限）',key='v195-index-end')
            clicked=st.form_submit_button('读取实验目录')
        if clicked:
            st.session_state['v195-index-context']={'v195-index-paths':paths,'v195-index-kind':kind,
                'v195-index-status':state,'v195-index-template':template,'v195-index-version':version,'v195-index-start':start,'v195-index-end':end}
            filters={key:value for key,value in [('kind',kind if kind!='全部' else ''),('status',state.strip()),('template_id',template.strip()),
                ('strategy_version',version.strip()),('start_on_or_after',start.strip()),('end_on_or_before',end.strip())] if value}
            try:st.session_state['v195-experiment-index-result']=index({'workspaces':[p.strip() for p in paths.splitlines() if p.strip()],'filters':filters})
            except QuantError as exc:
                st.session_state.pop('v195-experiment-index-result',None);st.error(str(exc))
            st.session_state.pop('v195-experiment-comparison',None)
        result=st.session_state.get('v195-experiment-index-result')
        if result:
            st.dataframe(pd.DataFrame([{'工作区':r['workspace'],'类型':r['kind'],'运行ID':r['run_id'],'状态':r['status'],
                '数据类型':r['data_type'],'观察开始':r['observed_start'],'模拟截至':r['through_session'],'区间依据':r['period_basis'],
                '规则版本':', '.join(r['rule_versions']) or '尚无信号','策略模板':', '.join(r['templates']),'批注数':len(r['notes'])} for r in result['experiments']]))
            for error in result['errors']:st.warning(error['workspace']+'：'+error['reason'])
            st.download_button('导出实验目录及引用',json.dumps(result,ensure_ascii=False,indent=2),file_name='simulation-index.json')
            st.caption('完整可恢复实验使用experiment export导出；本文件是索引及批注，不含数据库或完整行情。')
            comparison_controls(result['experiments'])


def comparison_controls(rows):
    from pathlib import Path
    from ..workspace.experiments import compare
    complete={f"{i+1}. {Path(row['workspace']).name} · {row['kind']}":row for i,row in enumerate(rows) if row['status']=='COMPLETED'}
    if len(complete)<2:return
    with st.form('v195-compare-form'):
        selected=st.multiselect('选择2至7个同口径实验比较',list(complete),key='v195-compare-selected')
        clicked=st.form_submit_button('比较已完成实验')
    if clicked:
        request=[{'name':name,'workspace':complete[name]['workspace'],'run_id':complete[name]['run_id']} for name in selected]
        try:
            from .v20_workbench import submit
            from ..workspace.service import read_workspace
            from ..common import digest
            workspace=complete[selected[0]]['workspace'] if selected else rows[0]['workspace']
            root,_,config,_=read_workspace(workspace)
            destination=root/config.runtime_dir/'simulation/comparisons'/(digest(request)+'.json')
            submit(workspace,{'operation':'compare','members':request,'destination':str(destination)},'compare')
            st.session_state['v20-comparison-file']=str(destination)
        except QuantError as exc:
            st.session_state.pop('v195-experiment-comparison',None);st.error(str(exc))
    file=st.session_state.get('v20-comparison-file')
    if file and Path(file).is_file():
        try:st.session_state['v195-experiment-comparison']=json.loads(Path(file).read_text())
        except (OSError,ValueError):st.error('比较回执损坏，保留原文件并重新核实。')
    result=st.session_state.get('v195-experiment-comparison')
    if result:
        import ffn
        st.caption('合成历史模拟；下方为上次明确提交的比较。短样本年化仅供换算，不代表策略有效性。')
        frame=pd.DataFrame(result['curves'])
        st.line_chart(frame,x_label='市场交易日期',y_label='模拟权益 USD')
        st.line_chart(frame.apply(ffn.to_drawdown_series),x_label='市场交易日期',y_label='回撤（比例）')
        st.dataframe(pd.DataFrame(result['metrics']).T.rename(columns={'total_return':'累计收益','cagr':'年化收益',
            'max_drawdown':'最大回撤','annual_volatility':'年化波动率','observations':'观察点数','calendar_days':'观察自然日',
            'short_sample_annualization':'短样本年化'}))
        names={'recorded_cost':'账本已扣费用 USD','commission':'佣金 USD','bid_ask_cost':'价差解释 USD',
            'cost':'佣金及价差解释合计 USD','net_trading_pnl':'净交易盈亏 USD','turnover':'累计换手',
            'stock_trading_pnl':'股票交易现金流 USD','option_trading_pnl':'期权交易现金流 USD',
            'physical_delivery_cash_flow':'交割现金流 USD'}
        costs=pd.DataFrame(result['execution']).T
        st.dataframe(costs[[key for key in names if key in costs]].rename(columns=names))
        st.caption('价差成本已经体现在成交及净值中，费用解释不会再次扣减收益。不同资金、区间、数据或引擎的实验会拒绝比较。')
        st.download_button('导出比较曲线、口径与引用',json.dumps(result,ensure_ascii=False,indent=2),file_name='simulation-comparison.json')
