from native_tools import native_engine_root,native_dotnet
from pathlib import Path
import json
import pandas as pd
import pytest
from personal_quant.common import QuantError,decimal as D
from personal_quant.data.calendar import Calendar
from personal_quant.options.contracts import OptionContract
from personal_quant.options.monthly_path import validate_path
from personal_quant.options.monthly_replay import monthly_replay
from test_options_monthly_replay_v19 import monthly_signals,ROOT


def execution(signals):
    first=signals[0]['applicable_session'];last=signals[-1]['selection']
    end=pd.Timestamp(last['expiry'])-pd.Timedelta(days=last['exit_days_before_expiry'])
    calendar=Calendar.market(first,str((end+pd.Timedelta(days=10)).date()))
    days=calendar.sessions[calendar.sessions<=end]
    stocks={s:{str(d.date()):str(base+D(i)*step) for i,d in enumerate(days)}
            for s,base,step in [('SPY',D(100),D('.05')),('IEF',D(50),D('.02'))]}
    contracts={l['contract']['contract_id']:OptionContract.from_dict(l['contract']) for sig in signals for l in sig['selection']['legs']}
    quotes={l['contract']['contract_id']:l['reference_quote'] for sig in signals for l in sig['selection']['legs']}
    options={identity:{str(d.date()):dict(bid=str(D(1)+D(i)*D('.01')),ask=str(D('1.1')+D(i)*D('.01')))
             for i,d in enumerate(days) if c.listed_at[:10]<=str(d.date())<=c.expiry and quotes[identity]['received_at'][:10]<=str(d.date())}
             for identity,c in contracts.items()}
    return dict(schema_version=1,data_type='synthetic',stocks=stocks,options=options),days,contracts,quotes


def test_explicit_path_missing_stock_or_quote_and_precision_refused(tmp_path):
    signals=monthly_signals(tmp_path,'protective_put');path,days,contracts,quotes=execution(signals)
    assert validate_path(path,days,['SPY','IEF'],contracts,quotes)==path
    key=next(iter(path['stocks']['IEF']));path['stocks']['IEF'].pop(key)
    with pytest.raises(QuantError) as exc:validate_path(path,days,['SPY','IEF'],contracts,quotes)
    assert exc.value.code=='INCOMPLETE_LEAN_PATH'
    path,days,contracts,quotes=execution(signals);identity=next(iter(path['options']))
    path['options'][identity][next(iter(path['options'][identity]))]['ask']='.5'
    with pytest.raises(QuantError) as exc:validate_path(path,days,['SPY','IEF'],contracts,quotes)
    assert exc.value.code=='INVALID_LEAN_PATH'
    path,days,contracts,quotes=execution(signals);path['stocks']['SPY'][key]='100.00001'
    with pytest.raises(QuantError) as exc:validate_path(path,days,['SPY','IEF'],contracts,quotes)
    assert exc.value.code=='INVALID_LEAN_PATH'


def test_variable_prices_two_stocks_and_multiple_contracts_actual_lean(tmp_path):
    signals=monthly_signals(tmp_path,'protective_put');path,days,_,_=execution(signals)
    out=tmp_path/'engine'
    proof=monthly_replay(native_engine_root(),native_dotnet(),out,signals,
        initial_cash=100000,fee_per_contract=2,stock_commission_bps=2,
        packages=[2,3],stock_basket={'IEF':50},execution_path=path)
    # Independent endpoint cash calculation: share profits, signed put spread,
    # each opening/closing fee and both stocks' commissions.
    expected=D(100000)
    for index,cycle in enumerate(proof['cycles']):
        first=cycle['entry_submit_at'][:10];last=cycle['exit_submit_at'][:10];n=[2,3][index]
        spy1=D(path['stocks']['SPY'][first]);spy2=D(path['stocks']['SPY'][last])
        ief1=D(path['stocks']['IEF'][first]);ief2=D(path['stocks']['IEF'][last])
        c=signals[index]['selection']['legs'][0]['contract']['contract_id']
        put1=D(path['options'][c][first]['ask']);put2=D(path['options'][c][last]['bid'])
        expected+=100*n*(spy2-spy1)+50*(ief2-ief1)+100*n*(put2-put1)-4*n
        expected-=(100*n*(spy1+spy2)+50*(ief1+ief2))*D('.0002')
    assert abs(D(proof['actual_equity'])-expected)<=D('.01')
    assert D(proof['ledger_bridge']['equity'])==expected
    assert proof['data_type']=='synthetic_variable_path' and proof['duplicate_events_added']==0
    events=json.loads((out/'engine-events.json').read_text())
    assert len(events)==12 and {e['symbol'] for e in events if not e['right']}=={'SPY','IEF'}
    assert sorted(abs(e['quantity']) for e in events if e['right'])==[2,2,3,3]
    assert proof['ledger_bridge']['positions']=={} and proof['ledger_bridge']['option_positions']=={}
    equities=pd.read_csv(out/'daily-equity.csv').equity
    assert equities.nunique()>10

