from pathlib import Path
import sys
import json
from streamlit.testing.v1 import AppTest
from personal_quant.config import Config
from personal_quant.workspace.service import create,status
ROOT=Path(__file__).resolve().parents[1]


def test_v20_four_pages_budget_preview_and_workspace_context_are_readonly(tmp_path,monkeypatch):
    root=tmp_path/'options';create(root,{'schema_version':1,'kind':'options','account_id':'demo-account','initial_cash':'100000'},Config.load(ROOT/'configs/demo.toml'))
    monkeypatch.chdir(root);monkeypatch.setattr(sys,'argv',['app','--config',str(root/'config.json')])
    app=AppTest.from_file(str(ROOT/'src/personal_quant/ui/app.py'),default_timeout=40).run()
    for page in ['策略研究','调仓计划','运行状态','账户总览']:
        app.sidebar.radio[0].set_value(page).run();assert not app.exception
        if page=='调仓计划':
            app.button(key='v20-capital-submit').click().run();assert not app.exception
            result=app.session_state['v20-capital-result'][1]
            assert result['status']=='PREVIEW_ONLY' and result['financial_events_added']==0
        if page=='运行状态':
            assert app.text_input(key='v20-input-package') is not None
            assert app.button(key='v20-maintenance-submit') is not None
        if page=='策略研究':assert app.button(key='v20-research-run') is not None
    assert status(root)['events']==1 and not status(root)['runs']
