from pathlib import Path
import pytest
from personal_quant.config import Config
from personal_quant.common import QuantError
from personal_quant.workspace.service import create,status,worker

ROOT=Path(__file__).resolve().parents[1]
SPEC={'schema_version':1,'account_id':'demo-account','initial_cash':'100000','kind':'etf'}


def test_initialization_is_idempotent_and_rejects_replacement(tmp_path):
    config=Config.load(ROOT/'configs/demo.toml');root=tmp_path/'workspace with spaces'
    first=create(root,SPEC,config);again=create(root,SPEC,config)
    assert first['identity']['workspace_id']==again['identity']['workspace_id']
    assert again['events']==1
    with pytest.raises(QuantError) as caught:create(root,{**SPEC,'initial_cash':'200000'},config)
    assert caught.value.code=='WORKSPACE_CONFLICT'
    assert status(root)['events']==1


def test_etf_simulation_can_start_pause_resume_and_repeat(tmp_path):
    config=Config.load(ROOT/'configs/demo.toml');root=tmp_path/'run'
    create(root,SPEC,config)
    first=worker(root,'start');assert worker(root,'start')['run_id']==first['run_id']
    paused=worker(root,'pause',first['run_id']);assert paused['status']=='PAUSED'
    done=worker(root,'resume',first['run_id'],'2024-07-03')
    assert done['through_session']=='2024-07-03' and done['events']==1
    repeat=worker(root,'resume',first['run_id'],'2024-07-03')
    assert repeat['events']==1
    with pytest.raises(QuantError,match='只能前进'):worker(root,'resume',first['run_id'],'2024-07-02')
