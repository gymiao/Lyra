from native_tools import native_engine_root,native_dotnet
from pathlib import Path
import pytest
from test_options_monthly_replay_v19 import monthly_signals,ROOT
from test_options_monthly_natural_v19 import natural_path
from personal_quant.common import write_json,QuantError
from personal_quant.config import Config
from personal_quant.workspace.service import create,worker,status


@pytest.mark.parametrize('name,spot,equity,settlement',[('long_straddle',100,99748,False),('long_call',110,100871.8,True)])
def test_public_option_workspace_expiry_delivery_settlement_and_repeat(tmp_path,name,spot,equity,settlement):
    signals=monthly_signals(tmp_path/'signals',name)
    request={'signals':signals,'packages':[1,1],'stock_basket':{},'execution_path':natural_path(signals,spot),
             'final_lifecycle':'natural_expiry_with_delivery_exit'}
    request_file=tmp_path/'request.json';write_json(request_file,request)
    root=tmp_path/'workspace'
    made=create(root,{'schema_version':1,'account_id':'demo-account','initial_cash':'100000','kind':'options'},Config.load(ROOT/'configs/demo.toml'))
    assert made['identity']['price_snapshot_id'] is None
    assert not (root/'runtime/demo/data/latest.json').exists()
    started=worker(root,'start',input_file=request_file,engine_root=native_engine_root(),dotnet=native_dotnet(),fee_per_contract=2)
    first=worker(root,'step',started['run_id'],'2024-11-04')
    assert first['status']=='PAUSED'
    expired=worker(root,'resume',started['run_id'],'2025-01-17')
    assert expired['details']['as_of']=='2025-01-18T05:00:00+00:00'
    assert expired['details']['lifecycle_receipts']
    again=worker(root,'resume',started['run_id'],'2025-01-17')
    assert again['events']==expired['events'] and again['repeated']
    recovered=worker(root,'resume',started['run_id'],'2025-01-21')
    done=worker(root,'resume',started['run_id'],'2025-01-22') if settlement else recovered
    assert done['status']=='COMPLETED' and float(done['details']['equity'])==pytest.approx(equity)
    repeat=worker(root,'resume',started['run_id'],done['through_session'])
    assert repeat['events']==done['events'] and repeat['status']=='COMPLETED'
    # Changing fees must create an independent experiment rather than another
    # run spending this account's funds.
    with pytest.raises(QuantError) as caught:
        worker(root,'start',input_file=request_file,engine_root=native_engine_root(),dotnet=native_dotnet(),fee_per_contract=3)
    assert '只接受一份冻结运行' in str(caught.value)
    assert status(root)['events']==done['events']
