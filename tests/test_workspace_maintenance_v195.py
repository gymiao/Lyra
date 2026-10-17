import json
from pathlib import Path
import subprocess
import sys
import pytest
from personal_quant.common import QuantError
from personal_quant.config import Config
from personal_quant.portfolio import Ledger
from personal_quant.portfolio.backup import create_bundle
from personal_quant.workspace.service import create
from personal_quant.workspace import maintenance

ROOT=Path(__file__).resolve().parents[1]


def setup(tmp_path,monkeypatch):
    root=tmp_path/'workspace'
    create(root,{'schema_version':1,'kind':'options','account_id':'demo-account','initial_cash':'100000'},Config.load(ROOT/'configs/demo.toml'))
    monkeypatch.chdir(root)
    create_bundle(root/'runtime/demo',root/'config.json',tmp_path/'backup')
    return root,tmp_path/'backup'


def test_public_review_and_recovery_record_actual_time_without_new_money(tmp_path,monkeypatch):
    root,backup=setup(tmp_path,monkeypatch);target=tmp_path/'restored'
    for action,extra in [('backup-review',[]),('recovery-drill',['--destination',str(target)])]:
        process=subprocess.run([sys.executable,'-m','personal_quant','workspace',action,'--workspace',str(root),
            '--source',str(backup),*extra],cwd='/tmp',text=True,capture_output=True)
        assert process.returncode==0,process.stderr
        receipt=json.loads(process.stdout)
        assert receipt['status']=='VERIFIED' and receipt['verified_at'] and receipt['financial_events_added']==0
    book=Ledger.read_only(root/'runtime/demo/account.sqlite','demo')
    cloned=Ledger.read_only(target/'runtime/demo/account.sqlite','demo')
    assert book.sequence('demo-account')==cloned.sequence('demo-account')==1
    assert book.snapshot('demo-account','2024-07-02T21:00:00Z')['settled_cash']=='100000'
    book.close();cloned.close()
    def forbid(*a,**kw):raise AssertionError('status must not fully verify all backup contents again')
    monkeypatch.setattr(maintenance,'verify_bundle',forbid)
    result=maintenance.summary(root)
    assert len(result['records'])==2 and result['schedule_installation']=='UNVERIFIED'
    assert all(r['reference']=='MANIFEST_UNCHANGED' and not r['full_contents_rechecked'] for r in result['records'])
    instant=result['records'][0]['verified_at'];(backup/'manifest.json').write_text('changed')
    again=maintenance.summary(root)
    assert again['records'][0]['verified_at']==instant
    assert all(r['reference']=='REFERENCE_MISSING_OR_CHANGED' for r in again['records'])


def test_foreign_workspace_and_invalid_receipt_are_not_reported_as_verified(tmp_path,monkeypatch):
    root,backup=setup(tmp_path,monkeypatch)
    other=tmp_path/'other';create(other,{'schema_version':1,'kind':'options','account_id':'demo-account','initial_cash':'200000'},Config.load(ROOT/'configs/demo.toml'))
    with pytest.raises(QuantError) as error:maintenance.verify(other,backup,destination=tmp_path/'must-not-exist')
    assert error.value.code=='BACKUP_WORKSPACE_MISMATCH' and not (tmp_path/'must-not-exist').exists()
    result=maintenance.verify(root,backup)
    receipt=root/'runtime/demo/maintenance/receipts'/(result['receipt_id']+'.json')
    receipt.write_text('{"unexpected":"record"}')
    assert maintenance.summary(root)['records'][0]['status']=='INVALID'


def test_receipt_disk_failure_reports_completed_restore_without_hiding_clone(tmp_path,monkeypatch):
    root,backup=setup(tmp_path,monkeypatch);target=tmp_path/'clone'
    def fail(*args,**kwargs):raise OSError(28,'No space left on device')
    monkeypatch.setattr(maintenance,'write_json',fail)
    receipt=maintenance.verify(root,backup,destination=target)
    assert receipt['status']=='VERIFIED_RECORD_PENDING' and (target/'runtime/demo/account.sqlite').is_file()
    assert maintenance.summary(root)['records']==[]


def test_maintenance_ui_records_only_explicit_verified_actions(tmp_path,monkeypatch):
    from streamlit.testing.v1 import AppTest
    root,backup=setup(tmp_path,monkeypatch)
    monkeypatch.setattr(sys,'argv',['app','--config',str(root/'config.json')])
    app=AppTest.from_file(str(ROOT/'src/personal_quant/ui/app.py'),default_timeout=30).run()
    app.sidebar.radio[0].set_value('运行状态').run()
    assert not app.exception and maintenance.summary(root)['records']==[]
    next(x for x in app.text_input if x.label=='当前工作区完整备份目录').set_value(str(backup))
    next(x for x in app.button if x.label=='完整核验备份').click().run()
    assert not app.exception and len(maintenance.summary(root)['records'])==1
    app.run();assert len(maintenance.summary(root)['records'])==1
    next(x for x in app.text_input if x.label=='隔离恢复的新目录').set_value(str(tmp_path/'ui-clone'))
    next(x for x in app.button if x.label=='核验并隔离恢复').click().run()
    assert not app.exception and len(maintenance.summary(root)['records'])==2
    book=Ledger.read_only(root/'runtime/demo/account.sqlite','demo')
    assert book.sequence('demo-account')==1;book.close()
