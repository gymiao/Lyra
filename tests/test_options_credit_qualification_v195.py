from native_tools import native_engine_root,native_dotnet
import json
import pandas as pd
import pytest
import os
from pathlib import Path
from test_options_monthly_replay_v19 import ROOT
from personal_quant.options.data import OptionDataStore
from personal_quant.options.replay import fixture_replay
from personal_quant.options.qualification import assess_engine
from personal_quant.common import write_json


def build_credit_evidence(tmp_path_factory):
    existing=os.environ.get('LYRAX_TEST_CREDIT_ENGINE_EVIDENCE')
    if existing:
        for name in ('bull_put_credit_spread','bear_call_credit_spread'):
            assert assess_engine(existing,name)['status']=='PASSED'
        return Path(existing)
    tmp_path=tmp_path_factory.mktemp('credit-engine-profile')
    examples=ROOT/'examples/options'
    rows=pd.read_csv(examples/'quotes-engine-fixture.csv')
    for index,row in rows.iterrows():
        if row['contract_id'].endswith(('CALL105','PUT95')):
            rows.loc[index,'bid']=2;rows.loc[index,'ask']=2.1
    store=OptionDataStore(tmp_path/'chains')
    saved=store.save(json.loads((examples/'contracts-engine-fixture.json').read_text()),rows,json.loads((examples/'metadata.json').read_text()))
    request=json.loads((examples/'selection-engine-fixture.json').read_text())
    output=tmp_path/'engine'
    proof=fixture_replay(native_engine_root(),native_dotnet(),output,store,saved['snapshot_id'],request,
        initial_cash=100000,fee_per_contract=2,exercise_case=True,
        templates=['bull_put_credit_spread','bear_call_credit_spread'],minimum_spread_width=5)
    return output/'verification.json'


def test_credit_profiles_require_native_partial_assignment_protection_and_expiry(credit_evidence):
    output=credit_evidence.parent;proof=json.loads(credit_evidence.read_text())
    for name,shares in [('bull_put_credit_spread','100'),('bear_call_credit_spread','-100')]:
        assert float(proof['cases'][name]['actual_equity'])==99972
        partial=proof['cases'][name+'_partial_assignment']
        assert float(partial['actual_equity'])==99586
        states=partial['ledger_lifecycle_path']
        assert states[0]['snapshot']['positions']=={'SPY':shares}
        assert states[1]['snapshot']['positions']=={}
        assert float(proof['cases'][name+'_worthless_expiry']['actual_equity'])==100086
        assert assess_engine(output/'verification.json',name)['status']=='PASSED'
    # A profitable closed round trip alone must never qualify the lifecycle.
    proof['cases'].pop('bear_call_credit_spread_partial_assignment')
    write_json(output/'missing-case.json',proof)
    blocked=assess_engine(output/'missing-case.json','bear_call_credit_spread')
    assert blocked['status']=='BLOCKED'
    assert any(c['code']=='MISSING_LIFECYCLE_CASE' for c in blocked['checks'])
