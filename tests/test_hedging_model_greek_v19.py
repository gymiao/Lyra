"""Model input proofs are fabricated fixtures; analytic expectations are independent."""
from copy import deepcopy
from datetime import date
import hashlib
import json
import math
from pathlib import Path

import pytest

from personal_quant.common import QuantError, digest, now_utc
from personal_quant.hedging.greek_evidence import register, assess
from personal_quant.hedging.exposure import normalize_delta
from personal_quant.options import pricing
from personal_quant.options.contracts import OptionContract
from personal_quant.portfolio import Ledger
from personal_quant.portfolio.backup import create_bundle, restore_bundle
from personal_quant.portfolio.schema import apply_workbench_schema, apply_v18_schema, apply_v19_schema
from test_options_data_v19 import sample


def model_proof(book, tmp_path, *, evidence_type='test', quantity=2):
    with book.transaction():
        apply_workbench_schema(book.connection);apply_v18_schema(book.connection);apply_v19_schema(book.connection)
    contract=OptionContract.from_dict({**sample()[0].content(),'style':'EUROPEAN'})
    args=dict(right='CALL',style='EUROPEAN',spot=100,strike=100,valuation_date='2026-10-09',
              expiry=contract.expiry,volatility=.2,rate=.04,dividend_yield=.01,multiplier=100,
              contracts=quantity,market_price=None,discrete_dividends=None)
    result=pricing.price(**args)
    t=(date.fromisoformat(contract.expiry)-date(2026,10,9)).days/365
    d1=(.04-.01+.2**2/2)*t/(.2*math.sqrt(t))
    expected=100*quantity*math.exp(-.01*t)*(.5+.5*math.erf(d1/math.sqrt(2)))
    observations={name:dict(value=args[name],source='ISOLATED TEST INPUT',
        as_of='2026-10-09T19:45:00Z',available_at='2026-10-09T19:45:02Z',
        received_at='2026-10-09T19:45:04Z',max_age_seconds=60,
        data_type='real_market' if evidence_type=='actual' else 'synthetic',raw_file='raw-inputs.txt')
        for name in ('spot','volatility','rate','dividend_yield','discrete_dividends')}
    inputs=dict(pricing=args,model=result['model'],engine=result['engine'],model_version=result['model_version'],
        pricing_source_hash=hashlib.sha256(Path(pricing.__file__).read_bytes()).hexdigest(),input_observations=observations)
    item=dict(contract_version=contract.version_hash,unit='position_total',value=str(expected),signed_contracts=quantity,
        source='QuantLib explicit fixture inputs',data_type='model',as_of='2026-10-09T19:45:00Z',
        available_at='2026-10-09T19:45:04Z',received_at='2026-10-09T19:45:05Z',model_inputs=inputs)
    directory=tmp_path/'model-proof';directory.mkdir()
    (directory/'raw-inputs.txt').write_text('FABRICATED ENGINEERING INPUTS; NO VENDOR ACCESS')
    body=dict(schema_version=2,asset_type='OPTION_MODEL_GREEK_OBSERVATION',
        series_id='option-model-greek:'+digest({'source':item['source'],'contract_version':contract.version_hash}),
        contract=contract.content(),observation=item,reviewed_at=now_utc(),valid_until='2027-01-01T00:00:00Z',
        decision='QUALIFIED',reviewer='fixture',reason='isolated model-input verification',
        evidence_type=evidence_type,evidence_files={})
    reseal(body,directory)
    return contract,item,body,directory,expected


def reseal(body,directory):
    (directory/'observation.json').write_text(json.dumps(body['observation']))
    (directory/'model-inputs.json').write_text(json.dumps(body['observation']['model_inputs']))
    body['evidence_files']={name:hashlib.sha256((directory/name).read_bytes()).hexdigest()
        for name in ('observation.json','model-inputs.json','raw-inputs.txt')}


@pytest.mark.parametrize('quantity',[2,-2])
def test_qualified_model_is_recomputed_and_normalized_once(ledger,tmp_path,quantity):
    contract,item,body,directory,expected=model_proof(ledger,tmp_path,evidence_type='actual',quantity=quantity)
    registered=register(ledger,body,directory)
    bound={**item,'qualification_id':registered['qualification_id']}
    assert assess(ledger,bound,contract,now_utc())['status']=='QUALIFIED'
    delta=normalize_delta(bound,contract,quantity,item['as_of'],item['received_at'],0)
    assert float(delta['delta_shares'])==pytest.approx(expected,abs=1e-8)
    assert ledger.sequence('sample')==0
    forged={**bound,'value':str(expected+1)}
    assert assess(ledger,forged,contract,now_utc())['status']=='UNQUALIFIED'
    archived=ledger.path.parent/'qualifications'/registered['qualification_id']/'raw-inputs.txt'
    archived.write_text('changed')
    assert 'CORRUPT_SOURCE_EVIDENCE' in assess(ledger,bound,contract,now_utc())['checks']


@pytest.mark.parametrize('change', ['delta','future','missing','multiplier','source_hash','model_version','stale','synthetic_actual'])
def test_incomplete_future_or_irreproducible_model_is_rejected(ledger,tmp_path,change):
    _,_,body,directory,_=model_proof(ledger,tmp_path,evidence_type='actual')
    body=deepcopy(body);item=body['observation'];inputs=item['model_inputs']
    if change=='delta':item['value']=str(float(item['value'])+1)
    elif change=='future':inputs['input_observations']['volatility']['available_at']='2026-10-09T20:00:00Z'
    elif change=='missing':del inputs['input_observations']['rate']
    elif change=='multiplier':inputs['pricing']['multiplier']=200
    elif change=='source_hash':inputs['pricing_source_hash']='0'*64
    elif change=='model_version':inputs['model_version']='unverified-version'
    elif change=='stale':inputs['input_observations']['rate'].update(as_of='2026-10-09T19:40:00Z',max_age_seconds=60)
    else:inputs['input_observations']['volatility']['data_type']='synthetic'
    reseal(body,directory)
    with pytest.raises(QuantError) as exc:register(ledger,body,directory)
    assert exc.value.code in {'INVALID_MODEL_GREEK_INPUT','MODEL_GREEK_MISMATCH'}


def test_test_inputs_remain_unqualified(ledger,tmp_path):
    contract,item,body,directory,_=model_proof(ledger,tmp_path)
    registered=register(ledger,body,directory)
    result=assess(ledger,{**item,'qualification_id':registered['qualification_id']},contract,now_utc())
    assert result['status']=='UNQUALIFIED' and 'GREEK_NOT_QUALIFIED' in result['checks']


def test_model_delta_requires_same_frozen_underlying_mark(ledger,tmp_path):
    from personal_quant.hedging.model_greek import require_mark
    _,item,_,_,_=model_proof(ledger,tmp_path)
    require_mark(item,100,require_complete=True)
    with pytest.raises(QuantError) as exc:require_mark(item,200,require_complete=True)
    assert exc.value.code=='MODEL_GREEK_PRICE_MISMATCH'


def test_model_mark_mismatch_does_not_prevent_required_close():
    from personal_quant.hedging.stage_assessment import require_operation_risk
    risk=dict(environment='paper',status='INCOMPLETE',checks=['MODEL_GREEK_PRICE_MISMATCH:PUT'],
        valuation={'status':'COMPLETE'},option_valuation={'status':'COMPLETE'},
        account=dict(equity='1000',missing_prices=[],anomalies=[],option_positions={'PUT':'1'}))
    require_operation_risk(risk,'CLOSE')
    with pytest.raises(QuantError) as exc:require_operation_risk(risk,'OPEN')
    assert exc.value.code=='GREEK_QUALIFICATION_REQUIRED'


def test_paper_model_requires_contract_evidence_and_survives_restore(tmp_path,monkeypatch):
    book=Ledger(tmp_path/'runtime/paper/account.sqlite','paper');book.account('sample')
    try:
        contract,item,body,directory,_=model_proof(book,tmp_path,evidence_type='actual')
        first=register(book,body,directory)
        check=assess(book,{**item,'qualification_id':first['qualification_id']},contract,now_utc())
        assert 'OPTION_CONTRACT_EVIDENCE_REQUIRED' in check['checks']
        raw=b'FABRICATED CONTRACT UNIT PROOF FOR ISOLATED TEST'
        unit_hash=hashlib.sha256(raw).hexdigest()
        contract=OptionContract.from_dict({**contract.content(),'evidence_hash':unit_hash})
        item={**item,'contract_version':contract.version_hash}
        body.update(contract=contract.content(),observation=item,
            series_id='option-model-greek:'+digest({'source':item['source'],'contract_version':contract.version_hash}))
        reseal(body,directory)
        units=book.path.parent/'options/contract-evidence'/unit_hash;units.parent.mkdir(parents=True);units.write_bytes(raw)
        second=register(book,body,directory);bound={**item,'qualification_id':second['qualification_id']}
        assert assess(book,bound,contract,now_utc())['status']=='QUALIFIED'
        config=tmp_path/'paper.toml';config.write_text((Path(__file__).resolve().parents[1]/'configs/demo.toml').read_text()
            .replace('environment = "demo"','environment = "paper"').replace('runtime_dir = "runtime/demo"','runtime_dir = "runtime/paper"'))
        monkeypatch.chdir(tmp_path)
        create_bundle(book.path.parent,config,tmp_path/'bundle')
        restore_bundle(tmp_path/'bundle',tmp_path/'restored','paper')
        restored=Ledger(tmp_path/'restored/runtime/paper/account.sqlite','paper')
        try:
            assert assess(restored,bound,contract,now_utc())['status']=='QUALIFIED'
            assert restored.sequence('sample')==0
        finally:restored.close()
    finally:book.close()
