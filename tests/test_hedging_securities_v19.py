import copy
import json
from pathlib import Path

import pytest

from personal_quant.common import QuantError,digest,now_utc
from personal_quant.hedging.securities import normalize,register,load,resolve
from personal_quant.hedging.coverage_service import account_coverage
from personal_quant.portfolio import Ledger
from personal_quant.portfolio.backup import create_bundle,verify_bundle,restore_bundle
from test_hedging_coverage_v19 import funded,request


def identity(**changes):
    return dict(dict(schema_version=1,security_id='security-us-spy',instrument_type='etf',
        ticker_history=[dict(ticker='SPY',valid_from='2024-01-01T00:00:00Z',valid_until='2030-01-01T00:00:00Z')],
        exchange='ARCX',calendar='XNYS',timezone='America/New_York',currency='USD',trade_unit='1',
        valid_from='2024-01-01T00:00:00Z',valid_until='2030-01-01T00:00:00Z',
        corporate_action_refs=[],source_qualification_refs=[],source_type='synthetic'),**changes)


def test_registration_idempotent_explicit_versions_and_no_implicit_upgrade(tmp_path):
    raw=identity();original=copy.deepcopy(raw);first=register(tmp_path,'demo',raw)
    assert register(tmp_path,'demo',raw)==first and raw==original
    raw['corporate_action_refs'].append('split-statement-one')
    second=register(tmp_path,'demo',raw)
    assert second['record']['version_hash']!=first['record']['version_hash']
    assert load(tmp_path,first['record']['version_hash'])==first
    assert first['record']['qualification']=='declared_identity_only' and not first['record']['executable']


@pytest.mark.parametrize('changes',[
    {'trade_unit':0},{'source_type':'verified'}, {'currency':'CNY'}, {'schema_version':True},
    {'corporate_action_refs':['one','one']}, {'ticker_history':[]},
    {'ticker_history':[dict(ticker='SPY',valid_from='2024-01-01T00:00:00Z',valid_until='2030-01-01T00:00:00Z')]*2}])
def test_invalid_or_self_qualified_identity_rejected(changes):
    with pytest.raises(QuantError):normalize(identity(**changes))


def test_stable_id_and_ticker_cannot_change_under_an_existing_binding(tmp_path):
    register(tmp_path,'demo',identity())
    with pytest.raises(QuantError) as exc:register(tmp_path,'demo',identity(instrument_type='stock'))
    assert exc.value.code=='SECURITY_IDENTITY_CONFLICT'
    with pytest.raises(QuantError) as exc:register(tmp_path,'demo',identity(security_id='a-different-id'))
    assert exc.value.code=='SECURITY_TICKER_CONFLICT'
    with pytest.raises(QuantError):register(tmp_path,'real',identity())


def test_knowledge_clock_alias_window_hash_and_link_checks(tmp_path):
    first=register(tmp_path,'demo',identity());version=first['record']['version_hash']
    mapping={'SPY':'security-us-spy'}
    result=resolve(tmp_path,'demo',{'SPY':version},mapping,'2026-10-09T21:00:00Z',now_utc())
    assert result['SPY']['record_hash']==first['record']['record_hash']
    with pytest.raises(QuantError) as exc:resolve(tmp_path,'demo',{'SPY':version},mapping,'2026-10-09T21:00:00Z','2024-01-01T00:00:00Z')
    assert exc.value.code=='SECURITY_NOT_KNOWN'
    with pytest.raises(QuantError) as exc:resolve(tmp_path,'demo',{'SPY':version},mapping,'2031-01-01T00:00:00Z',now_utc())
    assert exc.value.code=='SECURITY_NOT_ACTIVE'
    file=tmp_path/'hedging/securities'/version/'identity.json';before=file.read_bytes()
    file.write_text(json.dumps(identity(trade_unit='2')))
    with pytest.raises(QuantError):load(tmp_path,version)
    file.write_bytes(before);file.rename(file.with_suffix('.original'));file.symlink_to(file.with_suffix('.original'))
    with pytest.raises(QuantError):load(tmp_path,version)


def test_coverage_binds_registered_version_and_rejects_unknown_or_mismatched_ids(ledger):
    c=funded(ledger);item=register(ledger.path.parent,'demo',identity());version=item['record']['version_hash']
    req=request(ledger,c);req['security_versions']={'SPY':version}
    result=account_coverage(ledger,'sample',req)
    assert result['actual_protected_shares']['security-us-spy']=='100'
    assert result['security_identity_basis']['SPY']['version_hash']==version and not result['executable']
    req['security_ids']['SPY']='another-id'
    with pytest.raises(QuantError) as exc:account_coverage(ledger,'sample',req)
    assert exc.value.code=='SECURITY_BINDING_CONFLICT'


def test_complete_backup_restore_and_tampered_registry_is_rejected(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    runtime=tmp_path/'runtime/demo';runtime.mkdir(parents=True)
    book=Ledger(runtime/'account.sqlite','demo');book.account('sample')
    cfg=tmp_path/'demo.toml';cfg.write_bytes((Path(__file__).resolve().parents[1]/'configs/demo.toml').read_bytes())
    item=register(runtime,'demo',identity());version=item['record']['version_hash']
    create_bundle(runtime,cfg,tmp_path/'bundle');verify_bundle(tmp_path/'bundle','demo')
    restore_bundle(tmp_path/'bundle',tmp_path/'restored','demo')
    assert load(tmp_path/'restored/runtime/demo',version)==item
    file=runtime/'hedging/securities'/version/'record.json';record=json.loads(file.read_text());record['registered_at']='2024-01-01T00:00:00Z'
    file.write_text(json.dumps(record))
    with pytest.raises(QuantError) as exc:create_bundle(runtime,cfg,tmp_path/'bad-bundle')
    assert exc.value.code=='CORRUPT_SECURITY_REGISTRY'
    book.close()
