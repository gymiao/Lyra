import json
import shutil
from pathlib import Path
import pandas as pd
import pytest
from personal_quant.common import QuantError
from personal_quant.data.store import DataStore
from personal_quant.hedging.archive import publish,load,validate_references
from personal_quant.hedging.service import exposure
from personal_quant.options.data import OptionDataStore
from personal_quant.options.ledger import register_contract
from personal_quant.options.valuation import quote_set as option_quotes
from personal_quant.portfolio import Ledger
from personal_quant.portfolio.backup import create_bundle,verify_bundle,restore_bundle
from test_hedging_exposure_v19 import risk_market
from test_options_data_v19 import sample
from test_options_ledger_v19 import contract
from conftest import event


@pytest.fixture
def frozen_risk(risk_market,config,tmp_path,monkeypatch):
    _,frame,_,calendar=risk_market;monkeypatch.chdir(tmp_path)
    root=tmp_path/'runtime/demo';store=DataStore(root/'data');metadata=store.save(frame,calendar)
    book=Ledger(root/'account.sqlite','demo');book.account('sample')
    book.import_events('sample',[event('deposit','DEPOSIT',amount=30000),
        event('stock','BUY',symbol='SPY',quantity=100,price=100,settlement_at='2024-07-02T20:00:00Z')])
    clock=(calendar.close(calendar.sessions[-1])+pd.Timedelta(minutes=30)).isoformat()
    request={'schema_version':1,'as_of':clock,'knowledge_cutoff':clock,'ledger_seq':2,'ledger_view':'restated',
        'valuation_snapshot_id':metadata['snapshot_id'],'return_snapshot_id':metadata['snapshot_id'],
        'benchmark':'GLD','window':126,'min_r2':.9,'max_standard_error':.1,'max_mark_skew_seconds':120,
        'max_greek_age_seconds':3600,'greeks':[],'option_valuation':None}
    try:yield book,config,store,request,calendar
    finally:book.close()


def test_publish_repeat_future_facts_preserve_archive_and_full_restore(frozen_risk,tmp_path):
    book,config,store,request,_=frozen_risk
    result=publish(book,config,store,'sample',request)
    assert publish(book,config,store,'sample',request)==result
    root=book.path.parent/'hedging/exposures';body=load(root,result['exposure_id'])
    before=(root/result['exposure_id']/'exposure.json').read_bytes()
    assert float(body['risk']['beta_amount'])==pytest.approx(5000) and float(body['risk']['account_beta'])==pytest.approx(1/6)
    book.import_events('sample',[event('late-capital','DEPOSIT',amount=10000)])
    assert load(root,result['exposure_id'])==body and (root/result['exposure_id']/'exposure.json').read_bytes()==before
    validate_references(book.path.parent,book)
    cfg=tmp_path/'demo.toml';cfg.write_bytes((Path(__file__).resolve().parents[1]/'configs/demo.toml').read_bytes())
    create_bundle(book.path.parent,cfg,tmp_path/'bundle');verify_bundle(tmp_path/'bundle','demo')
    restore_bundle(tmp_path/'bundle',tmp_path/'restored','demo')
    restored=Ledger(tmp_path/'restored/runtime/demo/account.sqlite','demo')
    try:
        assert load(restored.path.parent/'hedging/exposures',result['exposure_id'])==body
        validate_references(restored.path.parent,restored)
        assert restored.sequence('sample')==3
    finally:restored.close()


def test_archive_tampering_missing_price_and_wrong_ledger_are_rejected(frozen_risk):
    book,config,store,request,_=frozen_risk;result=publish(book,config,store,'sample',request)
    root=book.path.parent/'hedging/exposures';file=root/result['exposure_id']/'exposure.json'
    original=file.read_bytes();body=json.loads(original);body['risk']['beta_amount']='0';file.write_text(json.dumps(body))
    with pytest.raises(QuantError,match='哈希'):load(root,result['exposure_id'])
    file.write_bytes(original)
    recorded=book.connection.execute("SELECT recorded_at FROM events WHERE event_id='stock'").fetchone()[0]
    book.connection.execute("UPDATE events SET recorded_at='2026-01-01T00:00:00Z' WHERE event_id='stock'")
    with pytest.raises(QuantError,match='账本前缀'):validate_references(book.path.parent,book)
    book.connection.execute("UPDATE events SET recorded_at=? WHERE event_id='stock'",(recorded,))
    validate_references(book.path.parent,book)
    missing=store.root/request['return_snapshot_id'];shutil.rmtree(missing)
    with pytest.raises(QuantError):validate_references(book.path.parent,book)


def test_historical_option_prefix_uses_old_holdings_and_greek_quantity(frozen_risk):
    book,config,store,request,calendar=frozen_risk
    original=contract(book,'PUT',100);body=original.content()
    body.update(contract_id='SPY-P100-20250130',listed_at='2024-01-01T00:00:00Z',expiry='2025-01-30',
                last_trade_at='2025-01-30T21:00:00Z',exercise_cutoff_at='2025-01-30T22:30:00Z')
    c=register_contract(book,body);close=calendar.close(calendar.sessions[-1]).isoformat()
    book.import_events('sample',[event('put-open','OPTION_TRADE',contract_version=c.version_hash,quantity=2,
        action='OPEN',trade_side='BUY',price=2,effective_at=close,settlement_at=close)])
    _,row,metadata=sample();row.update(contract_id=c.contract_id,contract_version=c.version_hash,
        exchange_timestamp=close,underlying_timestamp=close,last_timestamp=close,
        available_at=(pd.Timestamp(close)+pd.Timedelta(seconds=2)).isoformat(),
        received_at=(pd.Timestamp(close)+pd.Timedelta(seconds=4)).isoformat(),open_interest_available_at=close)
    options=OptionDataStore(book.path.parent/'options/chains');snapshot=options.save([c],pd.DataFrame([row]),metadata)['snapshot_id']
    limits={'max_age_seconds':3600,'max_underlying_skew_seconds':10,'max_spread_fraction':.2,'max_leg_skew_seconds':10}
    greek={'contract_version':c.version_hash,'unit':'position_total','value':-100,'signed_contracts':2,
        'source':'synthetic_reference','data_type':'synthetic','as_of':close,'available_at':row['available_at'],
        'received_at':row['received_at'],'model_inputs':{}}
    request={**request,'ledger_seq':3,'greeks':[greek],'option_valuation':{'snapshot_id':snapshot,'limits':limits}}
    book.import_events('sample',[event('put-close','OPTION_TRADE',contract_version=c.version_hash,quantity=2,
        action='CLOSE',trade_side='SELL',price=2,effective_at=(pd.Timestamp(close)+pd.Timedelta(minutes=15)).isoformat(),settlement_at=request['as_of'])])
    assert option_quotes(book,'sample',options,snapshot,request['as_of'],limits)['status']=='NO_OPTION_POSITIONS'
    historic=option_quotes(book,'sample',options,snapshot,request['as_of'],limits,ledger_seq=3)
    assert historic['status']=='COMPLETE' and historic['ledger_seq']==3
    result=exposure(book,config,store,'sample',request)
    assert result['status']=='COMPLETE' and result['account']['option_positions']=={c.contract_id:'2'}
    assert float(result['account']['equity'])==pytest.approx(30010) and float(result['risk']['beta_amount'])==pytest.approx(0,abs=1e-6)
    frozen=publish(book,config,store,'sample',request);validate_references(book.path.parent,book)
    assert load(book.path.parent/'hedging/exposures',frozen['exposure_id'])['option_valuation']['ledger_seq']==3
    with pytest.raises(QuantError,match='序号'):option_quotes(book,'sample',options,snapshot,request['as_of'],limits,ledger_seq=99)
