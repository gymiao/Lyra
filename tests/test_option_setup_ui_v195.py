from pathlib import Path
import sys
import time
from streamlit.testing.v1 import AppTest
from personal_quant.config import Config
from personal_quant.portfolio import Ledger
from personal_quant.workspace.service import create
from personal_quant.workspace.jobs import list_jobs

ROOT=Path(__file__).resolve().parents[1]


def test_chinese_form_background_prepare_use_and_refresh_do_not_trade(tmp_path,monkeypatch):
    root=tmp_path/'workspace'
    create(root,{'schema_version':1,'kind':'options','account_id':'demo-account','initial_cash':'100000'},Config.load(ROOT/'configs/demo.toml'))
    monkeypatch.chdir(root);monkeypatch.setattr(sys,'argv',['app','--config',str(root/'config.json')])
    app=AppTest.from_file(str(ROOT/'src/personal_quant/ui/app.py'),default_timeout=30).run()
    assert not app.exception
    next(x for x in app.button if x.label=='后台冻结合成配置').click().run()
    assert not app.exception
    deadline=time.monotonic()+60
    while time.monotonic()<deadline:
        jobs=list_jobs(root)
        if jobs and jobs[-1]['status']!='RUNNING':break
        time.sleep(.1)
    assert jobs[-1]['status']=='SUCCESS',jobs
    app.run();assert not app.exception
    app.button(key='v195-setup-use').click().run()
    assert not app.exception and app.text_input(key='v195-option-file').value.endswith('/request.json')
    assert app.number_input(key='v195-option-fee').value==2
    app.run();app.sidebar.radio[0].set_value('运行状态').run()
    assert not app.exception and len(list_jobs(root))==1
    book=Ledger.read_only(root/'runtime/demo/account.sqlite','demo')
    assert book.sequence('demo-account')==1
    assert book.connection.execute("SELECT count(*) FROM sqlite_master WHERE name='simulation_runs'").fetchone()[0]==0
    book.close()
