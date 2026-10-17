import importlib.util
from pathlib import Path
import pytest

script=Path(__file__).resolve().parents[1]/'scripts/check_v195.py'
spec=importlib.util.spec_from_file_location('lyrax_release_check',script)
gate=importlib.util.module_from_spec(spec);spec.loader.exec_module(gate)


def receipt():
    return [{'nodeid':node,'phase':phase,'outcome':'passed'} for node in ('a','b') for phase in ('setup','call','teardown')]


def test_only_complete_case_and_phase_coverage_passes():
    assert gate.complete_results(['a','b'],['b','a'],receipt())


@pytest.mark.parametrize('defect',['missing_case','duplicate_phase','failed_teardown','skipped_setup','xpassed'])
def test_partial_or_nonpassing_evidence_cannot_certify_release(defect):
    rows=receipt();collected=['a','b']
    if defect=='missing_case':collected=['a'];rows=rows[:3]
    elif defect=='duplicate_phase':rows.append(dict(rows[0]))
    elif defect=='failed_teardown':rows[-1]['outcome']='failed'
    elif defect=='skipped_setup':rows[0]['outcome']='skipped'
    else:rows[0]['wasxfail']=True
    assert not gate.complete_results(['a','b'],collected,rows)
