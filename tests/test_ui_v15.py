from pathlib import Path

from personal_quant.portfolio import Ledger
from personal_quant.strategies.store import StrategyStore
from test_ui import setup_ui, button


def test_workbench_enable_editor_template_switch_and_refresh_no_writes(tmp_path, monkeypatch):
    app = setup_ui(tmp_path, monkeypatch).run()
    app.sidebar.radio[0].set_value("策略研究").run()
    button(app, "备份并启用策略工作台").click().run()
    assert not app.exception and not app.error
    template = next(item for item in app.selectbox if item.label == "策略模板")
    template.set_value("momentum_rotation").run()
    button(app, "校验并冻结新版本").click().run()
    assert not app.exception and not app.error
    book = Ledger(Path("runtime/demo/account.sqlite"), "demo")
    try:
        first = StrategyStore(book).get("momentum_rotation", 1)
        assert first.content()["parameters"] == {"lookback": 126, "top_k": 2}
    finally:
        book.close()
    next(item for item in app.selectbox if item.label == "策略模板").set_value("inverse_volatility").run()
    button(app, "校验并保存草稿").click().run()
    assert not app.exception and not app.error
    from personal_quant.strategies.drafts import DraftStore
    assert len(DraftStore(Path("runtime/demo/drafts")).list()) == 1
    button(app, "校验并冻结新版本").click().run()
    assert not app.exception and not app.error
    button(app, "冻结六类演示版本（预算95%）").click().run()
    assert not app.exception and not app.error
    app.run()
    book = Ledger(Path("runtime/demo/account.sqlite"), "demo")
    try:
        versions = StrategyStore(book).list()
        assert len(versions) == 6
        assert StrategyStore(book).get("inverse_volatility", 1).content()["parameters"] == {"lookback": 63}
        assert book.connection.execute("SELECT count(*) FROM events").fetchone()[0] == 0
        assert book.connection.execute("SELECT count(*) FROM research_attempts").fetchone()[0] == 0
        assert book.connection.execute("SELECT count(*) FROM strategy_bindings").fetchone()[0] == 0
    finally:
        book.close()
