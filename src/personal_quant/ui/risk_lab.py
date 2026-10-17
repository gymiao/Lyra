"""Model-only multi-axis option stress, sharing QuantLib and existing leg schemas."""
import json
from datetime import date,timedelta
import pandas as pd
import streamlit as st
from ..common import QuantError,digest
from ..options.stress import evaluate,model_identity


def cached_result(key):
    result=st.session_state.get(key)
    if result and (result.get('model_identity')!=model_identity() or digest(result.get('request'))!=result.get('request_hash')):
        st.session_state.pop(key,None)
        st.warning('模型/依赖、计算精度或已缓存输入已变化，旧结果未作为当前模型展示；请显式重新计算。')
        return None
    return result


def controls():
    for key,value in st.session_state.get('v195-stress-context',{}).items():st.session_state.setdefault(key,value)
    with st.expander('组合风险图：价格、波动率与期限'):
        st.caption('理论情景 · 使用显式模型参数 · 有限网格不能证明最大亏损；不产生账户事件')
        with st.form('v195-risk-grid'):
            legs=st.text_area('标准组合腿 JSON',value='[]',key='v195-stress-legs')
            models=st.text_area('每条期权腿的模型 JSON',value='{}',key='v195-stress-models',help='按腿索引提供style、volatility、rate、dividend_yield')
            valuation=st.date_input('组合模型估值日',key='v195-valuation')
            horizon=st.date_input('组合压力时点',key='v195-horizon')
            prices=st.text_input('压力标的价格（逗号分隔）','80,90,100,110,120',key='v195-stress-prices')
            scales=st.text_input('波动率倍率（逗号分隔）','0.8,1,1.2',key='v195-stress-iv')
            submitted=st.form_submit_button('计算组合风险图')
        if submitted:
            st.session_state['v195-stress-context']={'v195-stress-legs':legs,'v195-stress-models':models,
                'v195-valuation':valuation,'v195-horizon':horizon,'v195-stress-prices':prices,'v195-stress-iv':scales}
            try:
                request={'legs':json.loads(legs),'models':json.loads(models),'valuation_date':str(valuation),'horizon_date':str(horizon),
                         'underlying_prices':[x.strip() for x in prices.split(',')],'volatility_multipliers':[x.strip() for x in scales.split(',')]}
                st.session_state['v195-stress-result']=evaluate(request)
            except (QuantError,ValueError,TypeError,KeyError) as exc:
                st.session_state.pop('v195-stress-result',None);st.error(str(exc))
        result=cached_result('v195-stress-result')
        if result:
            st.caption('以下为上次明确提交的冻结参数结果；未提交的表单修改不改变结果。')
            st.json(result['request'],expanded=False)
            frame=pd.DataFrame(result['points'])
            for field in ('underlying_price','volatility_multiplier','pnl'):frame[field]=frame[field].astype(float)
            grid=frame.pivot_table(index='underlying_price',columns='volatility_multiplier',values='pnl')
            st.dataframe(grid.style.background_gradient(cmap='RdYlGn'),use_container_width=True)
            st.line_chart(grid,x_label='压力标的价格',y_label='组合盈亏 USD')
            st.write('网格最差亏损 USD',result['worst_sample_loss'])
            st.write('理论最大亏损','未由有限网格推定')
            st.dataframe(pd.DataFrame([{'标的价格':p['underlying_price'],'IV倍率':p['volatility_multiplier'],
                'Greeks完整':p['greeks_complete'],**p['greeks']} for p in result['points']]))
            st.caption(result['greek_scope'])
            st.json(result['greek_units'],expanded=False)
            st.dataframe(pd.DataFrame([{'标的价格':p['underlying_price'],'IV倍率':p['volatility_multiplier'],
                '腿序号':leg['leg_index'],'类型':leg['kind'],'数量':leg['quantity'],'乘数':leg['multiplier'],
                '理论价值 USD':leg['value'],'Greeks完整':leg['greeks_complete'],'缺失原因':leg['missing_reason'],**leg['greeks']}
                for p in result['points'] for leg in p['leg_values']]))
            st.caption('；'.join(result['limitations']))
            st.download_button('导出组合风险情景',json.dumps(result,ensure_ascii=False,indent=2),file_name='risk-scenario.json')
    comparison_controls()


def comparison_controls():
    from ..options.risk_lab import compare
    with st.expander('同资本保护Put、Collar、持股与现金'):
        for key,value in st.session_state.get('v195-risk-context',{}).items():st.session_state.setdefault(key,value)
        st.caption('纯理论工程假设 · 每包100股 · 不读取行情、不产生计划或账本事件')
        with st.form('v195-risk-controls'):
            cash=st.number_input('共同初始模拟资金 USD',min_value=1.,value=20000.,key='v195-risk-cash')
            spot=st.number_input('建仓标的参考价 USD',min_value=.01,value=100.,key='v195-risk-spot')
            packages=st.number_input('包数（每包100股及1张期权）',min_value=1,max_value=100,value=1,key='v195-risk-packages')
            put=st.number_input('Put行权价 USD',min_value=.01,value=95.,key='v195-risk-put')
            call=st.number_input('Call行权价 USD',min_value=.01,value=105.,key='v195-risk-call')
            put_price=st.number_input('假设Put权利金（每报价单位USD）',min_value=0.,value=2.,key='v195-risk-put-price')
            call_price=st.number_input('假设Call权利金（每报价单位USD）',min_value=0.,value=1.,key='v195-risk-call-price')
            fee=st.number_input('期权建仓费用 USD/张',min_value=0.,value=2.,key='v195-risk-fee')
            bps=st.number_input('股票建仓佣金 bps',min_value=0.,value=2.,key='v195-risk-bps')
            budget=st.number_input('长期权及期权费用预算 USD',min_value=0.,value=1000.,key='v195-risk-budget')
            style=st.selectbox('模型行权方式',['EUROPEAN','AMERICAN'],key='v195-risk-style')
            vol=st.number_input('模型波动率（比例）',min_value=.001,max_value=4.,value=.2,key='v195-risk-vol')
            rate=st.number_input('模型利率（比例）',min_value=-.99,max_value=.99,value=.04,key='v195-risk-rate')
            dividend=st.number_input('连续分红率（比例）',min_value=0.,max_value=.99,value=0.,key='v195-risk-dividend')
            valuation=st.date_input('对照估值日',value=date.today(),key='v195-risk-value-date')
            expiry=st.date_input('共同到期日',value=date.today()+timedelta(days=90),key='v195-risk-expiry')
            horizon=st.date_input('对照压力时点',value=date.today()+timedelta(days=30),key='v195-risk-horizon')
            prices=st.text_input('对照压力价格（逗号分隔）','80,90,100,110,120',key='v195-risk-world-prices')
            scales=st.text_input('对照IV倍率（逗号分隔）','0.8,1,1.2',key='v195-risk-world-iv')
            submitted=st.form_submit_button('比较同资本风险情景')
        if submitted:
            keys=('v195-risk-cash','v195-risk-spot','v195-risk-packages','v195-risk-put','v195-risk-call',
                'v195-risk-put-price','v195-risk-call-price','v195-risk-fee','v195-risk-bps','v195-risk-budget',
                'v195-risk-style','v195-risk-vol','v195-risk-rate','v195-risk-dividend','v195-risk-value-date',
                'v195-risk-expiry','v195-risk-horizon','v195-risk-world-prices','v195-risk-world-iv')
            st.session_state['v195-risk-context']={key:st.session_state[key] for key in keys}
            request={'schema_version':1,'initial_cash':cash,'stock_price':spot,'packages':packages,'put_strike':put,
                'call_strike':call,'put_premium':put_price,'call_premium':call_price,'fee_per_contract':fee,
                'stock_commission_bps':bps,'maximum_premium_budget':budget,'style':style,'volatility':vol,'rate':rate,
                'dividend_yield':dividend,'valuation_date':str(valuation),'expiry':str(expiry),'horizon_date':str(horizon),
                'underlying_prices':[p.strip() for p in prices.split(',')],'volatility_multipliers':[p.strip() for p in scales.split(',')]}
            try:st.session_state['v195-risk-comparison']=compare(request)
            except (QuantError,ValueError,TypeError,KeyError) as exc:
                st.session_state.pop('v195-risk-comparison',None);st.error(str(exc))
        result=cached_result('v195-risk-comparison')
        if result:
            st.caption('下方为上次提交的完整同资本模型；查看/切换IV不产生新计算或账户事件。')
            st.json(result['request'],expanded=False)
            names={'protective_put':'保护Put','collar':'Collar','stock':'仅持股','cash':'现金'}
            rows=[{'组合':names[name],'标的价格':float(p['underlying_price']),'IV倍率':p['volatility_multiplier'],
                '权益 USD':float(p['equity']),'盈亏 USD':float(p['pnl'])} for name,body in result['controls'].items() for p in body['points']]
            frame=pd.DataFrame(rows)
            scale=st.selectbox('查看对照IV倍率',list(dict.fromkeys(frame['IV倍率'])),key='v195-risk-view-iv')
            st.line_chart(frame[frame['IV倍率']==scale].pivot(index='标的价格',columns='组合',values='盈亏 USD'))
            st.dataframe(pd.DataFrame([{'组合':names[name],'初始资本':body['initial_cash'],'股数':body['stock_shares'],
                '剩余现金':body['uninvested_cash'],'期权净权利金':body['net_option_premium'],
                '长期权预算使用':body['long_premium_budget_used'],'建仓费用':body['entry_fees'],
                '股票覆盖占用（股）':body['covered_call_shares'],'网格最差亏损':body['worst_sample_loss']} for name,body in result['controls'].items()]))
            st.json(result['greek_units'],expanded=False)
            st.dataframe(pd.DataFrame([{'组合':names[name],'标的价格':p['underlying_price'],'Greeks完整':p['greeks_complete'],**p['greeks']}
                for name,body in result['controls'].items() for p in body['points'] if p['volatility_multiplier']==scale]))
            st.dataframe(pd.DataFrame([{'组合':names[name],'标的价格':p['underlying_price'],'类型':leg['kind'],
                '数量':leg['quantity'],'乘数':leg['multiplier'],'理论价值':leg['value'],'Greeks完整':leg['greeks_complete'],
                '缺失原因':leg['missing_reason'],**leg['greeks']}
                for name,body in result['controls'].items() for p in body['points'] if p['volatility_multiplier']==scale for leg in p['leg_values']]))
            st.caption('；'.join(result['assumptions']))
            st.caption('有限网格最差结果不等于最大亏损保证；到期Greeks缺失不填零。下载保存本次全部输入与逐腿模型结果。')
            st.download_button('导出同资本风险对照',json.dumps(result,ensure_ascii=False,indent=2),file_name='risk-controls.json')
