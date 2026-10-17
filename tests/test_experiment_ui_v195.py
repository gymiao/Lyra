import json
from pathlib import Path
import sys
from streamlit.testing.v1 import AppTest
from personal_quant.config import Config
from personal_quant.portfolio import Ledger
from personal_quant.workspace.service import create
from personal_quant.workspace.worker import SCHEMA

ROOT=Path(__file__).resolve().parents[1]


def app(tmp_path,monkeypatch,kind):
    root=tmp_path/'workspace'
    create(root,{'schema_version':1,'kind':kind,'account_id':'demo-account','initial_cash':'100000'},Config.load(ROOT/'configs/demo.toml'))
    monkeypatch.chdir(root);monkeypatch.setattr(sys,'argv',['app','--config',str(root/'config.json')])
    return root,AppTest.from_file(str(ROOT/'src/personal_quant/ui/app.py'),default_timeout=30)


def test_index_form_is_read_only_and_keeps_explicit_workspace_result(tmp_path,monkeypatch):
    root,ui=app(tmp_path,monkeypatch,'etf');ui.run();ui.sidebar.radio[0].set_value('策略研究').run()
    ui.text_area(key='v195-index-paths').set_value(str(root))
    next(x for x in ui.button if x.label=='读取实验目录').click().run()
    assert not ui.exception
    result=ui.session_state['v195-experiment-index-result']
    assert result['read_only'] and len(result['experiments'])==1
    assert result['experiments'][0]['status']=='NOT_STARTED'
    ui.sidebar.radio[0].set_value('账户总览').run();ui.sidebar.radio[0].set_value('策略研究').run()
    assert not ui.exception and ui.text_area(key='v195-index-paths').value==str(root)
    book=Ledger(root/'runtime/demo/account.sqlite','demo');assert book.sequence('demo-account')==1;book.close()


def test_explicit_tool_relocation_reaches_background_job_from_ui(tmp_path,monkeypatch):
    root,ui=app(tmp_path,monkeypatch,'options')
    book=Ledger(root/'runtime/demo/account.sqlite','demo');book.connection.executescript(SCHEMA)
    book.connection.execute('INSERT INTO simulation_runs VALUES(?,?,?,?,?,?)',('a'*64,'PAUSED',None,'ui-wire-fixture','2026-10-15T00:00:00Z','{}'));book.close()
    from personal_quant.workspace import jobs
    # The UI wrapper resolves jobs.launch at submission time; importing it
    # while a spy is installed must not retain that spy for later tests.
    from personal_quant.ui import option_setup
    from personal_quant.ui.v20_workbench import launch_simulation
    assert option_setup.launch is launch_simulation
    calls=[]
    def launch(*args,**kwargs):calls.append((args,kwargs));return {'job_id':'wire-only-job'}
    monkeypatch.setattr(jobs,'launch',launch)
    ui.run();ui.sidebar.radio[0].set_value('运行状态').run()
    ui.text_input(key='v195-engine').set_value('/tmp/copied LEAN')
    ui.text_input(key='v195-dotnet').set_value('/tmp/copied SDK/dotnet')
    ui.checkbox(key='v195-relocate-tools').check().run()
    ui.number_input(key='v195-batch-days').set_value(7)
    ui.number_input(key='v195-batch-time').set_value(120.)
    ui.number_input(key='v195-batch-disk').set_value(16).run()
    ui.button(key='v195-resume').click().run()
    assert not ui.exception and len(calls)==1
    assert calls[0][0][1:]==('batch','a'*64,'2024-12-31')
    assert isinstance(calls[0][1]['request_id'],str) and calls[0][1]['request_id']
    assert {k:v for k,v in calls[0][1].items() if k!='request_id'}=={'engine_root':'/tmp/copied LEAN','dotnet':'/tmp/copied SDK/dotnet',
                         'max_sessions':7,'max_seconds':120.,'min_free_bytes':16*1024**2}
    book=Ledger(root/'runtime/demo/account.sqlite','demo');assert book.sequence('demo-account')==1;book.close()


def test_completed_cash_experiments_compare_from_chinese_ui_without_new_facts(tmp_path,monkeypatch):
    from dataclasses import replace
    from personal_quant.workspace.service import worker
    config=replace(Config.load(ROOT/'configs/demo.toml'),evaluation_end='2024-07-03')
    roots=[]
    for name in ['baseline','candidate']:
        root=tmp_path/name
        create(root,{'schema_version':1,'kind':'etf','account_id':'demo-account','initial_cash':'100000'},config)
        started=worker(root,'start');assert worker(root,'resume',started['run_id'],'2024-07-03')['status']=='COMPLETED'
        roots.append(root)
    monkeypatch.chdir(roots[0]);monkeypatch.setattr(sys,'argv',['app','--config',str(roots[0]/'config.json')])
    ui=AppTest.from_file(str(ROOT/'src/personal_quant/ui/app.py'),default_timeout=30).run()
    ui.sidebar.radio[0].set_value('策略研究').run()
    ui.text_area(key='v195-index-paths').set_value('\n'.join(map(str,roots)))
    next(x for x in ui.button if x.label=='读取实验目录').click().run()
    choices=ui.multiselect(key='v195-compare-selected').options
    ui.multiselect(key='v195-compare-selected').set_value(choices)
    next(x for x in ui.button if x.label=='比较已完成实验').click().run()
    assert not ui.exception
    import time
    path=Path(ui.session_state['v20-comparison-file']);deadline=time.monotonic()+90
    while not path.is_file() and time.monotonic()<deadline:time.sleep(.1)
    assert path.is_file(),'后台比较未发布回执'
    ui.run();assert not ui.exception
    result=ui.session_state['v195-experiment-comparison']
    assert all(value['total_return']==0 for value in result['metrics'].values())
    for root in roots:
        book=Ledger.read_only(root/'runtime/demo/account.sqlite','demo');assert book.sequence('demo-account')==1;book.close()
