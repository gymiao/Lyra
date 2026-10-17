import hashlib
import pytest
from personal_quant.common import QuantError,now_utc
from personal_quant.data.qualification import register,require_qualification
from personal_quant.portfolio.schema import apply_workbench_schema,apply_v18_schema,apply_v19_schema


def test_csv_label_and_test_evidence_do_not_grant_real_unit_qualification(ledger,tmp_path):
    with ledger.transaction():
        apply_workbench_schema(ledger.connection);apply_v18_schema(ledger.connection);apply_v19_schema(ledger.connection)
    metadata={'source':['test_source'],'symbols':['SPY']}
    with pytest.raises(QuantError,match='未取得来源'):require_qualification(ledger.connection,ledger.path.parent,metadata,'series',now_utc())
    evidence=tmp_path/'evidence';evidence.mkdir();(evidence/'terms.txt').write_text('TEST source terms; no actual validation')
    body={'schema_version':1,'series_id':'series','sources':['test_source'],'market':'XNYS','currency':'USD',
          'timezone':'America/New_York','price_basis':'unadjusted','units_description':'test shares',
          'adjustment_method':'test raw','actions_description':'test split/dividend units',
          'scope_symbols':['SPY'],'reviewed_at':'2024-01-01T00:00:00Z','valid_until':'2027-01-01T00:00:00Z',
          'decision':'QUALIFIED','reviewer':'unit_test','reason':'test path only','evidence_type':'test',
          'evidence_files':{'terms.txt':hashlib.sha256((evidence/'terms.txt').read_bytes()).hexdigest()}}
    registered=register(ledger,body,evidence)
    assert registered['evidence_type']=='test'
    with pytest.raises(QuantError,match='实际核验'):require_qualification(ledger.connection,ledger.path.parent,metadata,'series',now_utc())
    (evidence/'terms.txt').write_text('changed')
    with pytest.raises(QuantError,match='哈希'):register(ledger,body,evidence)
