"""Chinese v1.8 controls, sharing the CLI services and persistent versions."""
import json
from pathlib import Path
from uuid import uuid4
import pandas as pd
import streamlit as st
from ..common import QuantError, canonical
from ..strategies.store import enable_v18, StrategyStore
from ..data.catalog import DataCatalog
from ..diagnostics import doctor, sync_notices, notices, acknowledge
from ..research.validation import ValidationService
from ..research.service import ResearchService
from ..research.artifacts import export_package


def guarded(function):
    try:return function()
    except (QuantError,ValueError,OSError,KeyError,TypeError) as exc:st.error(str(exc));return None


def controls(ledger,config,config_path,page,clock):
    if page=='策略研究':
        from .options import controls as option_controls
        option_controls()
    version=ledger.connection.execute('SELECT version FROM schema_version').fetchone()[0]
    if version<4:
        with st.expander('启用 v1.8 数据管理与验证'):
            st.caption('先完整备份再升级；数据用途由你明确选择，既有资金和成交保留。')
            if st.button('备份并启用 v1.8'):
                result=guarded(lambda:enable_v18(ledger,config_path))
                if result:st.success(canonical(result));st.rerun()
        return
    with st.expander('数据来源与用途'):
        catalog=DataCatalog(ledger)
        if st.button('核验并登记已有行情系列'):
            guarded(catalog.refresh)
        state=catalog.list()
        options={row['series_id']:json.loads(row['metadata']) for row in state['series']}
        if options:
            role=st.selectbox('选择数据用途',['signal','execution','valuation','factor'],format_func=lambda x:{'signal':'研究和信号','execution':'真实份额与模拟成交','valuation':'账户估值与对账','factor':'PIT 因子'}[x])
            identity=st.selectbox('选择已核验的数据系列',list(options),format_func=lambda x:str(options[x].get('source',options[x].get('metadata',{}).get('source')))+' / '+str(options[x].get('price_basis','PIT factor'))+' / '+x[:8])
            revisions={r['role']:r['revision'] for r in state['roles']}
            if st.button('确认用途绑定'):
                result=guarded(lambda:catalog.bind(role,identity,expected_revision=revisions.get(role,0)))
                if result:st.success('用途已更新；历史信号与旧计划仍引用原快照。');st.rerun()
        else:st.info('先导入行情，再登记系列。')
        st.dataframe(pd.DataFrame(state['roles']))
    if page=='策略研究':
        validation=ValidationService(ledger,config)
        with st.expander('分段与成本验证'):
            st.caption('固定规则在独立窗口从同额现金开始；不拼接净值，不自动选择收益最高的策略。')
            refs={f"{v['strategy_id']}@{v['revision']}":v for v in StrategyStore(ledger).list()}
            if len(refs)>=2:
                benchmark=st.selectbox('验证基准',list(refs))
                candidates=st.multiselect('验证候选',[name for name in refs if name!=benchmark])
                start=st.text_input('验证起点',config.evaluation_start,key='v18-start')
                end=st.text_input('验证终点',config.evaluation_end,key='v18-end')
                months=st.number_input('独立窗口月数',min_value=1,max_value=36,value=6)
                costs=st.multiselect('佣金、滑点及固定费用倍数',[1,2,3],default=[1,2])
                retry=st.checkbox('明确重跑失败子实验')
                if st.button('冻结并提交后台验证'):
                    def submit():
                        from ..data.selection import selected
                        from ..data.store import DataStore
                        from ..strategies.spec import DataBundle
                        _,metadata,calendar=selected(DataStore(ledger.path.parent/'data'),'signal')
                        windows=[];date=pd.Timestamp(start);stop=pd.Timestamp(end)
                        while date<=stop:
                            last=min(date+pd.DateOffset(months=int(months))-pd.Timedelta(days=1),stop)
                            windows.append({'start':str(date.date()),'end':str(last.date())});date=last+pd.Timedelta(days=1)
                        members={f'member_{i}':{'strategy_id':refs[name]['strategy_id'],'revision':refs[name]['revision']} for i,name in enumerate([benchmark]+candidates)}
                        from ..data.selection import factor_snapshot
                        request={'members':members,'benchmark_member_id':'member_0','data_bundle':DataBundle(metadata['snapshot_id'],calendar.hash,factor_snapshot_id=factor_snapshot(DataStore(ledger.path.parent/'data'))).content(),
                            'windows':windows,'cost_scenarios':[{'id':f'cost_{c}','commission_multiplier':c,'slippage_multiplier':c,'fixed_fee_multiplier':c} for c in costs]}
                        suite=validation.create(request)
                        return validation.launch(suite['suite_id'],retry=retry)
                    result=guarded(submit)
                    if result:st.success('验证任务已登记：'+result['suite_id'])
            suites=validation.list()
            if st.button('刷新验证任务'):st.rerun()
            if suites:
                chosen=st.selectbox('查看验证套件',[s['suite_id'] for s in suites]);suite=validation.get(chosen)
                st.write('套件状态',suite['status'])
                st.dataframe(pd.DataFrame([{'window':i['payload']['window'],'cost':i['payload']['cost_id'],'status':i['status'],'attempt_id':i['attempt_id']} for i in suite['items']]))
                st.expander('窗口指标与失败原因').json([i['details'] for i in suite['items']])
                if st.button('核实中断验证任务'):guarded(lambda:validation.recover(chosen))
                if st.button('继续未完成验证任务'):guarded(lambda:validation.launch(chosen,retry=retry))
        with st.expander('登记研究协议'):
            st.caption('登记未来观察规则及开始时间；历史区间只能作为已观察验证。需要按协议冻结规格，修改建立新协议。')
            content=st.text_area('协议 JSON（name、specification、future_start）',height=130)
            if st.button('校验并登记研究协议'):
                result=guarded(lambda:validation.protocol(json.loads(content)))
                if result:st.success(result['protocol_id'])
            st.dataframe(pd.DataFrame([dict(r) for r in ledger.connection.execute('SELECT protocol_id,created_at FROM validation_protocols')]))
        with st.expander('可还原研究包'):
            successful=[r for r in ResearchService(ledger).list() if r['status']=='SUCCESS']
            if successful:
                run_id=st.selectbox('选择要归档的研究',[r['run_id'] for r in successful])
                if st.button('导出源码、锁文件和研究输入'):
                    destination=Path('reports/research-packages')/(run_id+'-'+uuid4().hex[:8])
                    result=guarded(lambda:export_package(ResearchService(ledger),run_id,destination))
                    if result:st.success('研究包已保存：'+str(destination));st.json(result)
    if page=='运行状态':
        with st.expander('环境与数据就绪检查',expanded=True):
            diagnostic=doctor(config,clock)
            st.write('诊断状态',diagnostic['status'])
            from ..diagnostics import display_checks
            st.dataframe(pd.DataFrame(display_checks(diagnostic)))
            if st.button('核验历史研究报告完整性'):
                guarded(lambda: st.json(doctor(config,clock,verify_reports=True)))
            if st.button('同步本地待办'):guarded(lambda:sync_notices(ledger,diagnostic));st.rerun()
            items=notices(ledger);st.dataframe(pd.DataFrame(items))
            if items:
                identity=st.selectbox('待办记录',[n['notice_id'] for n in items])
                if st.button('确认已读（不解除阻断）'):guarded(lambda:acknowledge(ledger,identity));st.rerun()
