import json
from pathlib import Path
import pandas as pd
from native_tools import native_engine_root,native_dotnet
from personal_quant.options.data import OptionDataStore
from personal_quant.options.replay import fixture_replay
from personal_quant.options.qualification import assess_engine


def build_evidence(tmp_path):
    examples=Path(__file__).resolve().parents[1]/'examples/options'
    contracts=json.loads((examples/'contracts-engine-fixture.json').read_text())
    rows=pd.read_csv(examples/'quotes-engine-fixture.csv')
    rows=rows.astype({'bid':float,'ask':float})
    bids={'PUT90':.5,'PUT95':1,'PUT100':2,'CALL100':2,'CALL105':1,'CALL110':.5}
    for i,row in rows.iterrows():
        key=next(key for key in bids if row['contract_id'].endswith(key))
        rows.loc[i,'bid']=bids[key];rows.loc[i,'ask']=bids[key]+.05
    store=OptionDataStore(tmp_path/'chains')
    identity=store.save(contracts,rows,json.loads((examples/'metadata.json').read_text()))['snapshot_id']
    rule=json.loads((examples/'selection-engine-fixture.json').read_text())
    output=tmp_path/'engine'
    proof=fixture_replay(native_engine_root(),native_dotnet(),output,store,identity,rule,
        initial_cash=100000,fee_per_contract=2,exercise_case=True,
        templates=['iron_condor','iron_butterfly'],minimum_spread_width=5)
    return output/'verification.json'


def test_four_leg_native_round_trip_both_assignments_and_expiry(four_evidence):
    output=four_evidence.parent;proof=json.loads(four_evidence.read_text())
    for name,expiry,assignment in [('iron_condor',100082,99577),('iron_butterfly',100182,99677)]:
        assert float(proof['cases'][name]['actual_equity'])==99964
        assert float(proof['cases'][name+'_worthless_expiry']['actual_equity'])==expiry
        for side,shares in [('put','100'),('call','-100')]:
            case=proof['cases'][name+'_'+side+'_assignment']
            assert float(case['actual_equity'])==assignment
            assert case['ledger_lifecycle_path'][0]['snapshot']['positions']=={'SPY':shares}
            assert case['ledger_bridge']['positions']=={} and case['ledger_bridge']['option_positions']=={}
        assert assess_engine(output/'verification.json',name)['status']=='PASSED'
