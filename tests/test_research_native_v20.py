import json
from pathlib import Path
from copy import deepcopy
from native_tools import native_engine_root,native_dotnet
from test_research_protocol_v20 import specification
from personal_quant.workspace.scenarios import generate
from personal_quant.workspace.research_protocol import freeze,run
from personal_quant.common import QuantError
import pytest
ROOT=Path(__file__).resolve().parents[1]


def test_native_predeclared_development_assessment_and_fee_pressure(tmp_path):
    scenario=json.loads((ROOT/'configs/v20-scenario.json').read_text())
    scenario.update(start='2024-01-02',end='2024-08-30',iv_nodes={'2024-01-02':.25},daily_volatility=0)
    scenario['price_nodes']={s:{} for s in scenario['initial_prices']}
    package=tmp_path/'input';generate(scenario,package)
    spec=specification();spec['input_bundle']=str(package)
    parameters=json.loads((ROOT/'configs/v195-option-setup.json').read_text())['selection_parameters']
    parameters.update(minimum_dte=14,target_dte=21,maximum_dte=35,exit_days_before_expiry=3)
    spec['selection_parameters']={'long_call':parameters}
    spec['costs'].append({'name':'fees-stress','fee_per_contract':4,'stock_commission_bps':2,'spread_multiplier':1})
    root=tmp_path/'study';freeze(root,spec)
    changed=deepcopy(spec);changed['question']='结果看过后换问题'
    with pytest.raises(QuantError):freeze(root,changed)
    result=run(root,native_engine_root(),native_dotnet())
    assert result['status']=='PASSED',result
    assert len(result['experiments'])==4
    for base,stress in [(result['experiments'][0],result['experiments'][1]),(result['experiments'][2],result['experiments'][3])]:
        assert base['metrics']['long_call']['commission']*2==stress['metrics']['long_call']['commission']
        assert base['metrics']['cash']['total_return']==stress['metrics']['cash']['total_return']==0
        assert stress['metrics']['long_call']['total_return']<base['metrics']['long_call']['total_return']
    assert run(root,native_engine_root(),native_dotnet())['experiments']==result['experiments']
