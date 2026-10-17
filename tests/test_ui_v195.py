from pathlib import Path
import shutil
from streamlit.testing.v1 import AppTest
from personal_quant.portfolio import Ledger
from personal_quant.portfolio.imports import event_csv
from personal_quant.portfolio.report import account_report

ROOT=Path(__file__).resolve().parents[1]
CLOCK='2024-12-31T21:30:00Z'


def app_in(tmp_path,monkeypatch):
    (tmp_path/'configs').mkdir()
    shutil.copy2(ROOT/'configs/demo.toml',tmp_path/'configs/demo.toml')
    monkeypatch.chdir(tmp_path)
    return AppTest.from_file(str(ROOT/'src/personal_quant/ui/app.py'),default_timeout=30)


def deposit(amount,identity):
    row=event_csv((ROOT/'examples/test_statement.csv').read_bytes())[0]
    return {**row,'account_id':'demo-account','event_id':identity,'amount':str(amount)}


def test_account_page_flags_report_after_late_deposit(tmp_path,monkeypatch):
    app=app_in(tmp_path,monkeypatch)
    book=Ledger(Path('runtime/demo/account.sqlite'),'demo');book.account('demo-account')
    book.import_events('demo-account',[deposit(100,'first')])
    account_report(book,'demo-account',CLOCK,{},Path('runtime/demo/reports/account-latest'))
    book.import_events('demo-account',[deposit(50,'second')]);book.close()
    app.run()
    assert not app.exception
    assert any('账本已变化' in x.value for x in app.warning)
    next(x for x in app.button if x.label=='更新账户报告').click().run()
    assert not app.exception
    assert {x.label:x.value for x in app.metric}['总资产']=='150'
    assert {x.label:x.value for x in app.metric}['投资盈亏']=='0'


def test_navigation_keeps_account_and_historical_view_clock(tmp_path,monkeypatch):
    app=app_in(tmp_path,monkeypatch).run()
    next(x for x in app.text_input if x.label=='账户 ID').set_value('selected-account')
    app.sidebar.text_input[0].set_value('2025-01-13T21:30:00Z');app.run()
    for page in ['策略研究','调仓计划','运行状态','账户总览']:
        app.sidebar.radio[0].set_value(page).run()
        assert not app.exception
    assert next(x.value for x in app.text_input if x.label=='账户 ID')=='selected-account'
    assert app.sidebar.text_input[0].value=='2025-01-13T21:30:00Z'


def test_option_workspace_has_four_pages_without_etf_binding_and_shows_calendar(tmp_path,monkeypatch):
    from personal_quant.config import Config
    from personal_quant.workspace.service import create
    import sys
    directory=tmp_path/'options'
    create(directory,{'schema_version':1,'account_id':'demo-account','initial_cash':'100000','kind':'options'},Config.load(ROOT/'configs/demo.toml'))
    monkeypatch.chdir(directory)
    monkeypatch.setattr(sys,'argv',['app','--config',str(directory/'config.json')])
    app=AppTest.from_file(str(ROOT/'src/personal_quant/ui/app.py'),default_timeout=30).run()
    assert not app.exception
    assert {x.label:x.value for x in app.metric}['总资产']=='100000'
    for page in ['策略研究','调仓计划','运行状态','账户总览']:
        app.sidebar.radio[0].set_value(page).run()
        assert not app.exception
        if page in {'调仓计划','运行状态'}:assert any(x.value=='期权生命周期日历' for x in app.subheader)
        if page=='运行状态':
            diagnostics=[x.value for x in app.dataframe if {'kind','id','status'}<=set(x.value.columns)]
            assert diagnostics
            rows=diagnostics[0]
            assert set(rows.loc[rows.kind=='data','status'])=={'NOT_REQUIRED'}
            next(x for x in app.button if x.label=='准备脱敏诊断').click().run()
            assert not app.exception
            assert app.session_state['v195-diagnostic-data']['event_count']==1
    assert any('未绑定ETF行情' in x.value for x in app.info)
