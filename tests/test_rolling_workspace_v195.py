from native_tools import native_engine_root,native_dotnet
import json,sqlite3
from test_options_monthly_replay_v19 import monthly_signals,ROOT
from test_options_monthly_natural_v19 import natural_path
from personal_quant.common import write_json
from personal_quant.config import Config
from personal_quant.workspace.service import create,worker


def test_rolling_workspace_retains_stock_and_resumes_to_settled_cash_once(tmp_path):
    signals=monthly_signals(tmp_path/'signals','collar');path=natural_path(signals,100)
    path={**path,'stocks':{s:{d:p for d,p in values.items() if d<='2025-01-10'} for s,values in path['stocks'].items()},
          'options':{s:{d:p for d,p in values.items() if d<='2025-01-10'} for s,values in path['options'].items()}}
    request={'signals':signals,'packages':[1,1],'stock_basket':{},'execution_path':path,
             'retain_stock':True,'rolling_end_session':'2025-01-10'}
    file=tmp_path/'request.json';write_json(file,request);root=tmp_path/'workspace'
    create(root,{'schema_version':1,'account_id':'demo-account','initial_cash':'100000','kind':'options'},Config.load(ROOT/'configs/demo.toml'))
    started=worker(root,'start',input_file=file,engine_root=native_engine_root(),dotnet=native_dotnet(),fee_per_contract=2)
    first=worker(root,'step',started['run_id'],'2024-11-04')
    waiting=worker(root,'resume',started['run_id'],'2024-12-02')
    assert first['status']==waiting['status']=='PAUSED' and float(waiting['details']['equity'])==99970
    closed=worker(root,'resume',started['run_id'],'2025-01-10')
    done=worker(root,'resume',started['run_id'],'2025-01-13')
    assert done['status']=='COMPLETED' and float(done['details']['equity'])==99940
    repeat=worker(root,'resume',started['run_id'],'2025-01-13')
    assert repeat['events']==done['events']==11 and repeat['repeated']
    con=sqlite3.connect((root/'runtime/demo/account.sqlite').as_uri()+'?mode=ro',uri=True)
    stocks=[json.loads(row[0]) for row in con.execute("SELECT payload FROM events WHERE json_extract(payload,'$.kind') IN ('BUY','SELL') ORDER BY seq")]
    con.close()
    assert len(stocks)==2 and [float(e['quantity']) for e in stocks]==[100,100]
