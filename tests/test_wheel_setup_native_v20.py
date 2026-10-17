from pathlib import Path
import json
from native_tools import native_engine_root,native_dotnet
from personal_quant.common import write_json
from personal_quant.config import Config
from personal_quant.workspace.service import create,worker
from personal_quant.workspace.scenarios import generate
from personal_quant.workspace.option_setup import prepare
ROOT=Path(__file__).resolve().parents[1]


def test_generic_wheel_chooses_from_actual_prior_prefix_and_repeats(tmp_path):
    scenario=json.loads((ROOT/'configs/v20-scenario.json').read_text())
    scenario['daily_volatility']=0
    scenario['price_nodes']['SPY']={'2024-08-21':90,'2024-08-30':100,'2024-09-20':120,'2024-09-30':100}
    package=tmp_path/'inputs';generate(scenario,package)
    cfg=Config.load(ROOT/'configs/demo.toml').content();cfg['evaluation_end']='2024-10-31'
    write_json(tmp_path/'config.json',cfg)
    root=tmp_path/'wheel';create(root,{'schema_version':1,'kind':'options','account_id':'demo-account','initial_cash':'100000','input_bundle':str(package)},Config.load(tmp_path/'config.json'))
    spec=json.loads((ROOT/'configs/v195-option-setup.json').read_text());spec.update(template_id='wheel',input_bundle=str(package),
        engine_root=str(native_engine_root()),dotnet=str(native_dotnet()),cash_buffer=10)
    spec['selection_parameters'].update(minimum_dte=14,target_dte=21,maximum_dte=35,exit_days_before_expiry=0)
    result=prepare(root,spec);request=json.loads(Path(result['request_file']).read_text())
    assert [s['selection']['template_id'] for s in request['signals']]==['cash_secured_put','covered_call','cash_secured_put']
    assert request['wheel'] and len(request['signals'])==3
    assert prepare(root,spec)['setup_id']==result['setup_id']
    start=worker(root,'start',input_file=result['request_file'],engine_root=native_engine_root(),dotnet=native_dotnet(),fee_per_contract=2)
    final=worker(root,'resume',start['run_id'],request['wheel_end_session'])
    assert final['status'] in {'PAUSED','COMPLETED'}
    repeat=worker(root,'resume',start['run_id'],request['wheel_end_session'])
    assert repeat['events']==final['events'] and repeat['details']['equity']==final['details']['equity']
