from pathlib import Path
from personal_quant.config import Config
from personal_quant.workspace.service import create,worker,status
from personal_quant.workspace.schedule import preview
ROOT=Path(__file__).resolve().parents[1]


def test_schedule_preview_is_readonly_and_does_not_install_cron(tmp_path):
    root=tmp_path/'work space';create(root,{'schema_version':1,'kind':'etf','account_id':'demo-account','initial_cash':100000},Config.load(ROOT/'configs/demo.toml'))
    run=worker(root,'start');before=status(root)
    result=preview(root,{'run_id':run['run_id'],'through':'2024-12-31','cron':'0 22 * * 1-5','max_sessions':10,'max_seconds':60,'min_free_bytes':0})
    assert result['status']=='PREVIEW_ONLY' and not result['installed'] and result['financial_events_added']==0
    assert result['tag'] in result['cron_line'] and 'work space' in result['cron_line']
    assert status(root)==before


def test_schedule_invalid_cron_fails_before_any_workspace_access(tmp_path):
    import pytest
    from personal_quant.common import QuantError
    for cron in ['0 22 0 * *','0 22 * 0 *','*/0 * * * *','1--2 * * * *','0 0 * * 6-2']:
        with pytest.raises(QuantError) as error:
            preview(tmp_path/'absent',{'run_id':'a'*64,'through':'2024-12-31','cron':cron,'max_sessions':10,'max_seconds':60,'min_free_bytes':0})
        assert error.value.code=='INVALID_CRON'
