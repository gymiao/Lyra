import json
from pathlib import Path
import pytest
from personal_quant.common import QuantError
from personal_quant.config import Config
from personal_quant.options.catalog import MONTHLY_RESEARCH
from personal_quant.portfolio import Ledger
from personal_quant.portfolio.backup import create_bundle,restore_bundle
from personal_quant.workspace.service import create,worker,status
from personal_quant.workspace.option_setup import prepare,load

ROOT=Path(__file__).resolve().parents[1]


def setup(tmp_path,template='protective_put',**changes):
    root=tmp_path/'workspace'
    create(root,{'schema_version':1,'kind':'options','account_id':'demo-account','initial_cash':'100000'},Config.load(ROOT/'configs/demo.toml'))
    spec=json.loads((ROOT/'configs/v195-option-setup.json').read_text());spec.update(template_id=template,**changes)
    if template.endswith('credit_spread') or template in {'iron_condor','iron_butterfly'}:spec['selection_parameters']['minimum_spread_width']=5
    return root,spec


@pytest.mark.parametrize('template',sorted(MONTHLY_RESEARCH))
def test_all_supported_templates_use_public_freezer_complete_chains_and_no_account_facts(tmp_path,template):
    root,spec=setup(tmp_path,template);first=prepare(root,spec)
    assert first['status']=='PREPARED' and first['mode']=='RESEARCH_SCHEDULE_ONLY' and first['executable'] is False
    assert prepare(root,spec)==first
    request=json.loads(Path(first['request_file']).read_text())
    assert len(request['signals'])==2 and all(s['selection']['template_id']==template for s in request['signals'])
    assert [s['decision_at'] for s in request['signals']]==['2024-10-31T20:30:00+00:00','2024-11-29T18:30:00+00:00']
    assert len(request['execution_path']['options'])==20 and all(s['selection']['data_type']=='synthetic' for s in request['signals'])
    assert status(root)['events']==1 and status(root)['runs']==[]
    assert first['last_market_session']==('2025-01-13' if template in {'protective_put','covered_call','collar'} else '2025-01-10')


def test_bad_quality_has_specific_reason_and_cannot_publish_setup(tmp_path):
    root,spec=setup(tmp_path);spec['selection_parameters']['max_age_seconds']=0
    with pytest.raises(QuantError) as caught:prepare(root,spec)
    assert caught.value.code=='OPTION_SETUP_SELECTION_BLOCKED' and 'STALE' in str(caught.value)
    assert not list((root/'runtime/demo/simulation/setups').glob('*/setup-manifest.json'))
    assert status(root)['events']==1


def test_changed_frozen_request_is_refused_and_fee_mismatch_blocks_before_start(tmp_path,monkeypatch):
    root,spec=setup(tmp_path);prepared=prepare(root,spec)
    with pytest.raises(QuantError) as caught:worker(root,'start',input_file=prepared['request_file'],engine_root='/no-engine',dotnet='/no-dotnet',fee_per_contract=3)
    assert '费用与冻结配置不同' in str(caught.value) and status(root)['runs']==[]
    file=Path(prepared['request_file']);file.write_bytes(file.read_bytes()+b' ')
    with pytest.raises(QuantError):load(file.parent)
    assert status(root)['events']==1


def test_prepared_input_is_preserved_by_full_backup_before_any_run(tmp_path,monkeypatch):
    root,spec=setup(tmp_path);prepared=prepare(root,spec);monkeypatch.chdir(root)
    create_bundle(root/'runtime/demo',root/'config.json',tmp_path/'bundle')
    recovered=tmp_path/'recovered';result=restore_bundle(tmp_path/'bundle',recovered,'demo')
    directory=recovered/'runtime/demo/simulation/setups'/prepared['setup_id']
    assert load(directory)['setup_id']==prepared['setup_id']
    assert status(recovered)['events']==1 and status(recovered)['runs']==[]
    assert json.loads((directory/'request.json').read_text())['signals'][0]['selection']['template_id']=='protective_put'
