"""Four-page read-only hedge view using the same monitoring service as daily jobs."""
from pathlib import Path
import pandas as pd
import streamlit as st

from ..common import QuantError
from ..hedging.monitor import monitor
from ..hedging.catalog import catalog


def controls(book,page,clock):
    with st.expander('对冲方法目录与支持等级'):
        result=catalog()
        st.caption(result['meaning'])
        frame=pd.DataFrame(result['methods'])
        labels={'CORE_ENGINEERING':'核心工程已实现','OPTION_TEMPLATE_ONLY':'仅期权叠加模板',
                'CONDITIONAL_NOT_IMPLEMENTED':'条件扩展尚未实现','QUALIFIED_INPUTS_REQUIRED':'需合格输入',
                'CATALOG_ONLY':'仅目录','ACCOUNT_CHECKS_REQUIRED':'需逐账户/来源检查','UNSUPPORTED':'未支持'}
        for name in ('support','research','paper','real'):
            frame[name]=frame[name].map(labels)
        st.dataframe(frame.rename(columns={
            'method_id':'方法标识','name':'方法','phase':'批次','purpose':'用途','risks':'主要风险',
            'required_inputs':'所需输入','hedge_spec_tool':'目标工具支持','support':'工程等级',
            'research':'研究门槛','paper':'前向门槛','real':'真实门槛','executable':'可执行'}),hide_index=True)
        st.caption('核心工程方法仍需逐账户检查；条件批次尚未实现执行。备兑Call是期权收益叠加，不视为完整下跌保护。')
    with st.expander('股票与期权对冲：父决定、执行与保护'):
        st.caption('只读对冲视图；原研究决定、实际成交、在途和保护引用分开显示。刷新不生成订单或财务事件。')
        accounts=[r[0] for r in book.connection.execute('SELECT id FROM accounts ORDER BY id')]
        if not accounts:
            st.info('尚无账户；可先进行策略研究，不假设已有资金或资产。')
            return
        account=st.selectbox('对冲查看账户',accounts,key='hedge-view-account')
        result=monitor(book,account,clock)
        st.caption(f"截至 {pd.Timestamp(result['as_of']).tz_convert('Asia/Shanghai')} · 类型 {result.get('data_type','账户诊断')} · 环境 {book.environment}")
        st.write('对冲监测状态',result['status'])
        if result['checks']:st.dataframe(pd.DataFrame(result['checks']))
        if page=='账户总览':
            coverage=result['current_coverage']
            if coverage:
                st.write('当前实际保护股数',coverage['actual_protected_shares'])
                st.write('在途意图股数（尚未形成实际保护）',coverage['inflight_intended_shares'])
                st.write('实际未分配期权风险',coverage['unallocated_actual_contracts'])
            else:st.info('尚无经核对的当前保护覆盖；缺失不按零风险处理。')
        elif page=='策略研究':
            if result['parents']:
                selected=st.selectbox('冻结对冲研究决定',result['parents'],format_func=lambda r:r['hedge_id'][:12],key='hedge-view-parent')
                try:
                    from ..hedging.archive import load
                    risk=load(book.path.parent/'hedging/exposures',selected['exposure_id'])
                    st.caption(f"原风险快照截至 {pd.Timestamp(risk['as_of']).tz_convert('Asia/Shanghai')} · 来源类型 {risk['data_types']}；不是当前敞口")
                    st.json({'risk':risk['risk'],'beta_model':risk['beta_model']})
                except (QuantError,OSError,ValueError) as exc:st.error('原对冲研究不可读：'+str(exc))
            else:st.info('尚无冻结对冲研究决定。')
        elif page=='调仓计划':
            parents=pd.DataFrame(result['parents'])
            for column in ('decision_at','generated_at','valid_until'):
                if column in parents:parents[column]=pd.to_datetime(parents[column],utc=True).dt.tz_convert('Asia/Shanghai')
            st.dataframe(parents)
            st.json({'execution_groups':result['progress'],'execution_group_versions':result['group_archive'],'closures':result['closures']})
            st.caption('执行组 COMPLETE 仅表示定义内成交及结算完成，不授予新的交易资格。')
        else:
            st.json(result)
            from ..options.receipt_risk import history
            try:
                st.write('逐笔期权凭据风险历史')
                st.json(history(book,account))
                st.caption('中间异常不会因批次最终余额恢复而删除；未提供报价时不判定估值、压力或交易资格。')
            except (QuantError,OSError,ValueError) as exc:
                st.error('逐凭据审计不可核对：'+str(exc))
            st.caption('逐阶段报价、来源、覆盖和压力资格仍独立检查；无法核实或有差异时暂停新计划。')

