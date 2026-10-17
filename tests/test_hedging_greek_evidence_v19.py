"""Greek evidence tests use fabricated files in an isolated demo account."""
import hashlib
import json

import pytest

from personal_quant.common import QuantError, now_utc
from personal_quant.hedging.greek_evidence import register, assess, assess_candidate, series_id
from personal_quant.hedging.stage_assessment import require_operation_risk
from personal_quant.options.contracts import OptionContract
from personal_quant.portfolio import Ledger
from personal_quant.portfolio.schema import apply_workbench_schema, apply_v18_schema, apply_v19_schema
from test_options_data_v19 import sample


def proof(book,tmp_path,**changes):
    with book.transaction():
        apply_workbench_schema(book.connection);apply_v18_schema(book.connection);apply_v19_schema(book.connection)
    contract=OptionContract.from_dict({**sample()[0].content(),'right':'PUT'})
    item=dict(contract_version=contract.version_hash,unit='per_share',value='-0.5',signed_contracts=2,
        source='fixture_provider',data_type='provider',as_of='2026-10-09T19:45:00Z',
        available_at='2026-10-09T19:45:02Z',received_at='2026-10-09T19:45:04Z',model_inputs={})
    directory=tmp_path/'greek-proof';directory.mkdir(exist_ok=True)
    (directory/'observation.json').write_text(json.dumps(item))
    (directory/'raw-provider.txt').write_text('ISOLATED TEST DATA: no vendor response or entitlement')
    body=dict(schema_version=2,asset_type='OPTION_GREEK_OBSERVATION',
        series_id=series_id(item['source'],contract.version_hash),contract=contract.content(),observation=item,
        reviewed_at=now_utc(),valid_until='2027-01-01T00:00:00Z',decision='QUALIFIED',reviewer='fixture',
        reason='engineering fixture only',evidence_type='test',
        evidence_files={name:hashlib.sha256((directory/name).read_bytes()).hexdigest()
                        for name in ('observation.json','raw-provider.txt')})
    body.update(changes)
    return contract,item,body,directory


def test_missing_or_test_greek_cannot_qualify_open(ledger,tmp_path):
    contract,item,body,directory=proof(ledger,tmp_path)
    assert assess(ledger,item,contract,now_utc())['checks']==['GREEK_QUALIFICATION_REQUIRED']
    registered=register(ledger,body,directory)
    qualified=assess(ledger,{**item,'qualification_id':registered['qualification_id']},contract,now_utc())
    assert qualified['checks']==['GREEK_NOT_QUALIFIED'] and not qualified['executable']
    risk={'environment':'paper','account':{'option_positions':{contract.contract_id:'2'}},'greek_qualification':{contract.contract_id:qualified},'status':'COMPLETE'}
    with pytest.raises(QuantError) as exc:require_operation_risk(risk,'OPEN')
    assert exc.value.code=='GREEK_QUALIFICATION_REQUIRED'
    risk['greek_qualification']={contract.contract_id:'untrusted-status'}
    with pytest.raises(QuantError) as exc:require_operation_risk(risk,'OPEN')
    assert exc.value.code=='GREEK_QUALIFICATION_REQUIRED'
    assert ledger.sequence('sample')==0


def test_exact_actual_typed_fixture_latest_decision_and_files(ledger,tmp_path):
    contract,item,body,directory=proof(ledger,tmp_path,evidence_type='actual')
    first=register(ledger,body,directory);at=now_utc();bound={**item,'qualification_id':first['qualification_id']}
    result=assess(ledger,bound,contract,at)
    assert result['status']=='QUALIFIED' and not result['executable']
    require_operation_risk({'environment':'paper','account':{'option_positions':{contract.contract_id:'2'}},
        'greek_qualification':{contract.contract_id:result},'status':'COMPLETE'},'OPEN')
    candidate={'spec':{'mode':'beta_target'},'selection':{'legs':[{'contract':contract.content()}]},
               'candidate_inputs':{'greeks':[bound]}}
    assert assess_candidate(ledger,candidate,at)[contract.version_hash]==result
    assert 'GREEK_OBSERVATION_MISMATCH' in assess(ledger,{**bound,'value':'-0.6'},contract,at)['checks']
    assert 'SOURCE_NOT_KNOWN' in assess(ledger,bound,contract,'2026-10-09T19:46:00Z')['checks']
    register(ledger,{**body,'decision':'REJECTED','reason':'fixture revoked'},directory)
    assert 'GREEK_SUPERSEDED' in assess(ledger,bound,contract,now_utc())['checks']
    (ledger.path.parent/'qualifications'/first['qualification_id']/'raw-provider.txt').write_text('tampered')
    assert 'CORRUPT_SOURCE_EVIDENCE' in assess(ledger,bound,contract,now_utc())['checks']


def test_model_and_wrong_observation_file_are_rejected(ledger,tmp_path):
    contract,item,body,directory=proof(ledger,tmp_path)
    with pytest.raises(QuantError) as exc:register(ledger,{**body,'observation':{**item,'data_type':'model','model_inputs':{'iv':.2}}},directory)
    assert exc.value.code=='INVALID_GREEK_EVIDENCE'
    (directory/'observation.json').write_text(json.dumps({**item,'value':'-0.6'}))
    with pytest.raises(QuantError) as exc:register(ledger,body,directory)
    assert exc.value.code=='GREEK_OBSERVATION_MISMATCH'


def test_candidate_requires_each_leg_and_qualification(ledger,tmp_path):
    contract,item,body,directory=proof(ledger,tmp_path)
    candidate={'spec':{'mode':'beta_target'},'selection':{'legs':[{'contract':contract.content()}]},
               'candidate_inputs':{'greeks':[]}}
    with pytest.raises(QuantError) as exc:assess_candidate(ledger,candidate,now_utc())
    assert exc.value.code=='GREEK_QUALIFICATION_REQUIRED'
    candidate['candidate_inputs']['greeks']=[item]
    assert assess_candidate(ledger,candidate,now_utc())[contract.version_hash]['status']=='UNQUALIFIED'
    candidate['spec']['mode']='share_protection'
    assert assess_candidate(ledger,candidate,now_utc())=={}


def test_paper_rejects_test_evidence_and_requires_real_contract_file(tmp_path):
    book=Ledger(tmp_path/'paper/account.sqlite','paper');book.account('sample')
    try:
        contract,item,body,directory=proof(book,tmp_path)
        with pytest.raises(QuantError) as exc:register(book,body,directory)
        assert exc.value.code=='TEST_EVIDENCE_FORBIDDEN'
        actual=register(book,{**body,'evidence_type':'actual'},directory)
        out=assess(book,{**item,'qualification_id':actual['qualification_id']},contract,now_utc())
        assert out['status']=='UNQUALIFIED' and 'OPTION_CONTRACT_EVIDENCE_REQUIRED' in out['checks']
        raw=b'ISOLATED TEST: fabricated contract terms, not an exchange record'
        evidence_hash=hashlib.sha256(raw).hexdigest()
        contract=OptionContract.from_dict({**contract.content(),'evidence_hash':evidence_hash})
        item={**item,'contract_version':contract.version_hash}
        (directory/'observation.json').write_text(json.dumps(item))
        body={**body,'evidence_type':'actual','contract':contract.content(),'observation':item,
              'series_id':series_id(item['source'],contract.version_hash),
              'evidence_files':{name:hashlib.sha256((directory/name).read_bytes()).hexdigest()
                                for name in ('observation.json','raw-provider.txt')}}
        target=book.path.parent/'options/contract-evidence'/evidence_hash;target.parent.mkdir(parents=True);target.write_bytes(raw)
        bound=register(book,body,directory)
        assert assess(book,{**item,'qualification_id':bound['qualification_id']},contract,now_utc())['status']=='QUALIFIED'
        target.write_text('changed')
        assert 'OPTION_CONTRACT_EVIDENCE_REQUIRED' in assess(book,{**item,'qualification_id':bound['qualification_id']},contract,now_utc())['checks']
    finally:book.close()
