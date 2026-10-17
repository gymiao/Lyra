"""Operation evidence in an isolated demo; no actual brokerage permissions are asserted."""
import hashlib
from pathlib import Path
import pytest
from personal_quant.common import now_utc,QuantError
from personal_quant.options.permissions import register,assess,series_id
from personal_quant.portfolio.schema import apply_workbench_schema,apply_v18_schema,apply_v19_schema
from personal_quant.portfolio.backup import create_bundle,verify_bundle,restore_bundle
from personal_quant.portfolio import Ledger


def proof(book,tmp_path,**overrides):
    with book.transaction():
        apply_workbench_schema(book.connection);apply_v18_schema(book.connection);apply_v19_schema(book.connection)
    directory=tmp_path/'evidence';directory.mkdir(exist_ok=True);(directory/'statement.txt').write_text('FIXTURE ONLY - not a broker statement')
    body=dict(schema_version=2,asset_type='ACCOUNT_OPTION_PERMISSIONS',series_id=series_id('sample',book.environment),
        account_id='sample',environment=book.environment,broker='test-broker',market='OPRA',currency='USD',
        scope_templates=['long_put','cash_secured_put'],scope_operations=['OPEN','CLOSE'],settlement_policy='cash_account_no_margin',
        exercise_policy='close_before_expiry',maximum_contracts=2,maximum_physical_cash='10000',minimum_exit_days=7,
        reviewed_at='2024-01-01T00:00:00Z',valid_until='2027-01-01T00:00:00Z',decision='QUALIFIED',reviewer='fixture',
        reason='isolated engineering fixture',evidence_type='test',evidence_files={'statement.txt':hashlib.sha256((directory/'statement.txt').read_bytes()).hexdigest()})
    body.update(overrides);return body,directory


def test_test_evidence_missing_and_caps_do_not_grant_any_permission(ledger,tmp_path):
    body,directory=proof(ledger,tmp_path)
    assert assess(ledger,'sample','long_put','CLOSE',now_utc())['checks']==['ACCOUNT_OPTION_PERMISSIONS_REQUIRED']
    first=register(ledger,body,directory);assert register(ledger,body,directory)==first
    at=now_utc();out=assess(ledger,'sample','long_put','OPEN',at,contract_count=3,exit_days=2)
    assert out['status']=='UNQUALIFIED' and not out['executable']
    assert set(out['checks'])=={'ACCOUNT_OPTION_LIMIT_EXCEEDED','ACCOUNT_OPTION_DISPOSITION_REQUIRED','ACCOUNT_OPTION_PERMISSIONS_NOT_QUALIFIED'}
    assert 'ACCOUNT_OPTION_OPERATION_NOT_PERMITTED' in assess(ledger,'sample','long_put','EXERCISE',at)['checks']
    assert 'ACCOUNT_OPTION_OPERATION_NOT_PERMITTED' in assess(ledger,'sample','covered_call','CLOSE',at)['checks']
    (ledger.path.parent/'qualifications'/first['qualification_id']/'statement.txt').write_text('changed')
    assert assess(ledger,'sample','long_put','CLOSE',at)['checks']==['CORRUPT_SOURCE_EVIDENCE']
    assert ledger.sequence('sample')==0


def test_actual_typed_fixture_scope_revocation_and_known_then(ledger,tmp_path):
    body,directory=proof(ledger,tmp_path,evidence_type='actual') # typed fixture only; isolated demo
    first=register(ledger,body,directory);at=now_utc()
    out=assess(ledger,'sample','long_put','OPEN',at,contract_count=2,exit_days=7)
    assert out['status']=='QUALIFIED' and not out['executable']
    register(ledger,dict(body,decision='REJECTED',reason='fixture revoked'),directory)
    assert assess(ledger,'sample','long_put','OPEN',at,contract_count=2,exit_days=7)==out
    assert 'ACCOUNT_OPTION_PERMISSIONS_NOT_QUALIFIED' in assess(ledger,'sample','long_put','CLOSE',now_utc())['checks']
    assert first['qualification_id']==out['qualification_id']


@pytest.mark.parametrize('changes',[{'scope_templates':['calendar_spread']},{'scope_operations':['AUTO_ORDER']},
    {'maximum_contracts':True},{'minimum_exit_days':0},{'settlement_policy':'margin'},{'environment':'real'}])
def test_unknown_or_unsupported_scopes_rejected(ledger,tmp_path,changes):
    body,directory=proof(ledger,tmp_path,**changes)
    with pytest.raises(QuantError):register(ledger,body,directory)


def test_test_permissions_cannot_enter_paper_registry(tmp_path):
    book=Ledger(tmp_path/'paper/account.sqlite','paper');book.account('sample')
    try:
        body,directory=proof(book,tmp_path)
        with pytest.raises(QuantError) as exc:register(book,body,directory)
        assert exc.value.code=='TEST_EVIDENCE_FORBIDDEN'
    finally:book.close()


def test_permission_archive_survives_complete_backup_without_account_assets(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path);book=Ledger(tmp_path/'runtime/demo/account.sqlite','demo');book.account('sample')
    try:
        body,directory=proof(book,tmp_path);register(book,body,directory)
        cfg=tmp_path/'demo.toml';cfg.write_bytes((Path(__file__).resolve().parents[1]/'configs/demo.toml').read_bytes())
        create_bundle(book.path.parent,cfg,tmp_path/'bundle');verify_bundle(tmp_path/'bundle','demo')
        restore_bundle(tmp_path/'bundle',tmp_path/'restored','demo');restored=Ledger(tmp_path/'restored/runtime/demo/account.sqlite','demo')
        try:
            at=now_utc();assert assess(restored,'sample','long_put','CLOSE',at)==assess(book,'sample','long_put','CLOSE',at)
            assert restored.sequence('sample')==0
        finally:restored.close()
    finally:book.close()
