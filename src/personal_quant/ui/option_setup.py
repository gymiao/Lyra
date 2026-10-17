"""Chinese configuration for explicitly synthetic, fixed two-cycle examples."""
import json
from pathlib import Path
import streamlit as st
from ..common import QuantError,digest,write_json
from ..options.catalog import MONTHLY_RESEARCH
from .v20_workbench import launch_simulation as launch
from ..workspace.option_setup import load
from .options import LABELS


def controls(workspace,config):
    runtime=Path(workspace)/config.runtime_dir
    with st.expander('期权模拟配置：冻结输入与月度规则'):
        st.caption('合成数据 · 2024年10/11月月末决策 · 标的恒100 · 非实际行情/合约。准备不入金或成交；更改参数不会覆盖已有运行。')
        with st.form('v195-option-setup'):
            bundle=st.text_input('多月场景输入包（留空使用固定两月样例）',key='v20-setup-bundle')
            cycles=st.number_input('最多月度周期',min_value=1,max_value=24,value=12,key='v20-setup-cycles')
            retain=st.checkbox('持续持股滚动（保护Put/备兑Call/Collar）',value=True,key='v20-setup-retain')
            templates=sorted(MONTHLY_RESEARCH|{'wheel'})
            template=st.selectbox('月度期权模板',templates,index=templates.index('protective_put'),format_func=lambda key:LABELS[key],key='v195-setup-template')
            underlying=st.selectbox('合成标的',list(config.symbols),key='v195-setup-underlying')
            packages=st.number_input('每周期包数',min_value=1,max_value=100,value=1,key='v195-setup-packages')
            fee=st.number_input('冻结期权费用 USD/张/次',min_value=0.,value=2.,key='v195-setup-fee')
            mode=st.selectbox('模拟计划模式',['仅研究调度','公共计划与风险检查'],key='v195-setup-mode')
            st.caption('仅研究调度不生成公共可执行计划；公共模式需要当前合成引擎资格和完整风险配置，不等于真实权限。')
            minimum=st.number_input('最小到期天数',min_value=1,value=30,key='v195-setup-min-dte')
            target=st.number_input('目标到期天数',min_value=1,value=45,key='v195-setup-target-dte')
            maximum=st.number_input('最大到期天数',min_value=1,value=80,key='v195-setup-max-dte')
            put=st.number_input('Put行权价/标的价',min_value=.01,max_value=.99,value=.95,key='v195-setup-put')
            call=st.number_input('Call行权价/标的价',min_value=1.01,value=1.05,key='v195-setup-call')
            exit_days=st.number_input('到期前退出自然日数',min_value=0,value=7,key='v195-setup-exit')
            width=st.number_input('信用价差最小宽度 USD',min_value=.01,value=5.,key='v195-setup-width')
            age=st.number_input('最大报价年龄（秒）',min_value=0,value=3600,key='v195-setup-age')
            spread=st.number_input('最大买卖价差比例',min_value=0.,max_value=1.,value=.25,key='v195-setup-spread')
            skew=st.number_input('最大标的时间偏差（秒）',min_value=0,value=60,key='v195-setup-skew')
            leg_skew=st.number_input('最大腿间时间偏差（秒）',min_value=0,value=10,key='v195-setup-leg-skew')
            deviation=st.number_input('最大腿间标的价格偏离比例',min_value=0.,max_value=1.,value=.01,key='v195-setup-deviation')
            st.caption('公共模式参数（仅选择公共模式时使用）；金额单位USD，预算不代表个人风险承受能力。')
            evidence=st.text_input('当前合成引擎生命周期验收文件',key='v195-setup-evidence')
            premium=st.number_input('权利金预算 USD',min_value=0.,value=1000.,key='v195-setup-premium')
            loss=st.number_input('最大模型亏损预算 USD',min_value=0.,value=30000.,key='v195-setup-loss')
            notional=st.number_input('每包标的等值名义金额上限 USD',min_value=0.,value=30000.,key='v195-setup-notional')
            contracts=st.number_input('每腿最大合约张数',min_value=1,value=1,key='v195-setup-contracts')
            adverse=st.number_input('可接受不利价格偏离比例',min_value=0.,max_value=.99,value=0.,key='v195-setup-adverse')
            buffer=st.number_input('期权计划现金缓冲 USD',min_value=0.,value=10.,key='v195-setup-buffer')
            reserve=st.number_input('提前指派额外现金预留 USD',min_value=0.,value=0.,key='v195-setup-reserve')
            reconcile=st.number_input('内部对账最长间隔（天）',min_value=0,value=1,key='v195-setup-reconcile')
            window=st.number_input('执行窗口交易日数（两月样例至少2）',min_value=2,value=5,key='v195-setup-window')
            clicked=st.form_submit_button('后台冻结合成配置')
        if clicked:
            params={'minimum_dte':minimum,'target_dte':target,'maximum_dte':maximum,'put_moneyness':put,'call_moneyness':call,
                'exit_days_before_expiry':exit_days,'max_age_seconds':age,'max_spread_fraction':spread,
                'max_underlying_skew_seconds':skew,'max_leg_skew_seconds':leg_skew,'max_underlying_price_fraction':deviation}
            if template.endswith('credit_spread') or template in {'iron_condor','iron_butterfly'}:params['minimum_spread_width']=width
            policy=None
            if mode=='公共计划与风险检查':policy={'risk':{'premium_budget':premium,'maximum_loss_budget':loss,
                'maximum_notional':notional,'maximum_contracts':contracts,'fee_per_contract':fee,'adverse_slippage_fraction':adverse,
                'cash_buffer':buffer,'early_assignment_cash_reserve':reserve},'engine_evidence_file':evidence,
                'reconciliation_max_days':reconcile,'execution_window_sessions':window}
            spec={'schema_version':1,'template_id':template,'underlying':underlying,'packages':packages,'fee_per_contract':fee,
                'selection_parameters':params,'plan_policy':policy}
            if bundle:spec.update(input_bundle=bundle,max_cycles=cycles,retain_stock=retain)
            if template=='wheel':
                spec.update(engine_root=st.session_state.get('v195-engine',''),dotnet=st.session_state.get('v195-dotnet',''),cash_buffer=buffer)
                spec['selection_parameters']['exit_days_before_expiry']=0
            file=runtime/'simulation/setup-requests'/(digest(spec)+'.json')
            try:
                write_json(file,spec);st.success(launch(workspace,'prepare',input_file=file)['job_id'])
            except (QuantError,OSError) as exc:st.error(str(exc))
        choices={}
        for file in (runtime/'simulation/setups').glob('*/setup-manifest.json'):
            try:
                body=json.loads(file.read_text());spec=body['basis']['spec']
                choices[file.parent.name]=(file.parent,f"{LABELS.get(spec['template_id'],spec['template_id'])} · {spec['underlying']} · {spec['packages']}包 · {body.get('cycle_count',2)}周期 · {body['mode']}")
            except (OSError,ValueError,KeyError,TypeError):st.warning('有不完整配置，需查看运行错误；不会自动使用。')
        if choices:
            selected=st.selectbox('已冻结配置',list(choices),format_func=lambda key:choices[key][1],key='v195-setup-selected')
            if st.button('核验并使用该配置',key='v195-setup-use'):
                try:
                    directory=choices[selected][0];body=load(directory)
                    st.session_state['v195-option-file']=str(directory/'request.json')
                    st.session_state['v195-option-fee']=float(body['basis']['spec']['fee_per_contract'])
                    st.session_state['v195-active-setup']=body
                except QuantError as exc:st.error(str(exc))
        active=st.session_state.get('v195-active-setup')
        if active:
            st.caption('已选配置只冻结输入；尚需明确建立模拟运行并推进。'+active['mode'])
            st.write('首日',active['first_session'],'最后行情日',active['last_market_session'],'最后结算日',active['last_settlement_session'])
            st.json(active['basis']['spec'],expanded=False)
