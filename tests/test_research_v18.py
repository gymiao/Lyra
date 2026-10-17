import json
from pathlib import Path
import pandas as pd
import pytest
from personal_quant.common import QuantError, write_json
from personal_quant.strategies.store import enable_v18, StrategyStore
from personal_quant.research.artifacts import export_package, verify_package, replay_package
from personal_quant.research.validation import ValidationService
from personal_quant.diagnostics import doctor, sync_notices, acknowledge
from test_research_service_v15 import research_workspace


def setup_validation(service, spec):
    config=__import__('personal_quant.config',fromlist=['Config']).Config.from_dict(spec.content()['config'])
    enable_v18(service.ledger,Path('config.json'))
    library=StrategyStore(service.ledger)
    refs={}
    for name,item in spec.content()['members'].items():
        renamed={**item,'strategy_id':name}
        strategy=__import__('personal_quant.strategies.spec',fromlist=['StrategySpec']).StrategySpec.from_dict(renamed)
        library.publish(strategy);refs[name]={'strategy_id':name,'revision':item['revision']}
    request={'members':refs,'benchmark_member_id':'benchmark','data_bundle':spec.content()['data_bundle'],
        'windows':[{'start':'2024-07-01','end':'2024-09-30'},{'start':'2024-10-01','end':'2024-12-31'}],
        'cost_scenarios':[{'id':'base','commission_multiplier':1,'slippage_multiplier':1,'fixed_fee_multiplier':1},
                          {'id':'double','commission_multiplier':2,'slippage_multiplier':2,'fixed_fee_multiplier':2}]}
    return ValidationService(service.ledger,config),request


def test_package_restores_matching_code_and_replays_without_account(research_workspace,tmp_path,monkeypatch):
    service,spec=research_workspace
    original=service.run(service.submit(spec)['attempt_id'])
    package=tmp_path/'package';export_package(service,original['run_id'],package)
    assert not list(package.rglob('*.sqlite'))
    # Replay must not consult the active code fingerprint.
    monkeypatch.setattr('personal_quant.research.artifacts.source_fingerprint',lambda:'f'*64)
    result=replay_package(package,tmp_path/'replayed')
    new=json.loads((Path(result['report'])/'manifest.json').read_text())
    assert new['source_hash']==original['source_hash']
    assert new['metrics']==original['metrics']
    pd.testing.assert_frame_equal(pd.read_csv(Path(result['report'])/'nav.csv'),pd.read_csv(service.reports/original['run_id']/'nav.csv'))
    assert verify_package(package)['source_hash']==original['source_hash']
    file=package/'workspace/config.json';file.write_text('{}')
    with pytest.raises(QuantError,match='改变'):verify_package(package)


def test_independent_windows_cost_scenarios_and_idempotence(research_workspace):
    service,spec=research_workspace;validation,request=setup_validation(service,spec)
    suite=validation.create(request);result=validation.run(suite['suite_id'])
    assert result['status']=='SUCCESS'
    assert len(result['items'])==4
    ids={item['attempt_id'] for item in result['items']}
    for item in result['items']:
        metrics=item['details']['metrics']
        assert all(m['initial_capital']==10000 for m in metrics.values())
        assert len({m['start'] for m in metrics.values()})==1
        assert len({m['end'] for m in metrics.values()})==1
    repeated=validation.run(suite['suite_id'])
    assert {i['attempt_id'] for i in repeated['items']}==ids
    assert repeated['details']['not_stitched_equity'] is True
    assert service.ledger.connection.execute('SELECT count(*) FROM events').fetchone()[0]==0


def test_missing_child_produces_incomplete_not_partial_success(research_workspace):
    service,spec=research_workspace;validation,request=setup_validation(service,spec)
    request['windows']=[{'start':'2024-07-01','end':'2024-07-15'}] # No eligible month-end execution.
    result=validation.run(validation.create(request)['suite_id'])
    assert result['status']=='INCOMPLETE'
    assert all(i['status']=='FAILED' for i in result['items'])


def test_protocol_and_suite_limits(research_workspace):
    service,spec=research_workspace;validation,request=setup_validation(service,spec)
    protocol=validation.protocol({'name':'fixed observed rule','specification':request,'future_start':None})
    assert protocol['purpose']=='observed_validation'
    request['windows']*=10
    with pytest.raises(QuantError,match='48'):validation.create(request)
    with pytest.raises(QuantError):validation.protocol({'name':'invalid future','specification':protocol['specification'],'future_start':'2000-01-01T00:00:00Z'})


def test_doctor_does_not_create_database_and_ack_does_not_resolve(config,tmp_path,monkeypatch,research_workspace):
    service,spec=research_workspace;validation,_=setup_validation(service,spec)
    result=doctor(validation.config,'2024-12-31T21:00:00Z')
    before=service.ledger.sequence('none')
    notices=sync_notices(service.ledger,result)
    assert notices
    identity=notices[0]['notice_id']
    acknowledge(service.ledger,identity)
    repeated=sync_notices(service.ledger,result)
    assert len(repeated)==len(notices)
    assert next(n for n in repeated if n['notice_id']==identity)['status']=='OPEN'
    assert service.ledger.sequence('none')==before
    other=tmp_path/'empty';other.mkdir();monkeypatch.chdir(other)
    assert doctor(config)['read_only']
    assert not Path(config.runtime_dir).exists()


def test_future_protocol_refuses_pre_registration_window(research_workspace):
    service,spec=research_workspace;validation,request=setup_validation(service,spec)
    with pytest.raises(QuantError,match='不能早于'):
        validation.protocol({'name':'future','specification':request,'future_start':'2090-01-01T00:00:00Z'})


def test_notice_resolution_and_recurrence_reset_read_acknowledgement(research_workspace):
    service,spec=research_workspace;validation,request=setup_validation(service,spec)
    issue={'checks':[{'kind':'task','id':'daily','status':'FAILED'}]}
    first=sync_notices(service.ledger,issue);identity=first[0]['notice_id']
    acknowledge(service.ledger,identity)
    assert sync_notices(service.ledger,{'checks':[]})[0]['status']=='RESOLVED'
    again=sync_notices(service.ledger,issue)
    assert len(again)==1 and again[0]['status']=='OPEN' and again[0]['acknowledged_at'] is None


def test_continuous_year_slice_uses_prior_holdings_equity():
    from personal_quant.research.slices import continuous_slices
    nav=pd.DataFrame({'baseline':[100,110,121,133.1]},index=pd.to_datetime(['2023-12-28','2023-12-29','2024-01-02','2024-01-03']))
    trades=pd.DataFrame(columns=['Date','strategy','total_cost'])
    result=continuous_slices(nav,trades,100)
    assert abs(result[1]['total_return']-.21)<1e-10
    assert result[1]['baseline_as_of']=='2023-12-29'


def test_parent_recovery_reuses_published_child_and_preserves_attempt_history(research_workspace,monkeypatch):
    from personal_quant.research.service import ResearchService
    service,spec=research_workspace;validation,request=setup_validation(service,spec)
    suite=validation.create(request)
    original=ResearchService.run
    class Crash(BaseException):pass
    crashed=[]
    def stop_after_publish(self,attempt_id):
        result=original(self,attempt_id)
        if not crashed:crashed.append(attempt_id);raise Crash()
        return result
    monkeypatch.setattr(ResearchService,'run',stop_after_publish)
    with pytest.raises(Crash):validation.run(suite['suite_id'])
    service.ledger.connection.execute("UPDATE validation_suites SET details='{}' WHERE suite_id=?",(suite['suite_id'],))
    monkeypatch.setattr(ResearchService,'run',original)
    validation.recover(suite['suite_id'])
    result=validation.run(suite['suite_id'])
    assert result['status']=='SUCCESS'
    assert any(i['attempt_id']==crashed[0] for i in result['items'])
    assert len(service.list())==4
    assert validation.recover(suite['suite_id'])['status']=='SUCCESS'


def test_source_archive_rejects_unlisted_files_and_stale_dependency_lock(tmp_path):
    import hashlib,json
    from personal_quant.research.artifacts import capture_source,verify_source
    root=tmp_path/'runtime';archive=capture_source(root)
    extra=archive/'.env';extra.write_text('PRIVATE_TEST_VALUE=not_a_credential')
    with pytest.raises(QuantError,match='额外'):verify_source(archive,archive.name)
    extra.unlink()
    lock=archive/'pyproject.toml';lock.write_text(lock.read_text()+'\n# changed dependency declaration\n')
    path=archive/'source-manifest.json';body=json.loads(path.read_text());body['files']['pyproject.toml']=hashlib.sha256(lock.read_bytes()).hexdigest();path.write_text(json.dumps(body))
    verify_source(archive,archive.name)
    with pytest.raises(QuantError,match='依赖声明'):capture_source(root)


@pytest.mark.parametrize('field,value',[('members',[]),('windows',[{'start':None,'end':'2024-12-31'}]),('cost_scenarios',['unexpected'])])
def test_malformed_validation_spec_is_rejected_without_partial_writes(research_workspace,field,value):
    service,spec=research_workspace;validation,request=setup_validation(service,spec)
    request[field]=value
    with pytest.raises(QuantError):validation.create(request)
    assert service.ledger.connection.execute('SELECT count(*) FROM validation_suites').fetchone()[0]==0
    assert service.ledger.connection.execute('SELECT count(*) FROM research_attempts').fetchone()[0]==0
