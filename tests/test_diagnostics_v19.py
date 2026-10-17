from dataclasses import replace
import pandas as pd
from personal_quant.diagnostics import doctor
from personal_quant.data.fixture import create_fixture
from personal_quant.data.calendar import Calendar
from personal_quant.data.store import DataStore
from personal_quant.portfolio import Ledger


def workspace(tmp_path, config, gap=False):
    cfg = replace(config, runtime_dir=str(tmp_path))
    prices, sessions = create_fixture(tmp_path / 'fixture')
    frame = pd.read_csv(prices)
    if gap:
        frame = frame.loc[~((frame.symbol == 'SPY') & (frame.session_date == '2024-12-20'))]
    DataStore(tmp_path / 'data').save(frame, Calendar.csv(sessions, 'synthetic_test_sessions'))
    return cfg


def test_recent_gap_blocks_despite_more_than_126_old_observations(tmp_path, config):
    cfg = workspace(tmp_path, config, gap=True)
    result = doctor(cfg, '2024-12-31T21:40:00Z')
    history = next(c for c in result['checks'] if c['kind'] == 'history')
    assert history['status'] == 'BLOCKED'
    assert history['missing_sessions']['SPY'] == ['2024-12-20']


def test_successful_retry_resolves_old_task_failure_but_other_run_stays_visible(tmp_path, config):
    cfg = workspace(tmp_path, config)
    book = Ledger(tmp_path / 'account.sqlite', 'demo')
    book.account('sample')
    for run_id, state in [('retry', 'SUCCESS'), ('other', 'FAILED')]:
        book.connection.execute('INSERT INTO daily_runs VALUES(?,?,?,?,?,?,?,?)',
            (run_id, 'sample', 'demo', '2024-12-31', cfg.hash, 'source', state, '2024-12-31T21:00:00Z'))
        book.connection.execute('INSERT INTO daily_attempts VALUES(?,?,?,?,?,?)',
            (run_id + '-failed', run_id, 'FAILED', '2024-12-31T21:30:00Z', '2024-12-31T21:31:00Z', '{}'))
    book.connection.execute('INSERT INTO daily_attempts VALUES(?,?,?,?,?,?)',
        ('retry-success', 'retry', 'SUCCESS', '2024-12-31T21:35:00Z', '2024-12-31T21:36:00Z', '{}'))
    book.connection.commit()
    book.close()
    tasks = [c['id'] for c in doctor(cfg, '2024-12-31T21:40:00Z')['checks'] if c['kind'] == 'task']
    assert tasks == ['other']


def test_running_retry_does_not_resolve_failed_run(tmp_path, config):
    cfg=workspace(tmp_path,config);book=Ledger(tmp_path/'account.sqlite','demo');book.account('sample')
    book.connection.execute('INSERT INTO daily_runs VALUES(?,?,?,?,?,?,?,?)',
        ('running','sample','demo','2024-12-31',cfg.hash,'source','RUNNING','2024-12-31T21:00:00Z'))
    for identity,state,minute in [('failed','FAILED','30'),('retry','RUNNING','35')]:
        book.connection.execute('INSERT INTO daily_attempts VALUES(?,?,?,?,?,?)',
            (identity,'running',state,f'2024-12-31T21:{minute}:00Z',None,'{}'))
    book.connection.commit();book.close()
    assert [c['id'] for c in doctor(cfg,'2024-12-31T21:40:00Z')['checks'] if c['kind']=='task']==['running']
