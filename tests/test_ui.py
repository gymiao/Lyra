"""Exercise the real Streamlit app in isolated working directories."""
from pathlib import Path
import shutil

import pandas as pd
import pytest

pytest.importorskip("streamlit", reason="四页操作验收需实际Streamlit依赖")
from streamlit.testing.v1 import AppTest

from personal_quant.data.store import DataStore
from personal_quant.portfolio import Ledger
from personal_quant.portfolio.imports import event_csv
from personal_quant.portfolio.report import report_from_store

REPO = Path(__file__).resolve().parents[1]
APP = REPO / "src/personal_quant/ui/app.py"


def test_operational_timestamps_are_displayed_in_shanghai_time():
    from personal_quant.ui.app import display_records
    result = display_records([{"recorded_at": "2024-07-31T20:30:00Z", "finished_at": None}])
    assert result.iloc[0]["recorded_at"] == "2024-08-01 04:30:00+08:00"
    assert result.iloc[0]["finished_at"] == ""


def setup_ui(tmp_path, monkeypatch):
    (tmp_path / "configs").mkdir()
    shutil.copy2(REPO / "configs/demo.toml", tmp_path / "configs/demo.toml")
    monkeypatch.chdir(tmp_path)
    return AppTest.from_file(str(APP), default_timeout=20)


def button(app, label):
    return next(item for item in app.button if item.label == label)


def test_empty_account_and_all_four_pages_do_not_create_facts(tmp_path, monkeypatch):
    app = setup_ui(tmp_path, monkeypatch).run()
    assert not app.exception
    assert any("测试/模拟" in item.value for item in app.info)
    button(app, "建立空账户").click().run()
    assert not app.exception and not app.error
    button(app, "更新账户报告").click().run()
    assert not app.exception and not app.error
    assert [item.value for item in app.metric] == ["0", "0", "0", "0"]
    for page in ["策略研究", "调仓计划", "运行状态", "账户总览"]:
        app.sidebar.radio[0].set_value(page).run()
        assert not app.exception and not app.error, page
    book = Ledger(Path("runtime/demo/account.sqlite"), "demo")
    try:
        snapshot = book.snapshot("demo-account", "2024-12-31T21:30:00Z")
        assert snapshot["settled_cash"] == "0"
        assert snapshot["positions"] == {}
        assert not book.active_events("demo-account", "2024-12-31T21:30:00Z")
    finally:
        book.close()


def test_account_page_displays_independent_statement_math(market, config, tmp_path, monkeypatch):
    app = setup_ui(tmp_path, monkeypatch)
    _, _, _, calendar = market
    store = DataStore(Path("runtime/demo/data"))
    store.save(pd.read_csv(REPO / "examples/statement_prices.csv"), calendar)
    book = Ledger(Path("runtime/demo/account.sqlite"), "demo")
    book.account("sample")
    book.import_events("sample", event_csv((REPO / "examples/test_statement.csv").read_bytes()))
    report_from_store(book, "sample", "2024-07-31T21:00:00Z", store, config,
                      Path("runtime/demo/reports/account-latest"))
    book.close()
    app.run()
    app.sidebar.text_input[0].set_value("2024-07-31T21:00:00Z")
    next(item for item in app.text_input if item.label == "账户 ID").set_value("sample")
    app.run()
    assert not app.exception and not app.error
    values = {item.label: item.value for item in app.metric}
    assert float(values["总资产"]) == 998.5
    assert float(values["净投入"]) == 1000
    assert float(values["已结算现金"]) == 503.5
    assert float(values["投资盈亏"]) == -1.5
    displayed = app.dataframe[0].value
    assert displayed.iloc[0]["标的"] == "SPY"
    assert float(displayed.iloc[0]["实际份额"]) == 10
    app.run()
    restarted = AppTest.from_file(str(APP), default_timeout=20).run()
    assert not restarted.exception
    book = Ledger(Path("runtime/demo/account.sqlite"), "demo")
    try:
        assert len(book.active_events("sample", "2024-07-31T21:00:00Z")) == 5
    finally:
        book.close()
