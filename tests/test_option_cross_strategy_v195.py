from native_tools import native_engine_root,native_dotnet
"""Two actual LEAN strategies use one full chain universe and price world."""
import os
from pathlib import Path
import pytest
from personal_quant.common import write_json
from personal_quant.config import Config
from personal_quant.workspace.service import create,worker
from personal_quant.workspace.experiments import compare
from test_stock_preparation_v195 import prepared_inputs

ROOT=Path(__file__).resolve().parents[1]


def test_protective_put_and_collar_compare_same_data_capital_cost_and_stock_exposure(tmp_path):
    put,put_path=prepared_inputs(tmp_path/'put-input','protective_put')
    collar,collar_path=prepared_inputs(tmp_path/'collar-input','collar')
    assert [s['input']['snapshot_id'] for s in put]==[s['input']['snapshot_id'] for s in collar]
    assert put_path['stocks']==collar_path['stocks']
    for identity in set(put_path['options'])&set(collar_path['options']):assert put_path['options'][identity]==collar_path['options'][identity]
    # Share all input quotes. The worker passes only known selected contracts
    # to LEAN, so unused or future contracts do not become available signals.
    world={**put_path,'options':{**put_path['options'],**collar_path['options']}}
    engine=Path(os.environ.get('LYRAX_TEST_ENGINE_ROOT',str(native_engine_root())))
    dotnet=Path(os.environ.get('LYRAX_TEST_DOTNET',str(native_dotnet())))
    request=[]
    for template,signals,equity in [('protective_put',put,100068.02),('collar',collar,100040.02)]:
        root=tmp_path/template;file=tmp_path/(template+'.json')
        write_json(file,{'signals':signals,'packages':[1,1],'stock_basket':{},'execution_path':world,
            'prepare_stock':True,'retain_stock':True,'rolling_end_session':'2025-01-13'})
        create(root,{'schema_version':1,'kind':'options','account_id':'demo-account','initial_cash':'100000'},Config.load(ROOT/'configs/demo.toml'))
        start=worker(root,'start',input_file=file,engine_root=engine,dotnet=dotnet,fee_per_contract=2)
        worker(root,'resume',start['run_id'],'2025-01-13');done=worker(root,'resume',start['run_id'],'2025-01-14')
        assert done['status']=='COMPLETED' and float(done['details']['equity'])==equity
        request.append({'name':template,'workspace':str(root),'run_id':start['run_id']})
    result=compare(request)
    assert result['execution']['protective_put']['net_trading_pnl']==pytest.approx(68.02)
    assert result['execution']['collar']['net_trading_pnl']==pytest.approx(40.02)
    assert result['policy']['engine']=='LEAN' and result['policy']['stock_commission_bps']==2
