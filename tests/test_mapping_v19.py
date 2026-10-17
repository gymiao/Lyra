import json
from pathlib import Path
import pytest
from personal_quant.common import QuantError
from personal_quant.portfolio.mapping import map_statement

ROOT=Path(__file__).resolve().parents[1]


def sample():
    return (ROOT/'examples/mappings/test_broker.csv').read_bytes(),json.loads((ROOT/'examples/mappings/test_broker.json').read_text())


def test_identical_legitimate_fills_keep_distinct_ids_and_reordered_file_is_idempotent(ledger):
    raw,mapping=sample();first=map_statement(raw,mapping)
    assert first['status']=='READY_FOR_PREVIEW'
    assert ledger.import_events('sample',first['events'])['added']==3
    reordered=b'\n'.join([raw.splitlines()[0],*reversed(raw.splitlines()[1:])])+b'\n'
    again=map_statement(reordered,{**mapping,'revision':2})
    assert again['original_file_hash']!=first['original_file_hash']
    assert ledger.import_events('sample',again['events'])['added']==0
    state=ledger.snapshot('sample','2024-07-03T21:00:00Z',{'SPY':100})
    assert state['settled_cash']=='598' and state['positions']=={'SPY':'4'} and state['equity']=='998'


def test_conflict_rolls_back_whole_import_and_unknown_row_remains_pending(ledger):
    raw,mapping=sample();events=map_statement(raw,mapping)['events']
    ledger.import_events('sample',events)
    bad=[{**events[1],'event_id':'new'},{**events[2],'price':'101'}]
    with pytest.raises(QuantError):ledger.import_events('sample',bad)
    assert ledger.sequence('sample')==3
    result=map_statement(raw.replace(b',Buy,',b',Unknown,'),mapping)
    assert result['status']=='BLOCKED' and len(result['pending'])==2


def test_ambiguous_dst_and_fee_rows_are_not_silently_converted():
    raw,mapping=sample()
    result=map_statement(raw.replace(b'2024-07-01 11:00:00',b'2024-11-03 01:30:00'),mapping)
    assert result['status']=='BLOCKED'
    with pytest.raises(QuantError):map_statement(raw,{**mapping,'expression':'__import__("os")'})
