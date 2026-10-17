import json
from pathlib import Path
import pytest
from personal_quant.common import QuantError, canonical
from personal_quant.config import Config
from personal_quant.portfolio import Ledger
from personal_quant.workspace.service import create
from personal_quant.workspace.worker import SCHEMA
from personal_quant.workspace.options_runner import publish_checkpoint

ROOT=Path(__file__).resolve().parents[1]


def fixture(tmp_path):
    root=tmp_path/'options'
    create(root,{'schema_version':1,'account_id':'demo-account','initial_cash':'100000','kind':'options'},Config.load(ROOT/'configs/demo.toml'))
    runtime=root/'runtime/demo';book=Ledger(runtime/'account.sqlite','demo')
    book.connection.executescript(SCHEMA)
    detail={'as_of':'2024-11-04T21:30:00+00:00','prices':{},'equity':'100000','data_type':'synthetic_prefix_simulation'}
    book.connection.execute('INSERT INTO simulation_runs VALUES(?,?,?,?,?,?)',('run','REPORT_PENDING','2024-11-04','source','now',canonical(detail)))
    book.connection.execute('INSERT INTO simulation_checkpoints VALUES(?,?,?)',('run','2024-11-04',canonical(detail)))
    return book,runtime


def test_report_write_failure_recovers_committed_facts_without_duplicate_funding(tmp_path,monkeypatch):
    from personal_quant.workspace import options_runner
    book,runtime=fixture(tmp_path)
    try:
        real=options_runner.account_report
        def interrupted(*args,**kwargs):
            real(*args,**kwargs)
            raise OSError('interrupted after filesystem publication')
        monkeypatch.setattr(options_runner,'account_report',interrupted)
        with pytest.raises(OSError):publish_checkpoint(book,runtime,'demo-account','run','2024-11-04')
        assert book.connection.execute('SELECT status FROM simulation_runs').fetchone()[0]=='REPORT_PENDING'
        assert book.sequence('demo-account')==1
        monkeypatch.setattr(options_runner,'account_report',real)
        first=publish_checkpoint(book,runtime,'demo-account','run','2024-11-04')
        again=publish_checkpoint(book,runtime,'demo-account','run','2024-11-04')
        assert first['report_id']==again['report_id']
        assert first['equity']=='100000' and book.sequence('demo-account')==1
        assert json.loads(book.connection.execute('SELECT details FROM simulation_checkpoints').fetchone()[0])['report_id']==first['report_id']
    finally:book.close()


def test_changed_checkpoint_facts_cannot_publish_old_equity(tmp_path):
    book,runtime=fixture(tmp_path)
    try:
        book.import_events('demo-account',[{'event_id':'late','kind':'DEPOSIT','amount':'10','effective_at':'2024-11-01T21:00:00Z','source':'test','evidence_type':'test'}])
        before=(runtime/'reports/account-latest/latest.json').read_bytes()
        with pytest.raises(QuantError) as error:publish_checkpoint(book,runtime,'demo-account','run','2024-11-04')
        assert error.value.code=='SIMULATION_CHECKPOINT_CHANGED'
        assert (runtime/'reports/account-latest/latest.json').read_bytes()==before
    finally:book.close()


def test_closed_account_settles_without_new_trades_or_investment_profit(tmp_path):
    from personal_quant.workspace.options_runner import settle_checkpoint
    book,runtime=fixture(tmp_path)
    try:
        book.import_events('demo-account',[
            {'event_id':'buy','kind':'BUY','symbol':'SPY','quantity':'100','price':'100','fee':'2',
             'effective_at':'2024-11-01T20:00:00Z','settlement_at':'2024-11-04T21:00:00Z','source':'test','evidence_type':'test'},
            {'event_id':'sell','kind':'SELL','symbol':'SPY','quantity':'100','price':'100','fee':'3',
             'effective_at':'2024-11-04T20:40:00Z','settlement_at':'2024-11-05T21:00:00Z','source':'test','evidence_type':'test'}])
        detail={'as_of':'2024-11-04T21:30:00Z','prices':{},'equity':'99995'}
        book.connection.execute('UPDATE simulation_runs SET details=?',(canonical(detail),))
        book.connection.execute('UPDATE simulation_checkpoints SET details=?',(canonical(detail),))
        before=book.snapshot('demo-account',detail['as_of'],{})
        assert float(before['receivables'])==9997 and float(before['equity'])==99995
        done=settle_checkpoint(book,runtime,'demo-account','run','2024-11-05','2024-11-05T21:30:00Z')
        final=book.snapshot('demo-account',done['as_of'],{})
        assert final['positions']=={} and float(final['settled_cash'])==99995
        assert float(final['investment_pnl'])==-5 and book.sequence('demo-account')==3
        assert book.connection.execute('SELECT status FROM simulation_runs').fetchone()[0]=='COMPLETED'
        assert publish_checkpoint(book,runtime,'demo-account','run','2024-11-05')['report_id']==done['report_id']
    finally:book.close()


def test_settlement_cannot_hide_open_stock_position(tmp_path):
    from personal_quant.workspace.options_runner import settle_checkpoint
    book,runtime=fixture(tmp_path)
    try:
        book.import_events('demo-account',[{'event_id':'buy','kind':'BUY','symbol':'SPY','quantity':'100','price':'100',
            'effective_at':'2024-11-01T20:00:00Z','settlement_at':'2024-11-04T21:00:00Z','source':'test','evidence_type':'test'}])
        with pytest.raises(QuantError) as caught:settle_checkpoint(book,runtime,'demo-account','run','2024-11-05','2024-11-05T21:30:00Z')
        assert caught.value.code=='OPEN_POSITIONS_WITHOUT_PRICES'
        assert book.connection.execute('SELECT count(*) FROM simulation_checkpoints').fetchone()[0]==1
    finally:book.close()


def test_daily_report_publication_recovers_without_losing_final_run_head(tmp_path,monkeypatch):
    from personal_quant.workspace import options_runner
    book,runtime=fixture(tmp_path)
    try:
        detail={'as_of':'2024-11-05T21:30:00Z','prices':{},'equity':'100000'}
        book.connection.execute('INSERT INTO simulation_checkpoints VALUES(?,?,?)',('run','2024-11-05',canonical(detail)))
        book.connection.execute('UPDATE simulation_runs SET through_session=?,details=?',('2024-11-05',canonical(detail)))
        real=options_runner.account_report;calls=[]
        def interrupted(*args,**kwargs):
            result=real(*args,**kwargs);calls.append(result['as_of'])
            if len(calls)==2:raise OSError('interrupted second daily publication')
            return result
        monkeypatch.setattr(options_runner,'account_report',interrupted)
        with pytest.raises(OSError):options_runner.publish_pending_checkpoints(book,runtime,'demo-account','run')
        assert book.connection.execute('SELECT status FROM simulation_runs').fetchone()[0]=='REPORT_PENDING'
        monkeypatch.setattr(options_runner,'account_report',real)
        options_runner.publish_pending_checkpoints(book,runtime,'demo-account','run')
        done=options_runner.publish_checkpoint(book,runtime,'demo-account','run','2024-11-05')
        state=book.connection.execute('SELECT through_session,details FROM simulation_runs').fetchone()
        assert state[0]=='2024-11-05' and json.loads(state[1])['report_id']==done['report_id']
        assert book.sequence('demo-account')==1
        assert all(json.loads(row[0]).get('report_id') for row in book.connection.execute('SELECT details FROM simulation_checkpoints'))
    finally:book.close()
