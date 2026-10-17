"""Read-only option scenario lab integrated in the existing research page."""
import pandas as pd
import json
import streamlit as st
from ..common import QuantError
from ..options.catalog import A8, catalog
from ..options.service import scenario
from ..options.pricing import price

LABELS={'wheel':'Wheel（按实际交割切换Put/Call）','long_call':'买入Call','long_put':'买入Put','protective_put':'保护Put','covered_call':'备兑Call',
        'cash_secured_put':'现金担保Put','collar':'领式Collar','bull_call_debit_spread':'牛Call借记价差',
        'bear_put_debit_spread':'熊Put借记价差','long_straddle':'买入跨式','long_strangle':'买入宽跨式',
        'bull_put_credit_spread':'牛Put信用价差','bear_call_credit_spread':'熊Call信用价差','iron_condor':'铁鹰','iron_butterfly':'铁蝶'}


def controls():
    with st.expander('期权研究：策略目录与到期情景'):
        st.caption('数据类型：理论情景；不含真实报价、历史回测或账户成交。期权组合需独立核对担保与提前指派。')
        with st.form('option-scenario'):
            identifier=st.selectbox('首批情景模板',sorted(A8),format_func=lambda x:LABELS[x])
            spot=st.number_input('标的参考价（情景参数）',min_value=.01,value=100.)
            multiplier=st.number_input('每张报价乘数（情景参数）',min_value=1,value=100)
            premium=st.number_input('第一期权腿权利金',min_value=0.,value=2.)
            other=st.number_input('价差第二腿权利金',min_value=0.,value=1.)
            fee=st.number_input('每条期权腿费用',min_value=0.,value=0.)
            expiry=st.date_input('共同到期日',value=pd.Timestamp('2026-12-18').date())
            submit=st.form_submit_button('计算到期情景')
        if submit:
            try:
                result=scenario({'template_id':identifier,'parameters':{'spot':spot,'multiplier':multiplier,
                    'premium':premium,'second_premium':other,'fee':fee,'expiry':str(expiry)}})
                st.session_state['option-scenario-result']=result
            except (QuantError,TypeError,ValueError) as exc:st.error(str(exc))
        result=st.session_state.get('option-scenario-result')
        if result:
            frame=pd.DataFrame(result['points']).astype(float)
            st.line_chart(frame.set_index('underlying_price'),y='pnl',x_label='到期标的价格',y_label='组合盈亏 USD')
            st.write('最大盈利：', '无限' if result['profit_unbounded'] else result['maximum_profit'])
            st.write('最大亏损：', '无限' if result['loss_unbounded'] else result['maximum_loss'])
            st.write('盈亏平衡价格：',result['break_even_prices'])
            st.dataframe(pd.DataFrame(result['legs']));st.caption(result['limitations'][0])
        rows=[{'类别':family['name'],'策略':row['template_id'],'情景能力':row['scenario'],
               '历史回测':row['historical'],'模拟跟踪':row['paper'],'真实账户':row['real']}
              for family in catalog() for row in family['strategies']]
        st.dataframe(pd.DataFrame(rows),hide_index=True)
    with st.expander('期权理论价格与 Greeks（QuantLib）'):
        with st.form('option-pricing'):
            right=st.selectbox('期权类型',['CALL','PUT'])
            style=st.selectbox('行权方式',['AMERICAN','EUROPEAN'])
            spot=st.number_input('理论标的价格',min_value=.01,value=100.)
            strike=st.number_input('行权价格',min_value=.01,value=100.)
            valuation=st.date_input('理论估值日',value=pd.Timestamp('2026-10-10').date())
            expiry=st.date_input('理论到期日',value=pd.Timestamp('2026-12-18').date())
            sigma=st.number_input('年化波动率',min_value=.0002,max_value=4.,value=.2)
            rate=st.number_input('年化无风险利率',min_value=-.99,max_value=.99,value=.04)
            dividends=st.number_input('连续年化分红率（模型假设）',min_value=0.,max_value=.99,value=.01)
            multiplier=st.number_input('理论每张乘数',min_value=1,value=100)
            discrete=st.text_area('已知离散分红（情景JSON，选填）',help='列表中的每项为ex_date与amount_per_share；使用时连续年化分红率必须为0，不能重复计分红。')
            submit=st.form_submit_button('计算理论价格与敏感度')
        if submit:
            try:st.json(price(right=right,style=style,spot=spot,strike=strike,valuation_date=str(valuation),
                expiry=str(expiry),volatility=sigma,rate=rate,dividend_yield=dividends,multiplier=multiplier,
                discrete_dividends=json.loads(discrete) if discrete.strip() else None))
            except (QuantError,ValueError,TypeError) as exc:st.error(str(exc))
