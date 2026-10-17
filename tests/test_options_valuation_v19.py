import hashlib
import json
from pathlib import Path
import pandas as pd
import pytest

from personal_quant.common import QuantError
from personal_quant.config import Config
from personal_quant.options.data import OptionDataStore
from personal_quant.options.source import register_source, assess_source, series_id
from personal_quant.options.valuation import quote_set
from personal_quant.portfolio import Ledger
from personal_quant.portfolio.report import report_from_store, load_account_report
from personal_quant.portfolio.backup import create_bundle, verify_bundle, restore_bundle
from personal_quant.data.store import DataStore
from test_options_ledger_v19 import contract, option_event
from test_options_data_v19 import sample
from test_options_monthly_replay_v19 import ROOT
from conftest import event

LIMITS={'max_age_seconds':900,'max_underlying_skew_seconds':10,
        'max_spread_fraction':.2,'max_leg_skew_seconds':10}


@pytest.fixture
def account(tmp_path):
    root=tmp_path/'runtime/demo';book=Ledger(root/'account.sqlite','demo');book.account('sample')
    c=contract(book)
    book.import_events('sample',[event('capital','DEPOSIT',amount=10000),
        option_event('short-put','OPTION_TRADE',c,action='OPEN',trade_side='SELL',price=2,fee=2)])
    _,quote,metadata=sample();quote.update(contract_id=c.contract_id,contract_version=c.version_hash)
    store=OptionDataStore(root/'options/chains');snapshot=store.save([c],pd.DataFrame([quote]),metadata)['snapshot_id']
    try:yield book,store,c,quote,metadata,snapshot
    finally:book.close()


def render(account,tmp_path,*,snapshot=None,as_of='2026-10-09T19:46:00Z'):
    book,store,_,_,_,identity=account
    return report_from_store(book,'sample',as_of,DataStore(book.path.parent/'data'),Config.load(ROOT/'configs/demo.toml'),
        book.path.parent/'reports/account-latest',option_valuation={'snapshot_id':snapshot or identity,'limits':LIMITS})


def test_option_mid_is_multiplied_once_and_external_capital_is_not_profit(account,tmp_path):
    book,store,c,_,_,identity=account
    q=quote_set(book,'sample',store,identity,'2026-10-09T19:46:00Z',LIMITS)
    assert q['status']=='COMPLETE' and q['prices']=={c.contract_id:'2.05'}
    result=render(account,tmp_path)
    # 10000 capital + 200 premium - 2 fee - 205 short liability = 9993.
    assert result['equity']=='9993.00' and result['investment_pnl']=='-7.00'
    assert result['option_market_value']=='-205.00' and result['option_cash_collateral']=='10000'
    assert result['valuation']['status']=='COMPLETE'
    assert result['valuation']['options']['source_assessment']['actual_source_qualified'] is False
    assert result['environment']=='demo' and book.sequence('sample')==2
    assert render(account,tmp_path)==result and load_account_report(book.path.parent/'reports/account-latest')==result
    book.import_events('sample',[event('extra','DEPOSIT',amount=1000,effective_at='2026-10-09T19:46:30Z')])
    changed=render(account,tmp_path,as_of='2026-10-09T19:47:00Z')
    assert float(changed['equity'])==10993 and float(changed['investment_pnl'])==-7


@pytest.mark.parametrize('problem',['late','stale','version','wide'])
def test_bad_option_marks_never_publish_complete_equity(account,tmp_path,problem):
    book,store,c,quote,metadata,_=account;clock='2026-10-09T19:46:00Z'
    if problem=='late':quote['received_at']='2026-10-09T20:00:00Z'
    if problem=='stale':clock='2026-10-09T20:01:00Z'
    if problem=='version':
        from personal_quant.options.contracts import OptionContract
        c=OptionContract.from_dict({**c.content(),'revision':'revised'});quote['contract_version']=c.version_hash
    if problem=='wide':quote['ask']=4
    identity=store.save([c],pd.DataFrame([quote]),metadata)['snapshot_id']
    report=render(account,tmp_path,snapshot=identity,as_of=clock)
    assert report['equity'] is None and report['valuation']['status']=='INCOMPLETE'
    assert report['valuation']['options']['prices']=={}
    assert report['missing_prices'] and book.sequence('sample')==2


def test_missing_option_request_is_not_cash_only(account,tmp_path):
    book,*_=account
    report=report_from_store(book,'sample','2026-10-09T19:46:00Z',DataStore(book.path.parent/'data'),
                             Config.load(ROOT/'configs/demo.toml'),tmp_path/'missing')
    assert report['equity'] is None and report['valuation']['status']=='INCOMPLETE'
    assert report['valuation']['options']['checks']==['OPTION_VALUATION_REQUEST_REQUIRED']


def test_daily_values_and_reconciles_options_without_new_facts(account,tmp_path,monkeypatch):
    from personal_quant.execution.daily import DailyRunner
    monkeypatch.chdir(tmp_path);book,_,c,_,_,identity=account
    config=Config.load(ROOT/'configs/demo.toml')
    expected={'account_id':'sample','currency':'USD','as_of':'2026-10-09T19:46:00Z','cash_basis':'settled',
              'cash':10000,'positions':{},'option_positions':{c.contract_id:-1},'equity':9993}
    inputs={'snapshot_id':identity,'limits':LIMITS}
    runner=DailyRunner(book,config,DataStore(book.path.parent/'data'))
    first=runner.run('sample',as_of=expected['as_of'],reconciliation=expected,option_valuation=inputs)
    assert first['reconciliation']['status']=='PASSED' and float(first['equity'])==9993
    assert first['option_valuation']['status']=='COMPLETE'
    # Missing underlying strategy data still blocks planning; valid option
    # marks do not silently qualify the entire daily workflow.
    assert first['status']=='BLOCKED' and book.sequence('sample')==2
    again=runner.run('sample',as_of=expected['as_of'],reconciliation=expected,option_valuation=inputs)
    assert again['report_id']==first['report_id'] and book.sequence('sample')==2
    incomplete=runner.run('sample',as_of=expected['as_of'])
    assert incomplete['valuation']=='INCOMPLETE' and incomplete['equity'] is None


def source_body(tmp_path,c,metadata):
    evidence=tmp_path/'evidence';evidence.mkdir()
    file=evidence/'fixture.txt';file.write_text('TEST ONLY: review-schema mechanics; not genuine provider permission')
    return {'schema_version':2,'asset_type':'OPTION_QUOTES','series_id':series_id(metadata['source']),
            'source':metadata['source'],'market':'OPRA','currency':'USD','timezone':'America/New_York',
            'price_basis':'premium_per_quote_unit','scope_contract_versions':[c.version_hash],
            'quote_convention':'TEST bid ask per quote unit','time_convention':'TEST available and received UTC',
            'corporate_actions':'TEST versioned standard contract','license_terms':'TEST local only',
            'reviewed_at':'2024-01-01T00:00:00Z','valid_until':'2027-01-01T00:00:00Z',
            'decision':'QUALIFIED','reviewer':'test-schema-only','reason':'TEST not actual source validation',
            'evidence_type':'test','evidence_files':{'fixture.txt':hashlib.sha256(file.read_bytes()).hexdigest()}},evidence


def test_real_label_and_test_review_cannot_grant_option_source(account,tmp_path):
    book,store,c,quote,metadata,_=account;metadata={**metadata,'data_type':'real_market'}
    identity=store.save([c],pd.DataFrame([quote]),metadata)['snapshot_id']
    first=render(account,tmp_path,snapshot=identity)
    assert first['equity'] is None and first['valuation']['options']['checks']==['OPTION_SOURCE_QUALIFICATION_REQUIRED']
    body,evidence=source_body(tmp_path,c,metadata);register_source(book,body,evidence)
    assert register_source(book,body,evidence)['qualification_id']==register_source(book,body,evidence)['qualification_id']
    result=render(account,tmp_path,snapshot=identity)
    assert result['equity'] is None and 'OPTION_SOURCE_NOT_QUALIFIED' in result['valuation']['options']['checks']
    (evidence/'fixture.txt').write_text('changed')
    with pytest.raises(QuantError,match='哈希'):register_source(book,body,evidence)


def test_declared_review_scope_and_archived_evidence_are_verified(account,tmp_path):
    # Positive protocol branch in a demo-only fixture. No genuine market-data
    # access or permission is asserted by this constructed review declaration.
    book,_,c,_,metadata,_=account;metadata={**metadata,'data_type':'real_market'}
    from personal_quant.options.contracts import OptionContract
    evidence_bytes=b'TEST ONLY contract terms for source-review protocol'
    evidence_hash=hashlib.sha256(evidence_bytes).hexdigest()
    c=OptionContract.from_dict({**c.content(),'evidence_hash':evidence_hash})
    terms=book.path.parent/'options/contract-evidence'/evidence_hash
    terms.parent.mkdir(parents=True);terms.write_bytes(evidence_bytes)
    body,evidence=source_body(tmp_path,c,metadata);body['evidence_type']='actual'
    registered=register_source(book,body,evidence)
    assert assess_source(book,metadata,[c],'2026-10-09T19:46:00Z')['status']=='QUALIFIED'
    different=OptionContract.from_dict({**c.content(),'revision':'different'})
    assert 'OPTION_SOURCE_SCOPE_MISMATCH' in assess_source(book,metadata,[different],'2026-10-09T19:46:00Z')['checks']
    archived=book.path.parent/'qualifications'/registered['qualification_id']/'fixture.txt'
    archived.write_text('changed')
    assert 'CORRUPT_OPTION_SOURCE_EVIDENCE' in assess_source(book,metadata,[c],'2026-10-09T19:46:00Z')['checks']


def test_option_mark_snapshot_and_report_survive_full_backup(account,tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path);book,_,_,_,_,identity=account
    report=render(account,tmp_path)
    config=tmp_path/'demo.toml';config.write_bytes((ROOT/'configs/demo.toml').read_bytes())
    create_bundle(book.path.parent,config,tmp_path/'bundle');verify_bundle(tmp_path/'bundle','demo')
    restore_bundle(tmp_path/'bundle',tmp_path/'recovered','demo')
    restored=load_account_report(tmp_path/'recovered/runtime/demo/reports/account-latest')
    assert restored==report and restored['valuation']['options']['snapshot_id']==identity
    # A report's exact chain is required independently of generic ETF snapshots.
    (tmp_path/'bundle/runtime/demo/options/chains'/identity/'chain.json').unlink()
    with pytest.raises(QuantError):verify_bundle(tmp_path/'bundle','demo')


def test_option_valuation_ui_shows_frozen_time_and_synthetic_label(account,tmp_path,monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.chdir(tmp_path);book,*_=account;render(account,tmp_path)
    count=book.sequence('sample');script=tmp_path/'valuation_ui.py'
    script.write_text('''from pathlib import Path
from personal_quant.config import Config
from personal_quant.portfolio import Ledger
from personal_quant.ui.v19 import controls
config_path=Path(__CONFIG_PATH__)
book=Ledger('runtime/demo/account.sqlite','demo')
try: controls(book,Config.load(config_path),config_path,'账户总览','2026-10-09T19:46:00Z')
finally: book.close()
'''.replace('__CONFIG_PATH__',repr(str(Path(__file__).resolve().parents[1]/'configs/demo.toml'))))
    app=AppTest.from_file(str(script)).run(timeout=30)
    assert not app.exception and not app.error
    assert any('合成报价' in caption.value and '报告截至' in caption.value for caption in app.caption)
    assert app.dataframe and book.sequence('sample')==count
