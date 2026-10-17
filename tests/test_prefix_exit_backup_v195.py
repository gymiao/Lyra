import os
from pathlib import Path
import pytest
from personal_quant.config import Config
from personal_quant.portfolio import Ledger
from personal_quant.portfolio.backup import create_bundle,restore_bundle
from personal_quant.options.exit_tasks import pending_exits
from test_stock_preparation_workspace_v195 import covered_evidence


def test_complete_prefix_exit_archive_restores_native_and_frozen_references(tmp_path,monkeypatch,covered_evidence):
    existing=os.environ.get('LYRAX_TEST_EXIT_WORKSPACE')
    if existing:workspace=Path(existing)
    else:
        from test_stock_preparation_workspace_v195 import test_actual_stock_fill_precedes_covered_plan_activation_and_resume
        test_actual_stock_fill_precedes_covered_plan_activation_and_resume(tmp_path/'source',covered_evidence,'collar',100084.02)
        workspace=tmp_path/'source/workspace'
    monkeypatch.chdir(workspace)
    bundle=tmp_path/'bundle'
    create_bundle(workspace/'runtime/demo',workspace/'config.json',bundle)
    restored=tmp_path/'restored';result=restore_bundle(bundle,restored,'demo')
    database=restored/Config.load(result['config']).runtime_dir/'account.sqlite'
    assert database.is_file()
    book=Ledger(database,'demo')
    assert book.sequence('demo-account')==11
    assert book.connection.execute("SELECT count(*) FROM tasks WHERE task_id LIKE 'option-exit-freeze:%'").fetchone()[0]==2
    assert book.connection.execute("SELECT count(*) FROM tasks WHERE task_id LIKE 'option-exit-simulation:%'").fetchone()[0]==2
    assert pending_exits(book,'demo-account','2025-01-14T22:00:00Z')==[]
    state=book.snapshot('demo-account','2025-01-14T22:00:00Z')
    assert state['positions']=={} and state['option_positions']=={}
    assert float(state['equity'])==100040.02
    book.close()
