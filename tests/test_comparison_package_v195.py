import json
from pathlib import Path
import pytest
from personal_quant.common import QuantError
from personal_quant.portfolio import Ledger
from personal_quant.workspace.comparison_package import export,verify,restore
from personal_quant.workspace.experiments import compare


def test_option_comparison_package_restores_data_specs_curves_and_cost_without_new_funding(tmp_path,option_experiment_cases):
    request=[option_experiment_cases[name] for name in ['size1','size2']]
    original=compare(request);package=tmp_path/'package'
    exported=export(request,package)
    assert exported['cases']==2 and verify(package)['status']=='PASSED'
    recovered=tmp_path/'restored';restored=restore(package,recovered)
    result=compare(restored['request'])
    for key in ['policy','metrics','execution','curves']:assert result[key]==original[key]
    assert result['request']!=original['request'] and restored['initial_funding_replayed'] is False
    assert json.loads((recovered/'request.json').read_text())==restored['request']
    for entry in restored['request']:
        book=Ledger.read_only(Path(entry['workspace'])/'runtime/demo/account.sqlite','demo')
        assert book.sequence('demo-account')==7
        assert book.connection.execute("SELECT count(*) FROM events WHERE json_extract(payload,'$.kind')='DEPOSIT'").fetchone()[0]==1
        book.close()
    # Accidental changes cannot be hidden by a valid individual backup.
    comparison=package/'comparison.json';comparison.write_bytes(comparison.read_bytes()+b' ')
    with pytest.raises(QuantError) as caught:verify(package)
    assert caught.value.code=='CORRUPT_COMPARISON_PACKAGE'
    with pytest.raises(QuantError):restore(package,tmp_path/'invalid-restore')
    assert not (tmp_path/'invalid-restore').exists()


def test_mismatched_fee_policy_is_rejected_before_export_directory_created(tmp_path,option_experiment_cases):
    with pytest.raises(QuantError) as caught:export([option_experiment_cases['size1'],option_experiment_cases['fee3']],tmp_path/'invalid')
    assert caught.value.code=='INCOMPARABLE_EXPERIMENT'
    assert not (tmp_path/'invalid').exists()


def test_recorded_rule_version_and_observed_interval_filters_use_frozen_inputs(option_experiment_cases,monkeypatch):
    from personal_quant.workspace.experiment_index import index
    workspaces=[case['workspace'] for case in option_experiment_cases.values()]
    versions={signal['selection']['strategy_version'] for case in option_experiment_cases.values()
              for signal in json.loads((Path(case['workspace'])/'runtime/demo/simulation/options'/case['run_id']/'request.json').read_text())['signals']}
    assert versions=={'monthly-selection/2.0.0'}
    recorded=next(iter(versions))
    from personal_quant.options import selection
    monkeypatch.setattr(selection,'RULE_VERSION','future-unpublished-test-rule')
    result=index({'workspaces':workspaces,'filters':{'strategy_version':recorded,
        'start_on_or_after':'2024-11-01','end_on_or_before':'2025-01-14'}})
    assert result['status']=='PASSED' and len(result['experiments'])==3
    assert all(row['period_basis']=='observed' and row['observed_end']=='2025-01-14' for row in result['experiments'])
    assert index({'workspaces':workspaces,'filters':{'end_on_or_before':'2025-01-13'}})['experiments']==[]
    assert index({'workspaces':workspaces,'filters':{'strategy_version':'future-unknown-rule'}})['experiments']==[]

    assert index({'workspaces':workspaces,'filters':{'strategy_version':selection.RULE_VERSION}})['experiments']==[]
