from datetime import date
from streamlit.testing.v1 import AppTest


def test_risk_grid_uses_existing_expiry_payoff_units_and_no_finite_max_claim():
    app=AppTest.from_string('from personal_quant.ui.risk_lab import controls\ncontrols()',default_timeout=30).run()
    for control in app.text_area:
        if control.label=='标准组合腿 JSON':control.set_value('[{"kind":"CALL","quantity":"1","entry_price":"2","strike":"100","multiplier":"100","expiry":"2026-12-18","fee":"0"}]')
        elif control.label=='每条期权腿的模型 JSON':control.set_value('{"0":{"style":"EUROPEAN","volatility":"0.2","rate":"0.04","dividend_yield":"0"}}')
    for control in app.date_input:
        control.set_value(date(2026,10,10) if control.label=='组合模型估值日' else date(2026,12,18))
    next(b for b in app.button if b.label=='计算组合风险图').click().run()
    assert not app.exception and not app.error
    result=app.session_state['v195-stress-result']
    assert float(next(p['pnl'] for p in result['points'] if p['underlying_price']=='120' and p['volatility_multiplier']=='1'))==1800
    assert result['maximum_loss']=='NOT_INFERRED_FROM_FINITE_GRID'
    assert all(not p['greeks_complete'] for p in result['points'])
