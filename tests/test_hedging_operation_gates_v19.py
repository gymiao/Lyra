from copy import deepcopy
import pytest
from personal_quant.common import QuantError,decimal as D
from personal_quant.hedging.stage_assessment import require_operation_risk
from personal_quant.hedging.stage_stress import evaluate
from test_hedging_stage_stress_v19 import inputs
from test_hedging_option_sizing_v19 import selected


def test_incomplete_beta_downgrades_close_only_and_direct_prices_are_explicit(selected):
    args=list(inputs(selected,'protective_put',quantity=1));risk=args[0];symbol=args[1]['lines'][0]['symbol']
    risk.update(status='INCOMPLETE',checks=['ZERO_BENCHMARK_VARIANCE','OPTION_DELTA_REQUIRED:'+symbol])
    risk['valuation']['status']='COMPLETE';risk['option_valuation']={'status':'COMPLETE'}
    risk['account']['option_positions']={symbol:'1'};risk['beta_model']['estimates']={}
    args[1].update(action='CLOSE');args[1]['lines'][0]['side']='SELL'
    args[2]={str((symbol,args[1]['lines'][0]['contract_version'],'SELL')):'1'}
    with pytest.raises(QuantError) as exc:require_operation_risk(risk,'OPEN')
    assert exc.value.code=='INCOMPLETE_HEDGE_EXPOSURE'
    require_operation_risk(risk,'CLOSE')
    with pytest.raises(QuantError) as exc:evaluate(*args)
    assert exc.value.code=='MODEL_INPUT_REQUIRED'
    for scenario in args[-1]['scenarios']:
        scenario['benchmark_return']=0;scenario['residual_returns']={'SPY':-.2}
    out=evaluate(*args)
    assert out['status']=='CHECKED' and len(out['vertices'])==2
    assert D(out['vertices'][0]['scenarios'][0]['prices']['SPY'])==80
    assert risk['beta_model']['estimates']=={} and risk['status']=='INCOMPLETE'


@pytest.mark.parametrize('mutation', ['raw_price','equity','account_anomaly','unknown_check','option_mark'])
def test_close_never_bypasses_valuation_or_account_facts(selected,mutation):
    risk=deepcopy(inputs(selected)[0]);risk.update(status='INCOMPLETE',checks=['ZERO_BENCHMARK_VARIANCE'])
    risk['valuation']['status']='COMPLETE';risk['option_valuation']={'status':'COMPLETE'}
    if mutation=='raw_price':risk['valuation']['status']='INCOMPLETE'
    elif mutation=='equity':risk['account']['equity']=None
    elif mutation=='account_anomaly':risk['account']['anomalies']=['unresolved']
    elif mutation=='unknown_check':risk['checks'].append('RISK_CALENDAR_CONFLICT')
    else:risk['account']['option_positions']={'put':'1'};risk['option_valuation']=None
    with pytest.raises(QuantError) as exc:require_operation_risk(risk,'CLOSE')
    assert exc.value.code=='INCOMPLETE_HEDGE_EXPOSURE'
