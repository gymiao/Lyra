from native_tools import native_engine_root,native_dotnet
import json
import pandas as pd
from test_options_monthly_replay_v19 import ROOT
from personal_quant.options.data import OptionDataStore
from personal_quant.options.replay import fixture_replay
from personal_quant.options.qualification import assess_engine
from personal_quant.common import write_json


def build_vol_evidence(tmp_path_factory):
    import os
    from pathlib import Path
    existing=os.environ.get('LYRAX_TEST_VOL_ENGINE_EVIDENCE')
    if existing:
        for name in ('long_straddle','long_strangle'):assert assess_engine(existing,name)['status']=='PASSED'
        return Path(existing)
    tmp_path=tmp_path_factory.mktemp('vol-engine-profile');examples=ROOT/'examples/options'
    store=OptionDataStore(tmp_path/'chains')
    saved=store.save(json.loads((examples/'contracts-engine-fixture.json').read_text()),
        pd.read_csv(examples/'quotes-engine-fixture.csv'),json.loads((examples/'metadata.json').read_text()))
    fixture_replay(native_engine_root(),native_dotnet(),tmp_path/'engine',store,saved['snapshot_id'],
        json.loads((examples/'selection-engine-fixture.json').read_text()),initial_cash=100000,fee_per_contract=2,
        exercise_case=True,templates=['long_straddle','long_strangle'])
    return tmp_path/'engine/verification.json'


def test_long_vol_profiles_require_native_exercise_exit_and_expiry(vol_evidence):
    proof=json.loads(vol_evidence.read_text())
    for name,premium in [('long_straddle',420),('long_strangle',220)]:
        cases=proof['cases']
        assert float(cases[name]['actual_equity'])==99972
        assert float(cases[name+'_call_exercise']['actual_equity'])==100000-premium-6+1001
        assert float(cases[name+'_put_itm_exit']['actual_equity'])==100000-premium-8+1001
        assert float(cases[name+'_worthless_expiry']['actual_equity'])==100000-premium-4
        assert cases[name+'_call_exercise']['ledger_bridge']['positions']=={'SPY':'100'}
        assert cases[name+'_put_itm_exit']['ledger_bridge']['positions']=={}
        assert assess_engine(vol_evidence,name)['status']=='PASSED'
    proof['cases'].pop('long_straddle_put_itm_exit');missing=vol_evidence.parent/'missing-put-exit.json';write_json(missing,proof)
    assert assess_engine(missing,'long_straddle')['status']=='BLOCKED'
