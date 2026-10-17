from native_tools import native_engine_root,native_dotnet
"""Different ETF options with identical strikes share capital, never identities."""
import json
from copy import deepcopy
import pandas as pd
import pytest
from personal_quant.common import QuantError,decimal as D
from personal_quant.options.contracts import OptionContract
from personal_quant.options.monthly_portfolio import normalize,event_contract
from personal_quant.options.monthly_replay import monthly_replay
from personal_quant.options.monthly_report import monthly_compare,load_monthly_report
from personal_quant.data.calendar import Calendar
from test_options_monthly_replay_v19 import monthly_signals,ROOT


def basket_inputs(tmp_path,*,natural=False):
    spy=monthly_signals(tmp_path/'spy','protective_put',underlying='SPY')
    gld=monthly_signals(tmp_path/'gld','protective_put',underlying='GLD')
    batches=[[spy[i],gld[i]] for i in range(2)]
    end=pd.Timestamp(spy[-1]['selection']['expiry'])
    calendar=Calendar.market(spy[0]['applicable_session'],str((end+pd.Timedelta(days=10)).date()))
    end=calendar.next(end) if natural else end-pd.Timedelta(days=spy[-1]['selection']['exit_days_before_expiry'])
    days=calendar.sessions[calendar.sessions<=end]
    stocks={symbol:{str(day.date()):str(D(base)+D(i)*D(step)) for i,day in enumerate(days)}
        for symbol,base,step in [('SPY',100,'.05'),('GLD',100,'-.03'),('IEF',50,'.02')]}
    contracts={leg['contract']['contract_id']:OptionContract.from_dict(leg['contract']) for batch in batches for signal in batch for leg in signal['selection']['legs']}
    quotes={leg['contract']['contract_id']:leg['reference_quote'] for batch in batches for signal in batch for leg in signal['selection']['legs']}
    options={identity:{str(day.date()):dict(bid=str(D(1)+D(i)*D('.01' if c.underlying=='SPY' else '.02')),
        ask=str(D('1.1')+D(i)*D('.01' if c.underlying=='SPY' else '.02')))
        for i,day in enumerate(days) if c.listed_at[:10]<=str(day.date())<=c.expiry and quotes[identity]['received_at'][:10]<=str(day.date())}
        for identity,c in contracts.items()}
    if natural:
        for symbol,price in [('SPY','110'),('GLD','80')]:
            stocks[symbol][spy[-1]['selection']['expiry']]=price
            stocks[symbol][str(end.date())]=price
    return batches,dict(schema_version=1,data_type='synthetic',stocks=stocks,options=options),contracts


def test_batches_retain_decisions_and_refuse_mixed_clock_scope_packages(tmp_path):
    batches,_,contracts=basket_inputs(tmp_path)
    normalized,counts,multi=normalize(batches,[[2,1],[3,2]])
    assert normalized==batches and counts==[[2,1],[3,2]] and multi
    with pytest.raises(QuantError) as exc:normalize(batches,[2,3])
    assert exc.value.code=='INVALID_MONTHLY_REPLAY'
    with pytest.raises(QuantError) as exc:normalize([batches[0],[batches[1][1],batches[1][0]]])
    assert exc.value.code=='INVALID_MONTHLY_REPLAY'
    event=dict(expiry=next(iter(contracts.values())).expiry,right='PUT',strike=95)
    with pytest.raises(QuantError) as exc:event_contract(event,contracts)
    assert exc.value.code=='LEAN_UNIT_MAPPING_FAILED'
    event['underlying']='GLD';assert event_contract(event,contracts).underlying=='GLD'


def independent_roundtrips(cycles,path):
    value=D(100000)
    for cycle in cycles:
        entry=cycle['entry_submit_at'][:10];exit=cycle['exit_submit_at'][:10]
        for symbol,q in cycle['stock_positions'].items():
            p1=D(path['stocks'][symbol][entry]);p2=D(path['stocks'][symbol][exit]);quantity=D(q)
            value+=quantity*(p2-p1)-quantity*(p1+p2)*D('.0002')
        for leg in cycle['legs']:
            quote=path['options'][leg['contract_id']];q=D(leg['quantity'])
            value+=q*100*(D(quote[exit]['bid'])-D(quote[entry]['ask']))-abs(q)*4
    return value


def test_two_option_underlyings_same_strikes_actual_lean_share_cash(tmp_path):
    batches,path,contracts=basket_inputs(tmp_path);out=tmp_path/'engine'
    proof=monthly_replay(native_engine_root(),native_dotnet(),out,batches,
        initial_cash=100000,fee_per_contract=2,stock_commission_bps=2,packages=[[2,1],[3,2]],stock_basket={'IEF':50},execution_path=path)
    expected=independent_roundtrips(proof['cycles'],path)
    assert D(proof['ledger_bridge']['equity'])==expected and abs(D(proof['actual_equity'])-expected)<=D('.01')
    events=json.loads((out/'engine-events.json').read_text())
    assert len(events)==20 and {e['underlying'] for e in events if e['right']}=={'SPY','GLD'}
    assert {e['symbol'] for e in events if not e['right']}=={'SPY','GLD','IEF'}
    assert proof['ledger_bridge']['positions']=={} and proof['ledger_bridge']['option_positions']=={}
    assert proof['duplicate_events_added']==0 and len(proof['cycles'])==2
    assert all(c['signal_ids']==[s['monthly_signal_id'] for s in batch] for c,batch in zip(proof['cycles'],batches))


def test_two_option_underlyings_report_daily_nav_costs_and_restore(tmp_path):
    batches,path,_=basket_inputs(tmp_path);out=tmp_path/'comparison'
    report=monthly_compare(native_engine_root(),native_dotnet(),out,batches,
        initial_cash=100000,fee_per_contract=2,stock_commission_bps=2,packages=[[2,1],[3,2]],stock_basket={'IEF':50},execution_path=path)
    assert report['option_underlyings']==['GLD','SPY'] and len(report['signal_ids'])==4
    assert report['monthly_batches']==[[s['monthly_signal_id'] for s in batch] for batch in batches]
    assert load_monthly_report(out)==report and report['metrics']['protective_put']['commission']>32
    assert abs(report['metrics']['protective_put']['bid_ask_cost']-80)<1e-8
    equity=pd.read_csv(out/'equity.csv')
    assert not equity.isna().any().any() and len(equity)>40
    for member in ('protective_put','stock','cash'):
        assert abs(D(equity[member].iloc[-1])-D(100000)-D(report['metrics'][member]['net_trading_pnl']))<D('.01')


def test_two_underlyings_natural_delivery_maps_actual_stock_once(tmp_path):
    batches,path,_=basket_inputs(tmp_path,natural=True);out=tmp_path/'natural'
    proof=monthly_replay(native_engine_root(),native_dotnet(),out,batches,initial_cash=100000,
        fee_per_contract=2,stock_commission_bps=2,packages=[[2,1],[3,2]],stock_basket={'IEF':50},execution_path=path,final_lifecycle='natural_expiry')
    events=json.loads((out/'engine-events.json').read_text())
    retired=[e for e in events if e['order_type']=='OptionExercise' and e['symbol']==e['order_symbol']]
    assert {(e['underlying'],e['in_the_money']) for e in retired}=={('SPY',False),('GLD',True)}
    assert proof['ledger_bridge']['positions']=={} and proof['ledger_bridge']['option_positions']=={}
    # 2 GLD Puts retire 200 shares for 19000 once; SPY shares remain until the
    # explicit common recovery close. These are internal transfers, not deposits.
    import sqlite3
    db=sqlite3.connect('file:'+str(out/'bridge.sqlite')+'?mode=ro',uri=True)
    try:rows=[json.loads(r[0]) for r in db.execute('SELECT payload FROM events ORDER BY seq')]
    finally:db.close()
    exercised=[e for e in rows if e['kind']=='OPTION_EXERCISE']
    assert len(exercised)==1 and exercised[0]['contract']['underlying']=='GLD' and D(exercised[0]['quantity'])==2
    assert len([e for e in rows if e['kind']=='DEPOSIT'])==1
