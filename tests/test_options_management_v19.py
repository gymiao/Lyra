from datetime import timedelta
import json
import pandas as pd
import pytest
from personal_quant.common import canonical,utc
from personal_quant.options.management import preview_exit,exit_due_at
from personal_quant.options.data import OptionDataStore
from personal_quant.options.contracts import OptionContract
from personal_quant.options.ledger import register_contract
from test_options_ledger_v19 import contract,option_event
from test_options_lifecycle_v19 import plan
from test_options_data_v19 import sample
from conftest import event


def setup_exit(book,tmp_path,short=False,cash=1000):
    c=contract(book);identity=plan(book,c,2)
    if short:
        body=json.loads(book.connection.execute('SELECT payload FROM option_plans').fetchone()[0])
        body['sizing']['lines'][0]['side']='SELL'
        book.connection.execute('UPDATE option_plans SET payload=?',(canonical(body),))
    book.import_events('sample',[event('capital','DEPOSIT',amount=cash),dict(option_event('open','OPTION_TRADE',c,
        action='OPEN',trade_side='SELL' if short else 'BUY',price=2,plan_id=identity),quantity=2)])
    record=sample()[1];record.update(contract_id=c.contract_id,contract_version=c.version_hash)
    store=OptionDataStore(tmp_path/'chains');snapshot=store.save([c],pd.DataFrame([record]),sample()[2])['snapshot_id']
    # Pre-settlement independent cash is the original deposit; trade-date equity
    # includes the 400 premium flow and two 205 mid-price option values.
    book.reconcile('sample',{'account_id':'sample','currency':'USD','as_of':'2026-10-09T19:45:10Z',
        'cash_basis':'settled','cash':cash,'positions':{},'option_positions':{c.contract_id:'-2' if short else '2'},
        'equity':cash-10 if short else cash+10},{c.contract_id:2.05})
    request={'plan_id':identity,'as_of':'2026-10-09T19:46:00Z','snapshot_id':snapshot,'trigger':'RISK_REDUCTION',
        'exit_days':7,'fee_per_contract':2,'max_age_seconds':900,'max_underlying_skew_seconds':10,
        'max_spread_fraction':.2,'max_leg_skew_seconds':10,'max_underlying_price_fraction':.01,'reconciliation_max_days':1}
    return c,store,request


def test_long_exit_is_quote_based_read_only_and_idempotent(ledger,tmp_path):
    c,store,request=setup_exit(ledger,tmp_path)
    before=ledger.connection.execute('SELECT payload FROM option_plans').fetchone()[0]
    result=preview_exit(ledger,store,request)
    assert result['status']=='CHECKED' and not result['executable']
    line=result['lines'][0]
    assert line['side']=='SELL' and line['action']=='CLOSE' and line['contracts']=='2'
    assert line['reference_price']=='2' and line['gross_amount']=='400' and line['estimated_fee']=='4'
    assert result['required_buy_cash']=='0'
    assert preview_exit(ledger,store,request)==result
    assert ledger.sequence('sample')==2
    assert ledger.connection.execute('SELECT payload FROM option_plans').fetchone()[0]==before
    assert ledger.connection.execute('SELECT count(*) FROM tasks').fetchone()[0]==0


def test_not_due_does_not_create_trade_or_require_future_quote(ledger,tmp_path):
    c,store,request=setup_exit(ledger,tmp_path)
    result=preview_exit(ledger,store,{**request,'trigger':'EXPIRY_WINDOW','snapshot_id':'not-downloaded'})
    assert result['status']=='NOT_DUE' and result['lines']==[]
    assert result['due_at']=='2026-12-11T20:40:00+00:00'
    assert ledger.sequence('sample')==2


def test_short_exit_budget_is_conditional_and_does_not_release_collateral_early(ledger,tmp_path):
    c,store,request=setup_exit(ledger,tmp_path,short=True,cash=20000)
    result=preview_exit(ledger,store,request)
    assert result['status']=='CHECKED' and result['conditional_cash_release']=='20000'
    assert result['available_after_short_close']=='20000'
    assert result['required_buy_cash']=='424.0'
    assert result['lines'][0]['side']=='BUY' and result['lines'][0]['contracts']=='2'
    assert result['account_basis']['option_cash_collateral']=='20000'
    assert ledger.sequence('sample')==2


@pytest.mark.parametrize('change,code',[
    ({'received_at':'2026-10-09T19:47:00Z'},'MISSING_EXIT_QUOTE'),
    ({'ask_size':1},'INSUFFICIENT_EXIT_QUOTE_SIZE'),
    ({'underlying_timestamp':'2026-10-09T18:00:00Z'},'UNDERLYING_TIME_MISMATCH')])
def test_exit_bad_or_future_quote_blocks(ledger,tmp_path,change,code):
    c,store,request=setup_exit(ledger,tmp_path,short=True,cash=30000)
    contracts,rows,meta,_=store.load(request['snapshot_id']);rows[0].update(change)
    request['snapshot_id']=store.save(list(contracts.values()),pd.DataFrame(rows),meta)['snapshot_id']
    result=preview_exit(ledger,store,request)
    assert result['status']=='BLOCKED' and any(code in issue for issue in result['checks'])
    assert ledger.sequence('sample')==2


def test_due_date_moves_to_prior_session_and_respects_half_day():
    body=sample()[0].content()
    # Dec 1 expiry minus seven days is Sunday Nov 24: use Friday Nov 22.
    c=OptionContract.from_dict({**body,'expiry':'2024-12-01','listed_at':'2024-01-01T14:30:00Z',
        'last_trade_at':'2024-11-29T18:00:00Z','exercise_cutoff_at':'2024-12-01T22:30:00Z'})
    assert exit_due_at(c,7).isoformat()=='2024-11-22T20:40:00+00:00'
    half=OptionContract.from_dict({**c.content(),'expiry':'2024-12-06','last_trade_at':'2024-12-06T21:00:00Z','exercise_cutoff_at':'2024-12-06T22:30:00Z'})
    assert exit_due_at(half,7).isoformat()=='2024-11-29T17:40:00+00:00'


def test_collar_exit_requires_short_close_before_protection_sale_and_sync_quotes(ledger,tmp_path):
    c,store,request=setup_exit(ledger,tmp_path,cash=40000)
    short=register_contract(ledger,{**c.content(),'contract_id':'SPY-20261218-C110-v1','right':'CALL','strike':'110','exercise_cash':'11000'})
    body=json.loads(ledger.connection.execute('SELECT payload FROM option_plans').fetchone()[0])
    body['selection']['legs'].append({'contract':short.content()})
    body['sizing']['lines'].append({'contract_id':short.contract_id,'contract_version':short.version_hash,'side':'SELL','contracts':'2'})
    ledger.connection.execute('UPDATE option_plans SET payload=?',(canonical(body),))
    ledger.import_events('sample',[event('stock','BUY',symbol='SPY',quantity=200,price=100,settlement_at='2024-07-02T20:00:00Z'),
        dict(option_event('short','OPTION_TRADE',short,action='OPEN',trade_side='SELL',price=3,plan_id=request['plan_id']),quantity=2)])
    contracts,rows,meta,_=store.load(request['snapshot_id'])
    row={**rows[0],'contract_id':short.contract_id,'contract_version':short.version_hash,'bid':'3','ask':'3.1'}
    request['snapshot_id']=store.save([c,short],pd.DataFrame(rows+[row]),meta)['snapshot_id']
    ledger.reconcile('sample',{'account_id':'sample','currency':'USD','as_of':'2026-10-09T19:45:10Z',
        'cash_basis':'settled','cash':20000,'positions':{'SPY':200},'option_positions':{c.contract_id:2,short.contract_id:-2},
        'equity':40000},{c.contract_id:2.05,short.contract_id:3.05,'SPY':100})
    result=preview_exit(ledger,store,request)
    assert result['status']=='CHECKED'
    assert [line['contract_id'] for line in result['lines']]==[short.contract_id,c.contract_id]
    assert result['lines'][0]['depends_on']==[]
    assert result['lines'][1]['depends_on']==[short.contract_id]
    assert result['required_buy_cash']=='624.0'
    row.update(exchange_timestamp='2026-10-09T19:45:20Z',underlying_timestamp='2026-10-09T19:45:20Z',available_at='2026-10-09T19:45:22Z',received_at='2026-10-09T19:45:24Z')
    request['snapshot_id']=store.save([c,short],pd.DataFrame(rows+[row]),meta)['snapshot_id']
    assert 'EXIT_LEG_TIME_MISMATCH' in preview_exit(ledger,store,request)['checks']
    assert ledger.sequence('sample')==4


def test_exit_insufficient_actual_cash_is_blocked_without_sale_credit(ledger,tmp_path):
    c,store,request=setup_exit(ledger,tmp_path,short=True,cash=100)
    result=preview_exit(ledger,store,request)
    assert result['status']=='BLOCKED' and 'INSUFFICIENT_EXIT_CASH' in result['checks']
    assert result['required_buy_cash']=='424.0' and result['available_after_short_close']=='100'
    assert result['account_basis']['option_cash_collateral']=='20000'
    assert ledger.sequence('sample')==2


def test_exit_cash_release_excludes_other_positions_in_same_contract(ledger,tmp_path):
    c,store,request=setup_exit(ledger,tmp_path,short=True,cash=30000)
    ledger.import_events('sample',[option_event('other-short','OPTION_TRADE',c,action='OPEN',trade_side='SELL',price=2)])
    ledger.reconcile('sample',{'account_id':'sample','currency':'USD','as_of':'2026-10-09T19:45:10Z',
        'cash_basis':'settled','cash':30000,'positions':{},'option_positions':{c.contract_id:-3},'equity':29985},{c.contract_id:2.05})
    result=preview_exit(ledger,store,request)
    assert result['status']=='CHECKED' and result['lines'][0]['contracts']=='2'
    assert result['conditional_cash_release']=='20000' and result['available_after_short_close']=='20000'
    assert result['account_basis']['option_cash_collateral']=='30000'
    assert ledger.snapshot('sample',request['as_of'],{c.contract_id:2.05})['reserved_cash']=='30000'
    assert ledger.sequence('sample')==3
