from native_tools import native_engine_root,native_dotnet
from test_wheel_native_v195 import wheel_inputs,ROOT
from personal_quant.common import write_json
from personal_quant.config import Config
from personal_quant.workspace.service import create,worker


def test_wheel_workspace_prefix_assignment_call_and_settlement_repeats_without_stock_orders(tmp_path):
    signals,path=wheel_inputs(tmp_path/'signals',True)
    file=tmp_path/'request.json';write_json(file,{'signals':signals,'packages':[1,1],'stock_basket':{},'execution_path':path,
        'wheel':True,'wheel_end_session':'2024-12-19'})
    root=tmp_path/'workspace';create(root,{'schema_version':1,'account_id':'demo-account','initial_cash':'100000','kind':'options'},Config.load(ROOT/'configs/demo.toml'))
    start=worker(root,'start',input_file=file,engine_root=native_engine_root(),dotnet=native_dotnet(),fee_per_contract=2)
    first=worker(root,'step',start['run_id'],'2024-11-04')
    stock=worker(root,'resume',start['run_id'],'2024-11-25')
    assert float(stock['details']['equity'])==99598 and stock['events']==3
    repeat=worker(root,'resume',start['run_id'],'2024-11-25')
    assert repeat['events']==3 and repeat['repeated']
    recovered=worker(root,'resume',start['run_id'],'2024-12-19')
    assert recovered['status']=='PAUSED' and float(recovered['details']['equity'])==101196
    final=worker(root,'resume',start['run_id'],'2024-12-20')
    assert final['status']=='COMPLETED' and float(final['details']['equity'])==101196
    assert final['events']==5
    again=worker(root,'resume',start['run_id'],'2024-12-20')
    assert again['events']==5 and again['status']=='COMPLETED'
