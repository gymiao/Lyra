from pathlib import Path
import pandas as pd
import pytest

from personal_quant.config import Config
from personal_quant.data.fixture import create_fixture
from personal_quant.data.calendar import Calendar
from personal_quant.data.store import DataStore
from personal_quant.portfolio import Ledger


def pytest_collection_finish(session):
    """Opt-in release evidence, including every collected node before execution."""
    import os,json
    if destination:=os.environ.get('LYRAX_TEST_REPORT_FILE'):
        Path(destination+'.collection.json').write_text(json.dumps([item.nodeid for item in session.items]))


def pytest_runtest_logreport(report):
    """Persist failures immediately, even if a later native extension crashes."""
    import os,json
    if destination:=os.environ.get('LYRAX_TEST_REPORT_FILE'):
        entry={'nodeid':report.nodeid,'phase':report.when,'outcome':report.outcome,'duration':report.duration,
               'wasxfail':bool(getattr(report,'wasxfail',False))}
        if report.failed:entry['failure']=str(report.longrepr)
        with Path(destination).open('a') as stream:
            stream.write(json.dumps(entry)+'\n');stream.flush()


@pytest.fixture(scope='session')
def option_experiment_cases(tmp_path_factory):
    from test_option_experiments_v195 import build_experiments
    return build_experiments(tmp_path_factory)


@pytest.fixture(scope='session')
def credit_evidence(tmp_path_factory):
    from test_options_credit_qualification_v195 import build_credit_evidence
    return build_credit_evidence(tmp_path_factory)


@pytest.fixture(scope='session')
def vol_evidence(tmp_path_factory):
    from test_options_vol_qualification_v195 import build_vol_evidence
    return build_vol_evidence(tmp_path_factory)


@pytest.fixture
def config():
    return Config.load(Path(__file__).resolve().parents[1] / "configs/demo.toml")


@pytest.fixture
def market(tmp_path):
    prices, sessions = create_fixture(tmp_path / "fixture")
    calendar = Calendar.csv(sessions, "synthetic_test_sessions")
    store = DataStore(tmp_path / "data")
    metadata = store.save(pd.read_csv(prices), calendar)
    return store, *store.load(metadata["snapshot_id"])


@pytest.fixture
def ledger(tmp_path):
    book = Ledger(tmp_path / "demo.sqlite", "demo")
    book.account("sample")
    yield book
    book.close()


def event(event_id, kind, **values):
    return {"event_id": event_id, "kind": kind, "effective_at": "2024-07-01T20:00:00+00:00",
            "source": "test_statement_v1", "evidence_type": "test", **values}



@pytest.fixture(scope='session')
def four_evidence(tmp_path_factory):
    from test_four_leg_native_v20 import build_evidence
    return build_evidence(tmp_path_factory.mktemp('four-leg-evidence'))
