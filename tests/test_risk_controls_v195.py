import copy
from datetime import date
import pytest
from streamlit.testing.v1 import AppTest
from personal_quant.common import QuantError
from personal_quant.options.risk_lab import compare
from personal_quant.options.stress import evaluate


def request():
    return {'schema_version':1,'initial_cash':'20000','stock_price':'100','packages':1,'put_strike':'95',
        'call_strike':'105','put_premium':'2','call_premium':'1','fee_per_contract':'2','stock_commission_bps':'2',
        'maximum_premium_budget':'1000','style':'EUROPEAN','volatility':'.2','rate':'.04','dividend_yield':'0',
        'valuation_date':'2026-10-10','expiry':'2026-12-18','horizon_date':'2026-12-18',
        'underlying_prices':['80','100','120'],'volatility_multipliers':['1']}


def test_four_controls_have_same_capital_and_hand_calculated_expiry_cash_and_fees():
    result=compare(request());controls=result['controls']
    expected={'protective_put':[-704,-204,1796],'collar':[-606,-106,394],'stock':[-2002,-2,1998],'cash':[0,0,0]}
    for name,pnl in expected.items():
        assert controls[name]['initial_cash']=='20000'
        assert [float(p['pnl']) for p in controls[name]['points']]==pnl
        assert [float(p['equity']) for p in controls[name]['points']]==[20000+x for x in pnl]
    assert float(controls['protective_put']['uninvested_cash'])==9796
    assert float(controls['collar']['uninvested_cash'])==9894
    assert float(controls['collar']['net_option_premium'])==100
    assert float(controls['collar']['long_premium_budget_used'])==204
    assert all(p['greeks_complete'] for p in controls['stock']['points'])
    assert all(p['greeks']['delta']==100 and p['greeks']['gamma']==0 for p in controls['stock']['points'])
    assert all(not p['greeks_complete'] and all(value is None for value in p['greeks'].values()) for p in controls['collar']['points'])
    assert result['executable'] is False and result['maximum_loss']=='NOT_INFERRED_FROM_FINITE_GRID'


@pytest.mark.parametrize('changes,code',[({'initial_cash':'10150'},'SCENARIO_CAPITAL_INSUFFICIENT'),
    ({'maximum_premium_budget':'203'},'SCENARIO_PREMIUM_BUDGET'),({'packages':'1.5'},'INVALID_RISK_COMPARISON')])
def test_controls_do_not_borrow_reduce_size_or_treat_short_premium_as_budget(changes,code):
    with pytest.raises(QuantError) as caught:compare({**request(),**changes})
    assert caught.value.code==code


def test_long_call_short_put_parity_has_full_position_delta_and_cancelling_gamma_vega():
    legs=[{'kind':kind,'quantity':quantity,'entry_price':'2','strike':'100','multiplier':'100','expiry':'2026-12-18'}
        for kind,quantity in [('CALL','1'),('PUT','-1')]]
    model={'style':'EUROPEAN','volatility':'.2','rate':'.04','dividend_yield':'0'}
    result=evaluate({'legs':legs,'models':{'0':model,'1':model},'valuation_date':'2026-10-10',
        'horizon_date':'2026-11-10','underlying_prices':['100'],'volatility_multipliers':['1']})
    point=result['points'][0]
    assert point['greeks']['delta']==pytest.approx(100,abs=1e-8)
    assert point['greeks']['gamma']==pytest.approx(0,abs=1e-8)
    assert point['greeks']['vega_per_vol_point']==pytest.approx(0,abs=1e-7)
    assert point['greeks_complete'] and all(leg['greeks_complete'] and leg['model']['model_version'] for leg in point['leg_values'])
    assert '百分点' in result['greek_units']['vega_per_vol_point']


def test_expiry_still_validates_model_parameters_and_rejects_unknown_dividend_paths():
    base={'legs':[{'kind':'CALL','quantity':'1','entry_price':'2','strike':'100','multiplier':'100','expiry':'2026-12-18'}],
        'models':{'0':{'style':'EUROPEAN','volatility':'.2','rate':'.04','dividend_yield':'0'}},
        'valuation_date':'2026-10-10','horizon_date':'2026-12-18','underlying_prices':['100'],'volatility_multipliers':['1']}
    bad=copy.deepcopy(base);bad['models']['0']['volatility']=0
    with pytest.raises(QuantError):evaluate(bad)
    bad=copy.deepcopy(base);bad['models']['0']['discrete_dividends']=[]
    with pytest.raises(QuantError) as caught:evaluate(bad)
    assert caught.value.code=='UNSUPPORTED_STRESS_DIVIDENDS'
    with pytest.raises(QuantError):evaluate({**base,'underlying_prices':['100','100.0']})


def test_ui_comparison_and_invalid_resubmission_do_not_keep_previous_success():
    app=AppTest.from_string('from personal_quant.ui.risk_lab import controls\ncontrols()',default_timeout=30).run()
    app.date_input(key='v195-risk-value-date').set_value(date(2026,10,10))
    app.date_input(key='v195-risk-expiry').set_value(date(2026,12,18))
    app.date_input(key='v195-risk-horizon').set_value(date(2026,12,18))
    next(x for x in app.button if x.label=='比较同资本风险情景').click().run()
    assert not app.exception and not app.error and app.session_state['v195-risk-comparison']['data_type']=='scenario_only'
    app.number_input(key='v195-risk-cash').set_value(100)
    next(x for x in app.button if x.label=='比较同资本风险情景').click().run()
    assert app.error and 'v195-risk-comparison' not in app.session_state


def test_advanced_ui_clears_old_result_after_invalid_json():
    app=AppTest.from_string('from personal_quant.ui.risk_lab import controls\ncontrols()',default_timeout=30).run()
    app.text_area(key='v195-stress-legs').set_value('[{"kind":"STOCK","quantity":"100","entry_price":"100"}]')
    next(x for x in app.button if x.label=='计算组合风险图').click().run()
    assert not app.exception and 'v195-stress-result' in app.session_state
    app.text_area(key='v195-stress-legs').set_value('{invalid')
    next(x for x in app.button if x.label=='计算组合风险图').click().run()
    assert app.error and 'v195-stress-result' not in app.session_state


def test_submitted_model_inputs_and_results_stay_paired_after_page_absence():
    app=AppTest.from_string('''import streamlit as st
page=st.sidebar.radio('页面',['风险','其他'])
if page=='风险':
    from personal_quant.ui.risk_lab import controls
    controls()
''',default_timeout=30).run()
    app.number_input(key='v195-risk-put-price').set_value(3.25)
    app.date_input(key='v195-risk-value-date').set_value(date(2026,10,10))
    app.date_input(key='v195-risk-expiry').set_value(date(2026,12,18))
    app.date_input(key='v195-risk-horizon').set_value(date(2026,12,18))
    next(x for x in app.button if x.label=='比较同资本风险情景').click().run()
    identity=app.session_state['v195-risk-comparison']['request_hash']
    app.sidebar.radio[0].set_value('其他').run();app.sidebar.radio[0].set_value('风险').run()
    assert not app.exception and app.number_input(key='v195-risk-put-price').value==3.25
    assert app.session_state['v195-risk-comparison']['request_hash']==identity
    assert app.session_state['v195-risk-comparison']['request']['put_premium']==3.25


def test_schema_boolean_does_not_mean_version_one():
    with pytest.raises(QuantError) as caught:compare({**request(),'schema_version':True})
    assert caught.value.code=='INVALID_RISK_COMPARISON'


def test_ui_model_drift_invalidates_cache_without_automatic_repricing(monkeypatch):
    from personal_quant.ui import risk_lab
    app=AppTest.from_string('from personal_quant.ui.risk_lab import controls\ncontrols()',default_timeout=30).run()
    app.text_area(key='v195-stress-legs').set_value('[{"kind":"STOCK","quantity":"100","entry_price":"100"}]')
    next(x for x in app.button if x.label=='计算组合风险图').click().run()
    assert 'v195-stress-result' in app.session_state
    changed={**app.session_state['v195-stress-result']['model_identity'],'QuantLib':'different-version'}
    monkeypatch.setattr(risk_lab,'model_identity',lambda:changed)
    def forbidden(*args,**kwargs):raise AssertionError('rerender must not calculate models')
    monkeypatch.setattr(risk_lab,'evaluate',forbidden)
    app.run()
    assert not app.exception and 'v195-stress-result' not in app.session_state
    assert any('模型/依赖' in warning.value for warning in app.warning)


def test_nonrepresentable_amounts_cannot_be_exported_as_infinite_chart_or_greeks():
    with pytest.raises(QuantError):compare({**request(),'initial_cash':'1e9999'})
    with pytest.raises(QuantError):evaluate({'legs':[{'kind':'STOCK','quantity':'1e9999','entry_price':'100'}],
        'models':{},'valuation_date':'2026-10-10','horizon_date':'2026-10-11',
        'underlying_prices':['100'],'volatility_multipliers':['1']})


def test_public_cli_risk_controls_is_model_only_and_does_not_create_account(tmp_path,monkeypatch,capsys):
    import json
    from pathlib import Path
    from personal_quant.cli import main
    root=Path(__file__).resolve().parents[1];monkeypatch.chdir(tmp_path)
    assert main(['--config',str(root/'configs/demo.toml'),'options','--action','risk-compare',
        '--file',str(root/'configs/v195-risk-scenario.json')])==0
    result=json.loads(capsys.readouterr().out)
    assert result['data_type']=='scenario_only' and result['executable'] is False
    assert float(result['controls']['collar']['points'][0]['pnl'])==-606
    assert not (tmp_path/'runtime/demo/account.sqlite').exists()


def test_mutating_callers_input_cannot_change_published_assumptions():
    body=request();result=compare(body);identity=result['request_hash']
    body['underlying_prices'][0]='1';body['initial_cash']='1'
    assert result['request']['underlying_prices'][0]=='80' and result['request']['initial_cash']=='20000'
    assert result['request_hash']==identity
