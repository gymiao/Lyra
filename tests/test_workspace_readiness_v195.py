from pathlib import Path
from personal_quant.config import Config
from personal_quant.data.store import DataStore
from personal_quant.workspace.service import create
from personal_quant.workspace.readiness import describe

ROOT=Path(__file__).resolve().parents[1]


def test_option_workspace_does_not_misreport_unused_etf_inputs_as_missing(tmp_path):
    root=tmp_path/'options'
    create(root,{'schema_version':1,'kind':'options','account_id':'demo-account','initial_cash':'100000'},Config.load(ROOT/'configs/demo.toml'))
    rows=describe(root)
    assert all(row['状态']=='不需要' for row in rows if row['用途'] in {'signal','execution','valuation','期权Greeks行情'})
    assert next(row['状态'] for row in rows if row['用途']=='期权配置')=='待准备输入'


def test_shared_diagnostic_and_daily_guidance_agree_with_option_readiness(tmp_path,monkeypatch):
    from personal_quant.diagnostics import doctor
    from personal_quant.portfolio import Ledger
    from personal_quant.ui.v19 import today
    root=tmp_path/'options'
    create(root,{'schema_version':1,'kind':'options','account_id':'demo-account','initial_cash':'100000'},Config.load(ROOT/'configs/demo.toml'))
    monkeypatch.chdir(root);config=Config.load(root/'config.json')
    result=doctor(config,'2024-11-01T21:30:00Z')
    assert result['workspace_kind']=='options' and result['status']=='READY_FOR_REVIEW'
    assert {r['id']:r['status'] for r in result['checks'] if r['kind']=='data'}==dict.fromkeys(['signal','execution','valuation'],'NOT_REQUIRED')
    book=Ledger.read_only(root/'runtime/demo/account.sqlite','demo')
    try:
        guidance=today(book,config,'2024-11-01T21:30:00Z')
        assert not any(r['事项'].startswith('data/') for r in guidance['todo'])
        assert 'ETF月末日历' in guidance['calendar_reason']
        assert book.sequence('demo-account')==1
    finally:book.close()


def test_etf_status_reads_metadata_without_loading_or_claiming_price_validation(tmp_path,monkeypatch):
    root=tmp_path/'etf'
    create(root,{'schema_version':1,'kind':'etf','account_id':'demo-account','initial_cash':'100000'},Config.load(ROOT/'configs/demo.toml'))
    def forbid(*args,**kwargs):raise AssertionError('status must not scan historical Parquet')
    monkeypatch.setattr(DataStore,'load',forbid)
    rows=describe(root)
    assert len(rows)==3 and all(row['状态']=='已登记，未重验原始文件' for row in rows)
    assert all(row['数据类型']=='synthetic' and row['登记截至'] for row in rows)


def test_malformed_role_metadata_produces_explicit_error(tmp_path):
    import pytest
    from personal_quant.common import QuantError
    root=tmp_path/'etf'
    create(root,{'schema_version':1,'kind':'etf','account_id':'demo-account','initial_cash':'100000'},Config.load(ROOT/'configs/demo.toml'))
    (root/'runtime/demo/data/series-heads.json').write_text('[]')
    with pytest.raises(QuantError) as error:describe(root)
    assert error.value.code=='CORRUPT_STATUS_METADATA'
