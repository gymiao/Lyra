from copy import deepcopy
from datetime import timedelta
import pandas as pd
import pytest
from personal_quant.common import QuantError, utc
from personal_quant.options.contracts import OptionContract
from personal_quant.options.data import OptionDataStore


def sample():
    contract=OptionContract.from_dict({'contract_id':'SPY-20261218-C100-v1','underlying':'SPY','right':'CALL','strike':100,
        'expiry':'2026-12-18','last_trade_at':'2026-12-18T21:00:00Z','exercise_cutoff_at':'2026-12-18T22:30:00Z',
        'listed_at':'2026-01-01T00:00:00Z','style':'AMERICAN','settlement':'PHYSICAL','currency':'USD',
        'quote_multiplier':100,'deliverable_shares':100,'deliverable_cash':0,'exercise_cash':10000,
        'tick_size':.01,'revision':'v1','evidence_hash':'synthetic_test_contract_terms'})
    record={'contract_id':contract.contract_id,'contract_version':contract.version_hash,
        'exchange_timestamp':'2026-10-09T19:45:00Z','available_at':'2026-10-09T19:45:02Z',
        'received_at':'2026-10-09T19:45:04Z','bid':2,'ask':2.1,'bid_size':10,'ask_size':10,
        'last':2.05,'last_timestamp':'2026-10-09T19:44:00Z','volume':100,'open_interest':200,
        'open_interest_available_at':'2026-10-09T12:00:00Z','underlying_price':100,
        'underlying_timestamp':'2026-10-09T19:45:00Z','source':'synthetic_options_v1'}
    metadata={'schema_version':1,'source':'synthetic_options_v1','data_type':'synthetic',
        'license_terms':'local test only','unit_evidence':'synthetic terms, not OCC evidence',
        'available_time_basis':'frozen synthetic timestamps'}
    return contract,record,metadata


def test_csv_dedup_same_snapshot_and_quality_is_not_source_qualification(tmp_path):
    contract,record,metadata=sample();store=OptionDataStore(tmp_path)
    saved=store.save([contract],pd.DataFrame([record,record]),metadata)
    repeated=store.save([contract],pd.DataFrame([record]),metadata)
    assert repeated['snapshot_id']==saved['snapshot_id'] and repeated['status']=='EXISTING'
    result=store.check(saved['snapshot_id'],'2026-10-09T19:46:00Z')
    assert result['checks'][0]['status']=='PASSED'
    assert not result['executable'] and result['source_qualification']=='UNVERIFIED'


@pytest.mark.parametrize('change,issue',[
    ({'bid':3},'INVALID_BID_ASK'),({'ask_size':0},'NO_QUOTED_SIZE'),
    ({'received_at':'2026-10-09T20:00:00Z'},'QUOTE_NOT_YET_AVAILABLE'),
    ({'underlying_timestamp':'2026-10-09T18:45:00Z'},'UNDERLYING_TIME_MISMATCH'),
    ({'ask':2.105},'INVALID_QUOTE_TICK')])
def test_bad_quotes_cannot_become_executable_by_csv_label(tmp_path,change,issue):
    contract,record,metadata=sample();record.update(change)
    store=OptionDataStore(tmp_path);saved=store.save([contract],pd.DataFrame([record]),metadata)
    assert issue in store.check(saved['snapshot_id'],'2026-10-09T19:46:00Z')['checks'][0]['issues']


def test_conflicting_duplicate_and_corruption_are_rejected(tmp_path):
    contract,record,metadata=sample();store=OptionDataStore(tmp_path)
    conflict={**record,'ask':2.2}
    with pytest.raises(QuantError,match='冲突'):store.save([contract],pd.DataFrame([record,conflict]),metadata)
    saved=store.save([contract],pd.DataFrame([record]),metadata)
    path=tmp_path/saved['snapshot_id']/'chain.json';path.write_text(path.read_text().replace('2.1','3.1'))
    with pytest.raises(QuantError,match='改变'):store.load(saved['snapshot_id'])


def test_adjusted_contract_requires_deliverable_support(tmp_path):
    contract,record,metadata=sample();body=contract.content();body['deliverable_cash']='10'
    adjusted=OptionContract.from_dict(body)
    record['contract_version']=adjusted.version_hash
    store=OptionDataStore(tmp_path);saved=store.save([adjusted],pd.DataFrame([record]),metadata)
    assert store.check(saved['snapshot_id'],'2026-10-09T19:46:00Z')['checks'][0]['issues']==['UNSUPPORTED_DELIVERABLE']


def test_frozen_execution_quote_age_and_receipt_have_distinct_clocks():
    from personal_quant.options.data import quality
    contract, record, _ = sample()
    record['available_at'] = record['received_at'] = '2026-10-09T20:00:00Z'
    limits = dict(max_age_seconds=900, max_underlying_skew_seconds=10, max_spread_fraction=.2)
    # A live decision cannot know a later receipt. Replaying the frozen actual
    # quote after receipt is valid; it does not make a live quote fresh again.
    assert 'QUOTE_NOT_YET_AVAILABLE' in quality(record, contract, '2026-10-09T19:45:00Z', **limits)
    assert quality(record, contract, '2026-10-09T19:45:00Z', knowledge_cutoff='2026-10-09T21:00:00Z', **limits) == []
    assert 'STALE_QUOTE' in quality(record, contract, '2026-10-09T21:00:00Z', **limits)
    assert 'QUOTE_NOT_YET_AVAILABLE' in quality(record, contract, '2026-10-09T19:45:00Z', knowledge_cutoff='2026-10-09T19:59:59Z', **limits)
    future = {**record, 'exchange_timestamp':'2026-10-09T19:46:00Z', 'underlying_timestamp':'2026-10-09T19:46:00Z'}
    assert 'QUOTE_NOT_YET_AVAILABLE' in quality(future, contract, '2026-10-09T19:45:00Z', knowledge_cutoff='2026-10-09T21:00:00Z', **limits)
    with pytest.raises(QuantError, match='不能早于'):
        quality(record, contract, '2026-10-09T19:45:00Z', knowledge_cutoff='2026-10-09T19:44:59Z', **limits)
