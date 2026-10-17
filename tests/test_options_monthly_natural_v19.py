from native_tools import native_engine_root,native_dotnet
import json
import pandas as pd
import pytest
from personal_quant.common import decimal as D
from personal_quant.data.calendar import Calendar
from personal_quant.options.contracts import OptionContract
from personal_quant.options.monthly_replay import monthly_replay
from test_options_monthly_replay_v19 import monthly_signals,ROOT

def natural_path(signals,spot):
    expiry=signals[-1]['selection']['expiry']
    calendar=Calendar.market(signals[0]['applicable_session'],str((pd.Timestamp(expiry)+pd.Timedelta(days=15)).date()))
    end=calendar.next(expiry);days=calendar.sessions[calendar.sessions<=end]
    stocks={'SPY':{str(d.date()):str(spot if d>=pd.Timestamp(expiry) else 100) for d in days}}
    contracts={l['contract']['contract_id']:OptionContract.from_dict(l['contract']) for sig in signals for l in sig['selection']['legs']}
    quotes={l['contract']['contract_id']:l['reference_quote'] for sig in signals for l in sig['selection']['legs']}
    options={}
    for identity,c in contracts.items():
        rows={}
        for d in days:
            day=str(d.date())
            if not c.listed_at[:10]<=day<=c.expiry or quotes[identity]['received_at'][:10]>day:continue
            intrinsic=max(D(spot)-c.strike,D(0)) if c.right=='CALL' else max(c.strike-D(spot),D(0))
            prior_bid=D(quotes[identity]['bid']) if signals[0]['selection']['template_id'].endswith('credit_spread') else D(1)
            bid=max(D('.01'),intrinsic) if day==expiry else prior_bid
            rows[day]={'bid':str(bid),'ask':str(bid+D('.1'))}
        options[identity]=rows
    return dict(schema_version=1,data_type='synthetic',stocks=stocks,options=options)

@pytest.mark.parametrize('template,spot,kind,expected',[
    ('protective_put',100,'OPTION_EXPIRY',99762),
    ('protective_put',90,'OPTION_EXERCISE',98762),
    ('covered_call',110,'OPTION_ASSIGNMENT',101182),
    ('cash_secured_put',90,'OPTION_ASSIGNMENT',99182)])
def test_natural_monthly_lifecycle_from_actual_engine_once(tmp_path,template,spot,kind,expected):
    signals=monthly_signals(tmp_path,template)
    proof=monthly_replay(native_engine_root(),native_dotnet(),tmp_path/'engine',signals,
        initial_cash=100000,fee_per_contract=2,packages=[1,2],
        execution_path=natural_path(signals,spot),final_lifecycle='natural_expiry')
    events=json.loads((tmp_path/'engine/engine-events.json').read_text())
    assert any(e['order_type']=='OptionExercise' for e in events)
    assert proof['final_lifecycle']=='natural_expiry' and proof['duplicate_events_added']==0
    assert D(proof['expected_equity'])==expected and D(proof['ledger_bridge']['equity'])==expected
    assert proof['ledger_bridge']['positions']=={} and proof['ledger_bridge']['option_positions']=={}
    from personal_quant.portfolio import Ledger
    book=Ledger(tmp_path/'engine/bridge.sqlite','demo')
    facts=[json.loads(r[0]) for r in book.connection.execute('SELECT payload FROM events')]
    assert len([f for f in facts if f['kind']==kind])==1
    assert not any(f['kind']=='SELL' and f.get('symbol')=='SPY' and f['effective_at']==
        next(f['effective_at'] for f in facts if f['kind']==kind) for f in facts)
    book.close()


@pytest.mark.parametrize('template,spot', [('collar',90),('collar',110),
    ('bull_call_debit_spread',110),('bear_put_debit_spread',90),('long_call',110),('long_put',100)])
def test_multi_leg_or_other_a8_natural_lifecycle(tmp_path,template,spot):
    signals=monthly_signals(tmp_path,template)
    proof=monthly_replay(native_engine_root(),native_dotnet(),tmp_path/'engine',signals,
        initial_cash=100000,fee_per_contract=2,packages=[1,2],
        execution_path=natural_path(signals,spot),final_lifecycle='natural_expiry')
    events=json.loads((tmp_path/'engine/engine-events.json').read_text())
    native=[e for e in events if e['order_type']=='OptionExercise' and e['symbol']==e['order_symbol']]
    assert len(native)==len(signals[-1]['selection']['legs'])
    assert all(abs(e['quantity'])==2 for e in native)
    assert proof['duplicate_events_added']==0 and proof['ledger_bridge']['positions']=={}
    assert proof['ledger_bridge']['option_positions']=={} and proof['ledger_bridge']['anomalies']==[]
    assert len(proof['lifecycle_receipts'])==len(native)
    assert len({r['ledger_seq'] for r in proof['lifecycle_receipts']})==len(native)
    if template=='bear_put_debit_spread':
        first=proof['lifecycle_receipts'][0]
        if any(D(q)<0 for q in first['snapshot']['positions'].values()):
            assert first['check_status']=='BLOCKED' and 'UNSUPPORTED_STOCK_SHORT_AFTER_DELIVERY' in first['checks']

def test_receipt_short_or_missing_equity_blocks_without_erasing_earlier_state():
    from personal_quant.options.monthly_natural import receipt_view
    row=dict(event_id='one-leg',kind='OPTION_EXERCISE')
    first=receipt_view(row,dict(anomalies=[],positions={'SPY':'-200'},equity='100000'),7)
    second=receipt_view(dict(row,event_id='counter-leg'),dict(anomalies=[],positions={},equity='100000'),8)
    assert first['check_status']=='BLOCKED' and first['checks']==['UNSUPPORTED_STOCK_SHORT_AFTER_DELIVERY']
    assert first['snapshot']['positions']=={'SPY':'-200'} and second['check_status']=='CHECKED'
    missing=receipt_view(row,dict(anomalies=[],positions={},equity=None),7)
    assert missing['check_status']=='BLOCKED'
