from native_tools import native_engine_root,native_dotnet
from pathlib import Path
import pytest
from personal_quant.common import QuantError
from personal_quant.config import Config
from personal_quant.workspace.service import create,status
from personal_quant.workspace import options_runner

ROOT=Path(__file__).resolve().parents[1]


def test_option_pause_arriving_during_native_work_stops_before_import_and_failure_is_visible(tmp_path,monkeypatch):
    root=tmp_path/'options'
    create(root,{'schema_version':1,'account_id':'demo-account','initial_cash':'100000','kind':'options'},Config.load(ROOT/'configs/demo.toml'))
    monkeypatch.chdir(root)
    first=options_runner.run('start',input_file=ROOT/'examples/options/monthly-variable-path.json',
        engine_root=native_engine_root(),dotnet=native_dotnet(),fee_per_contract=2)
    run_id=first['run_id']
    def request_pause(*args,**kwargs):
        # The main worker owns the simulation lock; pause must still succeed.
        paused=options_runner.run('pause',run_id)
        assert paused['pause_requested'] and paused['status']=='RUNNING'
        return {}
    monkeypatch.setattr(options_runner,'monthly_replay',request_pause)
    paused=options_runner.run('resume',run_id,'2024-11-04',requested_at='2000-01-01T00:00:00Z')
    assert paused['status']=='PAUSED' and paused['events']==1 and paused['through_session'] is None
    def fail(*args,**kwargs):raise QuantError('ENGINE_TEST_FAILURE','engine failed before importing facts')
    monkeypatch.setattr(options_runner,'monthly_replay',fail)
    with pytest.raises(QuantError) as caught:options_runner.run('resume',run_id,'2024-11-04')
    assert caught.value.code=='ENGINE_TEST_FAILURE'
    current=status(root)
    assert current['events']==1 and current['runs'][0]['status']=='FAILED'
    assert (root/'runtime/demo/simulation/options'/run_id/'last-failure.json').exists()
