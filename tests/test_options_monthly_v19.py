import json
from pathlib import Path
import pandas as pd
import pytest
from personal_quant.common import QuantError,digest
from personal_quant.data.calendar import Calendar
from personal_quant.options.data import OptionDataStore
from personal_quant.options.monthly import freeze_monthly

ROOT=Path(__file__).resolve().parents[1]


def fixture(tmp_path):
    examples=ROOT/'examples/options'
    rows=pd.read_csv(examples/'quotes-engine-fixture.csv')
    for field in ['exchange_timestamp','available_at','received_at','underlying_timestamp','last_timestamp','open_interest_available_at']:
        rows[field]=rows[field].str.replace('2024-10-09','2024-10-31',regex=False)
    store=OptionDataStore(tmp_path/'chains')
    identity=store.save(json.loads((examples/'contracts-engine-fixture.json').read_text()),rows,
                        json.loads((examples/'metadata.json').read_text()))['snapshot_id']
    request=json.loads((examples/'selection-engine-fixture.json').read_text())
    request['decision_at']='2024-10-31T20:30:00Z'
    request['parameters'].update(minimum_dte=10,target_dte=20,max_age_seconds=3600)
    return store,identity,request


def test_monthly_freeze_calendar_and_immutable_retry(tmp_path):
    store,identity,request=fixture(tmp_path)
    calendar=Calendar.market('2024-10-01','2024-12-03')
    archive=tmp_path/'monthly'
    def run():return freeze_monthly(store,identity,request,calendar,archive,scope='synthetic-collar',publication_delay_minutes=30)
    result=run()
    assert result['status']=='FROZEN_FOR_RESEARCH' and not result['executable']
    assert result['applicable_session']=='2024-11-01' and result['applicable_close']=='2024-11-01T20:00:00+00:00'
    assert run()==result and len(list(archive.glob('*.json')))==1
    request['parameters']['target_dte']=21
    with pytest.raises(QuantError,match='已冻结'):run()
    request['decision_at']='2024-10-30T20:30:00Z'
    assert run()['status']=='NO_ACTION'


def test_monthly_early_close_and_incomplete_calendar_fail_closed(tmp_path):
    store,identity,request=fixture(tmp_path)
    request['decision_at']='2024-11-29T21:30:00Z' # Thanksgiving Friday closed at 18:00 UTC.
    calendar=Calendar.market('2024-11-01','2024-12-03')
    with pytest.raises(QuantError,match='实际收盘'):
        freeze_monthly(store,identity,request,calendar,tmp_path/'monthly',scope='test',publication_delay_minutes=30)
    request['decision_at']='2024-11-29T18:30:00Z'
    assert freeze_monthly(store,identity,request,calendar,tmp_path/'monthly',scope='test',publication_delay_minutes=30)['status']=='BLOCKED'
    assert not list((tmp_path/'monthly').glob('*.json'))
    request['decision_at']='2024-10-31T20:30:00Z'
    truncated=Calendar.market('2024-10-01','2024-10-31')
    assert freeze_monthly(store,identity,request,truncated,tmp_path/'monthly',scope='test',publication_delay_minutes=30)['status']=='NO_ACTION'


def test_monthly_archive_tampering_is_not_silently_accepted(tmp_path):
    store,identity,request=fixture(tmp_path)
    calendar=Calendar.market('2024-10-01','2024-12-03')
    archive=tmp_path/'monthly'
    result=freeze_monthly(store,identity,request,calendar,archive,scope='test',publication_delay_minutes=30)
    path=archive/(result['monthly_signal_id']+'.json')
    body=json.loads(path.read_text());body['applicable_session']='2024-11-04';path.write_text(json.dumps(body))
    with pytest.raises(QuantError,match='哈希不匹配'):
        freeze_monthly(store,identity,request,calendar,archive,scope='test',publication_delay_minutes=30)
    # Rehashing the envelope must not conceal a changed frozen contract selection.
    body=result.copy();body['selection']={**result['selection'],'legs':[]}
    body['content_hash']=digest({k:v for k,v in body.items() if k!='content_hash'})
    path.write_text(json.dumps(body))
    with pytest.raises(QuantError,match='哈希不匹配'):
        freeze_monthly(store,identity,request,calendar,archive,scope='test',publication_delay_minutes=30)


def test_monthly_bundle_restores_frozen_signal_and_requires_chain(tmp_path,monkeypatch):
    import shutil
    from test_backup import scenario
    from personal_quant.portfolio.backup import create_bundle,restore_bundle,verify_bundle
    root,config,_,_=scenario(tmp_path,monkeypatch)
    store,identity,request=fixture(tmp_path)
    shutil.copytree(store.root,root/'options/chains')
    calendar=Calendar.market('2024-10-01','2024-12-03')
    body=freeze_monthly(store,identity,request,calendar,root/'options/monthly',scope='test',publication_delay_minutes=30)
    create_bundle(root,config,tmp_path/'bundle')
    proof=verify_bundle(tmp_path/'bundle','demo')
    assert proof['references']['monthly_option_snapshot_refs']==[identity]
    restore_bundle(tmp_path/'bundle',tmp_path/'restored','demo')
    recovered=tmp_path/'restored'/root/'options/monthly'/(body['monthly_signal_id']+'.json')
    assert json.loads(recovered.read_text())==body
    shutil.rmtree(root/'options/chains')
    with pytest.raises(QuantError,match='月度信号引用'):
        create_bundle(root,config,tmp_path/'broken-bundle')
