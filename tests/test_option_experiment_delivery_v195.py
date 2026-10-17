from native_tools import native_engine_root,native_dotnet
import json
import os
from pathlib import Path
import pytest
from personal_quant.common import QuantError
from personal_quant.options.monthly_replay import monthly_replay
from personal_quant.portfolio import Ledger
from personal_quant.workspace.option_experiments import verify_raw
from test_prepared_natural_v195 import inputs

ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('spot,expected',[(90,99556.02),(100,100054.02),(110,100556.02)])
def test_natural_cost_receipts_verify_retirement_and_exact_stock_delivery(tmp_path,spot,expected):
    signals,path=inputs(tmp_path/'inputs','collar',spot)
    engine=Path(os.environ.get('LYRAX_TEST_ENGINE_ROOT',str(native_engine_root())))
    dotnet=Path(os.environ.get('LYRAX_TEST_DOTNET',str(native_dotnet())))
    directory=tmp_path/'native'
    proof=monthly_replay(engine,dotnet,directory,signals,initial_cash=100000,fee_per_contract=2,stock_commission_bps=2,
        execution_path=path,retain_stock=True,prepare_stock=True,final_lifecycle='natural_expiry')
    assert float(proof['actual_equity'])==expected
    book=Ledger.read_only(directory/'bridge.sqlite','demo')
    facts=[e for e in book.active_events('monthly-bridge',proof['ledger_bridge']['as_of']) if e['kind']!='DEPOSIT'];book.close()
    events=json.loads((directory/'engine-events.json').read_text())
    verify_raw(events,facts)
    parent=next(e for e in events if e['order_type']=='OptionExercise' and e['symbol']==e['order_symbol'])
    altered=json.loads(json.dumps(events));altered_facts=json.loads(json.dumps(facts))
    identity=str(parent['order_id'])+':'+str(parent['event_id'])
    next(e for e in altered if e['order_id']==parent['order_id'] and e['event_id']==parent['event_id'])['fee']=1
    next(e for e in altered_facts if e['event_id']==identity)['fee']='1'
    with pytest.raises(QuantError):verify_raw(altered,altered_facts)
    deliveries=[e for e in events if e['order_type']=='OptionExercise' and e['symbol']!=e['order_symbol']]
    assert len(deliveries)==(0 if spot==100 else 1)
    if deliveries:
        deliveries[0]['quantity']+=1 # cannot explain 101 shares using a 100-share contract
        with pytest.raises(QuantError) as caught:verify_raw(events,facts)
        assert caught.value.code=='CORRUPT_EXPERIMENT'
