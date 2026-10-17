import json
from pathlib import Path
from native_tools import native_engine_root,native_dotnet
from personal_quant.config import Config
from personal_quant.portfolio import Ledger
from personal_quant.workspace.service import create,worker
from personal_quant.workspace.option_setup import prepare
from personal_quant.workspace.lifecycle_calendar import calendar_view

ROOT=Path(__file__).resolve().parents[1]


def test_option_batch_market_boundary_settlement_repeat_and_frozen_calendar(tmp_path):
    root=tmp_path/'workspace'
    create(root,{'schema_version':1,'kind':'options','account_id':'demo-account','initial_cash':'100000'},Config.load(ROOT/'configs/demo.toml'))
    setup=prepare(root,json.loads((ROOT/'configs/v195-option-setup.json').read_text()))
    started=worker(root,'start',input_file=setup['request_file'],engine_root=native_engine_root(),dotnet=native_dotnet(),fee_per_contract=2)
    # Requesting the settlement day must first commit the final market prefix.
    first=worker(root,'batch',started['run_id'],setup['last_settlement_session'],max_sessions=128,max_seconds=600,min_free_bytes=0)
    assert first['batch']['reason']=='BATCH_MARKET_BOUNDARY'
    assert first['through_session']==setup['last_market_session'] and first['events']==7
    final=worker(root,'batch',started['run_id'],setup['last_settlement_session'],max_sessions=128,max_seconds=600,min_free_bytes=0)
    assert final['status']=='COMPLETED' and final['details']['equity']=='99978.00'
    repeated=worker(root,'batch',started['run_id'],setup['last_settlement_session'],max_sessions=1,max_seconds=600,min_free_bytes=0)
    assert repeated['events']==7 and repeated['details']['equity']==final['details']['equity']
    book=Ledger.read_only(root/'runtime/demo/account.sqlite','demo')
    try:
        before=book.sequence('demo-account')
        calendar=calendar_view(book,'demo-account','2024-11-02T21:00:00Z')
        assert len(calendar['decisions'])==1 and not calendar['calendar_checks']
        assert calendar['decisions'][0]['applicable_session']=='2024-11-01'
        assert book.sequence('demo-account')==before==7
        assert book.connection.execute("SELECT count(*) FROM events WHERE json_extract(payload,'$.kind')='DEPOSIT'").fetchone()[0]==1
    finally:book.close()
