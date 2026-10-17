from native_tools import native_engine_root,native_dotnet
import json
from pathlib import Path
import pandas as pd
import pytest
from personal_quant.data.calendar import Calendar
from personal_quant.options.contracts import OptionContract
from personal_quant.options.data import OptionDataStore
from personal_quant.options.monthly import freeze_monthly
from personal_quant.options.monthly_replay import monthly_replay
from personal_quant.options.catalog import A8

ROOT=Path(__file__).resolve().parents[1]


def monthly_signals(tmp_path,template='collar',underlying='SPY',*,expiry_specs=None,selection_parameters=None,scope=None):
    examples=ROOT/'examples/options';base=json.loads((examples/'contracts-engine-fixture.json').read_text())
    base=[c for c in base if c['expiry']=='2024-11-20']
    rows=pd.read_csv(examples/'quotes-engine-fixture.csv');rows=rows[rows.contract_id.isin([c['contract_id'] for c in base])];contracts=[];frames=[]
    for expiry,session,listed in (expiry_specs or [('2024-12-18','2024-10-31','2024-10-01'),('2025-01-17','2024-11-29','2024-11-01')]):
        frame=rows.copy()
        for body in base:
            c={**body,'underlying':underlying,'expiry':expiry,'contract_id':body['contract_id'].replace('2024-11-20',expiry).replace('SPY',underlying),
               'listed_at':listed+'T13:30:00Z','last_trade_at':expiry+'T21:00:00Z','exercise_cutoff_at':expiry+'T22:30:00Z'}
            contract=OptionContract.from_dict(c);contracts.append(c)
            mask=frame.contract_id==body['contract_id'];frame.loc[mask,'contract_id']=c['contract_id'];frame.loc[mask,'contract_version']=contract.version_hash
        for field in ['exchange_timestamp','available_at','received_at','underlying_timestamp','last_timestamp','open_interest_available_at']:
            frame[field]=frame[field].str.replace('2024-10-09',session,regex=False)
            if session=='2024-11-29':frame[field]=frame[field].str.replace('19:45','17:45',regex=False).str.replace('19:44','17:44',regex=False)
        if template.endswith('credit_spread'):
            for c in contracts:
                if c['expiry']!=expiry:continue
                bid=2 if (c['right'],c['strike']) in {('PUT','95'),('CALL','105')} else 1
                mask=frame.contract_id==c['contract_id'];frame.loc[mask,'bid']=bid;frame.loc[mask,'ask']=bid+.1
        frames.append(frame)
    store=OptionDataStore(tmp_path/'chains');identity=store.save(contracts,pd.concat(frames),json.loads((examples/'metadata.json').read_text()))['snapshot_id']
    calendar=Calendar.market('2024-10-01','2025-01-31');signals=[]
    for decision in ['2024-10-31T20:30:00Z','2024-11-29T18:30:00Z']:
        request=json.loads((examples/'selection-engine-fixture.json').read_text());request.update(template_id=template,decision_at=decision,underlying=underlying)
        request['parameters']['max_age_seconds']=3600
        if selection_parameters:request['parameters'].update(selection_parameters)
        if template.endswith('credit_spread'):request['parameters']['minimum_spread_width']=5
        signals.append(freeze_monthly(store,identity,request,calendar,tmp_path/'monthly',scope=scope or 'synthetic-'+template,publication_delay_minutes=30))
    return signals


def test_two_months_keep_one_engine_cash_balance_and_respect_roll_settlement(tmp_path):
    if not (native_dotnet()).is_file():pytest.skip('隔离引擎未安装')
    signals=monthly_signals(tmp_path)
    proof=monthly_replay(native_engine_root(),native_dotnet(),tmp_path/'engine',signals,initial_cash=100000,fee_per_contract=2)
    # Two collar round trips: each loses 2 x (10 spread + 4 fees), capital never resets.
    assert proof['actual_equity']=='99944.0' or float(proof['actual_equity'])==99944
    assert proof['cycles'][0]['exit_submit_at']=='2024-12-02T15:40:00'
    assert proof['cycles'][1]['entry_submit_at']=='2024-12-03T15:40:00'
    events=json.loads((tmp_path/'engine/engine-events.json').read_text())
    assert len(events)==12 and {event['expiry'] for event in events if event['right']}=={'2024-12-18','2025-01-17'}
    assert signals[0]['selection']['expiry']=='2024-12-18' and signals[1]['selection']['expiry']=='2025-01-17'
    assert float(proof['ledger_bridge']['settled_cash'])==99944 and proof['duplicate_events_added']==0
    assert proof['ledger_bridge']['positions']=={} and proof['ledger_bridge']['option_positions']=={}
    assert [float(s['equity']) for s in proof['ledger_path']]==[99986,99972,99958,99944]
    assert float(proof['ledger_path'][-1]['receivables'])>0 # Last close has not settled yet.


@pytest.mark.parametrize('template',sorted(A8-{'collar'}))
def test_other_a8_monthly_portfolios_use_same_capital_and_unified_ledger(tmp_path,template):
    if not (native_dotnet()).is_file():pytest.skip('隔离引擎未安装')
    signals=monthly_signals(tmp_path,template)
    proof=monthly_replay(native_engine_root(),native_dotnet(),tmp_path/'engine',signals,initial_cash=100000,fee_per_contract=2)
    expected=99944 if template in {'bull_call_debit_spread','bear_put_debit_spread'} else 99972
    assert float(proof['actual_equity'])==expected and float(proof['ledger_bridge']['equity'])==expected
    assert proof['ledger_bridge']['anomalies']==[] and proof['duplicate_events_added']==0
