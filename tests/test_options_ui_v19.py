from test_ui import setup_ui,button
from pathlib import Path
from personal_quant.portfolio import Ledger


def test_scenario_and_quantlib_forms_compute_without_events_and_refresh_is_read_only(tmp_path,monkeypatch):
    app=setup_ui(tmp_path,monkeypatch).run()
    app.sidebar.radio[0].set_value('策略研究').run()
    assert not app.exception
    next(select for select in app.selectbox if select.label=='首批情景模板').set_value('protective_put')
    button(app,'计算到期情景').click().run()
    assert not app.exception and not app.error
    assert any('700' in str(item.value) for item in app.markdown)
    button(app,'计算理论价格与敏感度').click().run()
    assert not app.exception and not app.error
    app.run()
    book=Ledger(Path('runtime/demo/account.sqlite'),'demo')
    assert book.connection.execute('SELECT count(*) FROM events').fetchone()[0]==0
    assert book.connection.execute('SELECT count(*) FROM plans').fetchone()[0]==0
    book.close()


def test_v19_migration_and_all_pages_keep_empty_account_facts(tmp_path,monkeypatch):
    app=setup_ui(tmp_path,monkeypatch).run()
    button(app,'建立空账户').click().run()
    button(app,'备份并启用 v1.9').click().run()
    assert not app.exception and not app.error
    for page in ['账户总览','策略研究','调仓计划','运行状态']:
        app.sidebar.radio[0].set_value(page).run()
        assert not app.exception and not app.error,page
        assert any('只读摘要' in str(item.value) for item in app.caption)
    book=Ledger(Path('runtime/demo/account.sqlite'),'demo')
    assert book.connection.execute('SELECT version FROM schema_version').fetchone()[0]==5
    assert book.connection.execute('SELECT count(*) FROM events').fetchone()[0]==0
    assert book.connection.execute('SELECT count(*) FROM option_plans').fetchone()[0]==0
    book.close()
