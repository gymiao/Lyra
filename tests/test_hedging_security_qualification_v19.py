"""Isolated evidence fixtures test linkage, not actual vendor or broker qualification."""
import hashlib
from copy import deepcopy
import pytest
from personal_quant.common import QuantError,now_utc
from personal_quant.data.qualification import register as qualify,require_qualification,load_evidence
from personal_quant.data.store import DataStore
from personal_quant.hedging.securities import register,assess
from personal_quant.portfolio.schema import apply_workbench_schema,apply_v18_schema,apply_v19_schema
from test_hedging_securities_v19 import identity


def setup(ledger,market,tmp_path):
    with ledger.transaction():
        apply_workbench_schema(ledger.connection);apply_v18_schema(ledger.connection);apply_v19_schema(ledger.connection)
    _,frame,_,calendar=market;store=DataStore(ledger.path.parent/'data');meta=store.save(frame,calendar)
    directory=tmp_path/'proof';directory.mkdir();(directory/'terms.txt').write_text('ISOLATED TEST: fabricated vendor terms, no production evidence')
    body=dict(schema_version=1,series_id=store.series_identity(meta),sources=meta['source'],market='XNYS',currency='USD',
        timezone='America/New_York',price_basis='unadjusted',units_description='shares',adjustment_method='none',
        actions_description='explicit actions',scope_symbols=meta['symbols'],reviewed_at='2024-01-01T00:00:00Z',
        valid_until='2027-01-01T00:00:00Z',decision='QUALIFIED',reviewer='fixture',reason='engineering fixture only',
        evidence_type='actual',evidence_files={'terms.txt':hashlib.sha256((directory/'terms.txt').read_bytes()).hexdigest()})
    proof=qualify(ledger,body,directory);version=register(ledger.path.parent,'demo',identity(source_type='declared',
        source_qualification_refs=[proof['qualification_id']]))['record']['version_hash']
    req=dict(security_versions={'SPY':version},security_ids={'SPY':'security-us-spy'},as_of='2025-01-15T21:30:00Z',
        knowledge_cutoff=now_utc(),valuation_snapshot_id=meta['snapshot_id'],ledger_seq=0)
    return store,meta,body,directory,proof,req


def test_identity_label_and_bound_test_proof_cannot_become_execution(ledger,market,tmp_path):
    _,_,_,_,_,req=setup(ledger,market,tmp_path)
    out=assess(ledger,'sample',req)
    assert not out['executable'] and out['status']=='BLOCKED'
    assert 'SYNTHETIC_IDENTITY_OR_SOURCE:SPY' in out['checks']
    assert out['securities']['SPY']['source_assessment']['decision']=='QUALIFIED'
    version=register(ledger.path.parent,'demo',identity(source_type='declared'))['record']['version_hash']
    assert 'SECURITY_SOURCE_NOT_BOUND:SPY' in assess(ledger,'sample',dict(req,security_versions={'SPY':version},knowledge_cutoff=now_utc()))['checks']


def test_refusal_revocation_and_knowledge_cutoff_not_latest_future_record(ledger,market,tmp_path):
    _,meta,body,directory,proof,req=setup(ledger,market,tmp_path)
    cutoff=req['knowledge_cutoff'];row=qualify(ledger,dict(body,decision='REJECTED',reason='revoked fixture'),directory)
    prior=require_qualification(ledger.connection,ledger.path.parent,meta,body['series_id'],cutoff,knowledge_cutoff=cutoff)
    assert prior['qualification_id']==proof['qualification_id']
    out=assess(ledger,'sample',dict(req,knowledge_cutoff=now_utc()))
    assert 'SOURCE_NOT_QUALIFIED:SPY' in out['checks']
    with pytest.raises(QuantError) as exc:load_evidence(ledger.connection,ledger.path.parent,row['qualification_id'],cutoff)
    assert exc.value.code=='SOURCE_NOT_KNOWN'


def test_missing_action_and_resealed_source_file_are_not_opaque_claims(ledger,market,tmp_path):
    _,_,_,_,proof,req=setup(ledger,market,tmp_path)
    version=register(ledger.path.parent,'demo',identity(source_type='declared',source_qualification_refs=[proof['qualification_id']],
        corporate_action_refs=['missing-split']))['record']['version_hash']
    out=assess(ledger,'sample',dict(req,security_versions={'SPY':version},knowledge_cutoff=now_utc()))
    assert 'SECURITY_ACTION_NOT_BOUND:SPY' in out['checks']
    file=ledger.path.parent/'qualifications'/proof['qualification_id']/'terms.txt';file.write_text('changed')
    assert 'CORRUPT_SOURCE_EVIDENCE:SPY' in assess(ledger,'sample',dict(req,knowledge_cutoff=now_utc()))['checks']


def test_malformed_registered_source_evidence_has_stable_failure(ledger,market,tmp_path):
    _,_,_,_,proof,req=setup(ledger,market,tmp_path)
    ledger.connection.execute('UPDATE source_qualifications SET payload=? WHERE qualification_id=?',
        ('{"reviewed_at":"2024-01-01T00:00:00Z"}',proof['qualification_id']))
    with pytest.raises(QuantError) as exc:
        load_evidence(ledger.connection,ledger.path.parent,proof['qualification_id'],req['knowledge_cutoff'])
    assert exc.value.code=='CORRUPT_SOURCE_EVIDENCE'
