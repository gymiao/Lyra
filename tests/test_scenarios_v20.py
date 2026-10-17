import copy,json
from dataclasses import replace
from pathlib import Path
import pytest
from personal_quant.common import QuantError
from personal_quant.workspace.scenarios import generate
from personal_quant.workspace.packages import verify
from personal_quant.workspace.service import create
from personal_quant.workspace.option_setup import prepare,load
from personal_quant.config import Config
ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def world(tmp_path_factory):
    root=tmp_path_factory.mktemp('scenario-v20');spec=json.loads((ROOT/'configs/v20-scenario.json').read_text())
    result=generate(spec,root/'package');return root,spec,result


def test_three_month_model_world_has_explicit_source_and_nonconstant_prices(world):
    root,spec,result=world;manifest=verify(root/'package');body=json.loads((root/'package/scenario.json').read_text())
    assert result['cycles']==3 and result['executable'] is False and result['source_qualification']=='UNVERIFIED'
    assert manifest['input_bundle_id']==result['input_bundle_id']
    values=body['execution_path']['stocks']['SPY'];assert len(set(values.values()))>10
    assert len(manifest['option_snapshots'])==3 and len(body['execution_path']['options'])==42


def test_repeated_generation_content_identity_is_reproducible_and_future_nodes_do_not_change_old_chain(world):
    root,spec,result=world;second=generate(spec,root/'repeat');assert second['input_bundle_id']==result['input_bundle_id']
    future=copy.deepcopy(spec);future['price_nodes']['SPY']['2024-10-01']='110'
    changed=generate(future,root/'future');assert changed['input_bundle_id']!=result['input_bundle_id']
    assert verify(root/'future')['option_snapshots'][0]==verify(root/'package')['option_snapshots'][0]


def test_scenario_package_creates_etf_workspace_and_freezes_three_option_cycles(world):
    root,spec,_=world;config=replace(Config.load(ROOT/'configs/demo.toml'),evaluation_end='2024-10-31')
    etf=create(root/'etf',{'schema_version':1,'kind':'etf','account_id':'demo-account','initial_cash':'100000','input_bundle':str(root/'package')},config)
    assert etf['events']==1 and etf['identity']['price_snapshot_id']==verify(root/'package')['roles']['signal']
    create(root/'options',{'schema_version':1,'kind':'options','account_id':'demo-account','initial_cash':'100000'},config)
    params=json.loads((ROOT/'configs/v195-option-setup.json').read_text())
    params.update(template_id='long_call',input_bundle=str(root/'package'))
    params['selection_parameters'].update(minimum_dte=14,target_dte=21,maximum_dte=35,exit_days_before_expiry=3)
    result=prepare(root/'options',params);assert result['cycle_count']==3
    body=load(Path(result['setup_directory']));request=json.loads(Path(result['request_file']).read_text())
    assert len(request['signals'])==3 and request['packages']==[1,1,1]
    assert set(request['execution_path']['stocks']['SPY'].values())!={'100'} and body['data_type']=='synthetic'


def test_changed_file_and_symbolic_links_are_not_accepted_as_package(world):
    import shutil
    root,_,_=world;shutil.copytree(root/'package',root/'tampered')
    (root/'tampered/scenario.json').write_text('{}')
    with pytest.raises(QuantError):verify(root/'tampered')


def test_invalid_model_boundaries_fail_before_output(tmp_path):
    spec=json.loads((ROOT/'configs/v20-scenario.json').read_text());spec['expiry_days']=0
    with pytest.raises(QuantError):generate(spec,tmp_path/'invalid')
    assert not (tmp_path/'invalid').exists()


def test_assemble_existing_complete_chain_preserves_all_candidates(tmp_path):
    import json
    from pathlib import Path
    from personal_quant.workspace.scenarios import generate
    from personal_quant.workspace.packages import assemble,verify
    spec=json.loads((Path(__file__).resolve().parents[1]/'configs/v20-scenario.json').read_text())
    original=tmp_path/'source';generate(spec,original)
    scenario=json.loads((original/'scenario.json').read_text())
    result=assemble({'schema_version':1,'price_package':str(original),'chain_root':str(original/'chains'),
        'cycles':scenario['cycles'],'execution_path':scenario['execution_path'],'underlying':'SPY','corporate_actions':[]},tmp_path/'assembled')
    manifest=verify(tmp_path/'assembled')
    assert result['status']=='ASSEMBLED' and len(manifest['option_snapshots'])==3
    assert manifest['option_snapshots']==verify(original)['option_snapshots']
