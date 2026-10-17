from native_tools import native_engine_root,native_dotnet
import json
import os
from pathlib import Path
import sqlite3
import pytest
from personal_quant.common import QuantError
from personal_quant.options.contracts import OptionContract
from personal_quant.workspace.option_exit import verify_receipt


@pytest.fixture(scope='module')
def receipt(tmp_path_factory):
    existing=os.environ.get('LYRAX_TEST_EXIT_RUN_ROOT')
    if existing:
        candidates=list(Path(existing).glob('*/prefix-2025-01-13-*/verification.json'))
        assert len(candidates)==1
        directory=candidates[0].parent
    else:
        from test_stock_preparation_v195 import prepared_inputs
        from test_options_monthly_replay_v19 import ROOT
        from personal_quant.options.monthly_replay import monthly_replay
        tmp=tmp_path_factory.mktemp('exit-native-receipt');signals,path=prepared_inputs(tmp/'input')
        directory=tmp/'native'
        monthly_replay(native_engine_root(),native_dotnet(),directory,signals,
            initial_cash=100000,fee_per_contract=2,stock_commission_bps=2,execution_path=path,retain_stock=True,prepare_stock=True)
    proof=json.loads((directory/'verification.json').read_text())
    con=sqlite3.connect((directory/'bridge.sqlite').as_uri()+'?mode=ro',uri=True)
    event=json.loads(con.execute("SELECT payload FROM events WHERE json_extract(payload,'$.kind')='OPTION_TRADE' AND json_extract(payload,'$.action')='CLOSE' ORDER BY seq LIMIT 1").fetchone()[0]);con.close()
    return directory,event,OptionContract.from_dict(event['contract']),proof['cycles'][0]['signal_id']


def test_actual_native_receipt_matches_exact_signal_contract_and_money(receipt):
    directory,event,contract,signal=receipt
    assert len(verify_receipt(directory,event,contract,signal))==64


@pytest.mark.parametrize('change',[{'quantity':'99'},{'fee':'99'},{'trade_side':'BUY'}])
def test_native_receipt_mismatch_is_rejected(receipt,change):
    directory,event,contract,signal=receipt
    with pytest.raises(QuantError) as caught:verify_receipt(directory,{**event,**change},contract,signal)
    assert caught.value.code=='INVALID_ENGINE_FILL'


def test_other_monthly_intent_cannot_claim_receipt(receipt):
    directory,event,contract,signal=receipt
    with pytest.raises(QuantError) as caught:verify_receipt(directory,event,contract,signal+'-different')
    assert caught.value.code=='INVALID_ENGINE_FILL'
