from collections import namedtuple
from pathlib import Path
import pytest
from personal_quant.common import QuantError
from personal_quant.portfolio.maintenance import managed_backup, retention_preview, recovery_drill
from test_backup import scenario


def test_retention_protects_evidence_and_isolated_drill_replays_account(tmp_path, monkeypatch):
    root, config, _, _ = scenario(tmp_path, monkeypatch)
    directory = tmp_path / 'bundles'
    first = managed_backup(root, config, directory, keep=1)
    second = managed_backup(root, config, directory, keep=1, protected_ids=[first['backup_id']])
    preview = retention_preview(directory, 'demo', 1, [first['backup_id']])
    assert not preview['delete'] and len(preview['preserve']) == 2
    third = managed_backup(root, config, directory, keep=1, protected_ids=[first['backup_id']])
    assert third['removed'] == [second['backup_id']]
    assert Path(first['backup']).exists() and Path(third['backup']).exists()
    drill = recovery_drill(third['backup'], tmp_path/'drill', 'demo')
    assert drill['checks']['event_counts']['events'] == 5
    assert drill['checks']['account_states']['sample']['settled_cash'] == '503.5'


def test_space_failure_keeps_previous_backup(tmp_path, monkeypatch):
    root, config, _, _ = scenario(tmp_path, monkeypatch)
    directory = tmp_path / 'bundles'
    first = managed_backup(root, config, directory, keep=1)
    import personal_quant.portfolio.maintenance as maintenance
    Usage = namedtuple('Usage', 'total used free')
    monkeypatch.setattr(maintenance.shutil, 'disk_usage', lambda _: Usage(100, 100, 0))
    with pytest.raises(QuantError, match='可用0'):
        managed_backup(root, config, directory, keep=1)
    assert Path(first['backup']).is_dir()
    assert len(retention_preview(directory, 'demo')['inventory']) == 1
