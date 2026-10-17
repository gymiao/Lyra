from native_tools import native_engine_root,native_dotnet
from pathlib import Path
from personal_quant.config import Config
from personal_quant.workspace.service import create,worker

ROOT=Path(__file__).resolve().parents[1]


def test_option_workspace_imports_native_prefix_once_and_preserves_initial_funding(tmp_path):
    directory=tmp_path/'option-workspace'
    create(directory,{'schema_version':1,'account_id':'demo-account','initial_cash':'100000','kind':'options'},Config.load(ROOT/'configs/demo.toml'))
    started=worker(directory,'start',input_file=ROOT/'examples/options/monthly-variable-path.json',
        engine_root=native_engine_root(),dotnet=native_dotnet(),fee_per_contract=2)
    first=worker(directory,'step',started['run_id'],'2024-11-04')
    assert first['events']==4
    assert float(first['details']['equity'])==99994.5
    again=worker(directory,'step',started['run_id'],'2024-11-04')
    assert again['events']==4 and again['repeated'] is True
    closed=worker(directory,'resume',started['run_id'],'2025-01-10')
    assert closed['events']==13
    settled=worker(directory,'resume',started['run_id'],'2025-01-13')
    assert settled['status']=='COMPLETED' and settled['events']==13
    assert settled['details']['equity']==closed['details']['equity']
    repeated=worker(directory,'resume',started['run_id'],'2025-01-13')
    assert repeated['status']=='COMPLETED' and repeated['events']==13 and repeated['repeated']
    import sqlite3,json
    con=sqlite3.connect((directory/'runtime/demo/account.sqlite').as_uri()+'?mode=ro',uri=True)
    checkpoints=con.execute('SELECT session,details FROM simulation_checkpoints ORDER BY session').fetchall();con.close()
    input_path=json.loads((ROOT/'examples/options/monthly-variable-path.json').read_text())['execution_path']['stocks']['SPY']
    assert {row[0] for row in checkpoints}==set(input_path)|{'2025-01-13'}
    assert all(json.loads(row[1]).get('report_id') for row in checkpoints)
