import json
from pathlib import Path
from conftest import event
from personal_quant.common import digest,write_json
from personal_quant.config import Config
from personal_quant.workspace.lifecycle_calendar import calendar_view
from personal_quant.workspace.service import create
from personal_quant.workspace.diagnostic import view
from personal_quant.workspace.worker import SCHEMA

ROOT=Path(__file__).resolve().parents[1]


def test_calendar_dividend_dates_are_receipts_not_guesses(ledger):
    ledger.import_events('sample',[
        event('capital','DEPOSIT',amount=1000),
        event('known','DIVIDEND_ACCRUAL',symbol='SPY',amount=10,
              effective_at='2024-07-05T20:00:00Z',settlement_at='2024-07-10T20:00:00Z'),
        event('unknown','DIVIDEND_ACCRUAL',symbol='SPY',amount=2,effective_at='2024-07-05T20:00:00Z'),
        event('paid','DIVIDEND_PAYMENT',reference_event_id='known',amount=10,effective_at='2024-07-10T20:00:00Z')])
    changes=ledger.connection.total_changes
    before=calendar_view(ledger,'sample','2024-07-06T21:00:00Z')
    rows={r['event_id']:r for r in before['dividends']}
    assert rows['known']['status']=='PENDING' and rows['known']['paid_at'] is None
    assert rows['known']['expected_payment_at']=='2024-07-10T20:00:00+00:00'
    assert rows['unknown']['status']=='UNKNOWN_PAYMENT_DATE'
    after=calendar_view(ledger,'sample','2024-07-11T21:00:00Z')
    assert {r['event_id']:r['status'] for r in after['dividends']}=={'known':'PAID_RECORDED','unknown':'UNKNOWN_PAYMENT_DATE'}
    assert ledger.connection.total_changes==changes


def test_calendar_signal_index_checks_identity_and_excludes_future(ledger):
    ledger.connection.executescript(SCHEMA)
    root=ledger.path.parent/'simulation'
    identity={'workspace_id':'calendar-fixture','kind':'options','account_id':'sample'}
    write_json(root/'workspace.json',identity)
    index={'request_hash':'request-id','signals':[
        {'monthly_signal_id':'past','decision_at':'2024-07-01T21:00:00Z','applicable_session':'2024-07-02','applicable_close':'2024-07-02T20:00:00Z','generation_mode':'historical_reconstruction'},
        {'monthly_signal_id':'future','decision_at':'2024-08-01T21:00:00Z','applicable_session':'2024-08-02','applicable_close':'2024-08-02T20:00:00Z','generation_mode':'historical_reconstruction'}]}
    settings={'request_hash':'request-id','calendar_index_hash':digest(index)}
    run_id=digest({'workspace':identity['workspace_id'],'settings':settings})
    directory=root/'options'/run_id
    write_json(directory/'settings.json',settings);write_json(directory/'calendar-index.json',index)
    ledger.connection.execute('INSERT INTO simulation_runs VALUES(?,?,?,?,?,?)',(run_id,'CREATED',None,'source','2024-07-01T21:00:00Z','{}'))
    changes=ledger.connection.total_changes
    result=calendar_view(ledger,'sample','2024-07-05T21:00:00Z')
    assert [r['monthly_signal_id'] for r in result['decisions']]==['past']
    assert result['decisions'][0]['applicable_session']=='2024-07-02'
    assert result['dividend_evidence']=='UNKNOWN_NO_RECEIPTS' and not result['calendar_checks']
    index['signals'][0]['applicable_session']='2024-07-03';write_json(directory/'calendar-index.json',index)
    damaged=calendar_view(ledger,'sample','2024-07-05T21:00:00Z')
    assert not damaged['decisions'] and damaged['calendar_checks'][0]['status']=='UNVERIFIED_DECISION_INDEX'
    assert ledger.connection.total_changes==changes


def test_diagnostic_exports_only_whitelisted_error_codes(tmp_path):
    root=tmp_path/'workspace'
    create(root,{'schema_version':1,'kind':'options','account_id':'private-name','initial_cash':'100000'},Config.load(ROOT/'configs/demo.toml'))
    runtime=root/'runtime/demo'
    write_json(runtime/'simulation/options'/('a'*64)/'last-failure.json',{'code':'LEAN_REPLAY_FAILED','reason':'secret-token-in-error'})
    write_json(runtime/'simulation/jobs/job/result.json',{'status':'FAILED','code':'secret-token-as-code','reason':'private-path'})
    result=view(root);encoded=json.dumps(result)
    assert {r['code'] for r in result['errors']}=={'LEAN_REPLAY_FAILED','UNCLASSIFIED_ERROR'}
    assert not any(s in encoded for s in ('secret-token','private-path','private-name',str(root)))
    assert set(result['configuration'])=={'hash','environment','market','currency'}
    assert result['event_count']==1 and result['read_only']
