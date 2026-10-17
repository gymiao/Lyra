from native_tools import native_engine_root,native_dotnet
import json
import shutil
from pathlib import Path
import pandas as pd
import pytest

from personal_quant.common import QuantError
from personal_quant.config import Config
from personal_quant.execution.daily import DailyRunner
from personal_quant.data.store import DataStore
from personal_quant.options.activation import activate
from personal_quant.options.exit_tasks import preview_freeze, freeze_exit
from personal_quant.options.monthly_report import monthly_compare
from personal_quant.options.simulation import execute
from personal_quant.portfolio import Ledger
from personal_quant.portfolio.backup import create_bundle,verify_bundle,restore_bundle
from test_options_activation_v19 import setup,engine_evidence
from test_options_exit_tasks_v19 import exit_quote
from test_options_simulation_v19 import closing_quotes
from test_options_monthly_replay_v19 import ROOT

CLOCK='2024-12-02T21:01:00Z'


@pytest.fixture(scope='module')
def frozen_account(tmp_path_factory,engine_evidence):
    base=tmp_path_factory.mktemp('daily-option-base');root=base/'runtime/demo'
    book=Ledger(root/'account.sqlite','demo');book.account('sample')
    try:
        store,plan,activation=setup(book,root/'options',engine_evidence,cash=100000,packages=1)
        activate(book,store,activation)
        signals=sorted((json.loads(p.read_text()) for p in (root/'options/monthly').glob('*.json')),key=lambda s:s['decision_at'])
        monthly_compare(native_engine_root(),native_dotnet(),root/'options/monthly-research/comparison',signals,
                        initial_cash=100000,fee_per_contract=2,stock_commission_bps=2)
        opening={'kind':'OPEN','request':{'plan_id':plan['plan_id'],'report_id':'comparison',
            'execution_snapshot_id':closing_quotes(store,activation),'as_of':'2024-11-01T20:01:00Z','expected_sequence':1}}
        unopened=base/'unopened';shutil.copytree(root,unopened)
        execute(book,store,opening['request'])
        c=plan['selection']['legs'][0]['contract']['contract_id']
        book.reconcile('sample',{'account_id':'sample','currency':'USD','as_of':'2024-12-02T20:33:00Z',
            'cash_basis':'settled','cash':100098,'positions':{},'option_positions':{c:-1},'equity':99993},{c:1.05})
        reference=exit_quote(store,activation,'2024-12-02T20:34:00Z')
        request={'request_id':'daily-exit','execution_at':'2024-12-02T21:00:00Z','purpose':'OBLIGATION_CLOSE','expected_sequence':2,
            'review':{'plan_id':plan['plan_id'],'as_of':'2024-12-02T20:35:00Z','snapshot_id':reference,
                'trigger':'RISK_REDUCTION','exit_days':7,'fee_per_contract':2,'max_age_seconds':900,
                'max_underlying_skew_seconds':10,'max_spread_fraction':.2,'max_leg_skew_seconds':10,
                'max_underlying_price_fraction':.01,'reconciliation_max_days':1}}
        preview=preview_freeze(book,store,request);assert preview['status']=='CHECKED'
        freeze_exit(book,store,request,expected_hash=preview['preview_hash'])
        task={'kind':'CLOSE','request':{'exit_id':preview['exit_id'],'report_id':'comparison',
            'execution_snapshot_id':exit_quote(store,activation,'2024-12-02T21:00:00Z'),'as_of':CLOCK,'expected_sequence':2}}
        return root,task,unopened,opening
    finally:book.close()


@pytest.fixture
def daily_book(tmp_path,monkeypatch,frozen_account):
    monkeypatch.chdir(tmp_path);source,task=frozen_account[:2];root=tmp_path/'runtime/demo';shutil.copytree(source,root)
    book=Ledger(root/'account.sqlite','demo');config=Config.load(ROOT/'configs/demo.toml')
    try:yield book,config,DataStore(root/'data'),task
    finally:book.close()


@pytest.mark.parametrize('crash',['before_step_record','after_step_record'])
def test_daily_resumes_atomic_option_close_without_duplicate_events(daily_book,tmp_path,monkeypatch,crash):
    book,config,store,task=daily_book
    def interrupt(name,result):
        if name.startswith('option_execution:'):raise RuntimeError('simulated process interruption')
    if crash=='before_step_record':
        import personal_quant.options.exit_tasks as exits
        original=exits.execute_exit
        def interrupted(*args,**kwargs):
            original(*args,**kwargs);raise RuntimeError('simulated process interruption')
        monkeypatch.setattr(exits,'execute_exit',interrupted);runner=DailyRunner(book,config,store)
    else:runner=DailyRunner(book,config,store,after_step=interrupt)
    with pytest.raises(RuntimeError,match='interruption'):runner.run('sample',as_of=CLOCK,option_tasks=[task])
    assert book.sequence('sample')==3
    assert book.connection.execute("SELECT count(*) FROM daily_attempts WHERE status='FAILED'").fetchone()[0]==1
    if crash=='before_step_record':monkeypatch.setattr(exits,'execute_exit',original)
    resumed=DailyRunner(book,config,store).run('sample',as_of=CLOCK,option_tasks=[task])
    assert resumed['option_execution']['status']=='SUCCESS' and float(resumed['equity'])==99986
    assert resumed['status']=='BLOCKED' # Only stock signal input is absent.
    assert book.sequence('sample')==3 and book.snapshot('sample',CLOCK)['option_positions']=={}
    assert not book.snapshot('sample',CLOCK)['pending_option_exits']
    step=next(s for s in resumed['steps'] if s['name'].startswith('option_execution:'))
    assert step['reused']==(crash=='after_step_record')
    again=DailyRunner(book,config,store).run('sample',as_of=CLOCK,option_tasks=[task])
    assert again['report_id']==resumed['report_id'] and book.sequence('sample')==3
    if crash=='before_step_record':
        config_file=tmp_path/'demo.toml';config_file.write_bytes((ROOT/'configs/demo.toml').read_bytes())
        create_bundle(book.path.parent,config_file,tmp_path/'bundle');verify_bundle(tmp_path/'bundle','demo')
        restore_bundle(tmp_path/'bundle',tmp_path/'restored','demo')
        recovered=Ledger(tmp_path/'restored/runtime/demo/account.sqlite','demo')
        try:
            assert recovered.sequence('sample')==3 and float(recovered.snapshot('sample',CLOCK)['equity'])==99986
        finally:recovered.close()


def test_failed_option_task_stops_following_tasks_and_is_visible(daily_book):
    book,config,store,task=daily_book
    bad={**task,'request':{**task['request'],'expected_sequence':0}}
    result=DailyRunner(book,config,store).run('sample',as_of=CLOCK,option_tasks=[bad,task])
    assert result['option_execution']['status']=='BLOCKED' and result['option_execution']['not_processed']==1
    assert result['option_execution']['errors'][0]['code']=='STALE_PREVIEW'
    assert book.sequence('sample')==2 and book.snapshot('sample',CLOCK)['pending_option_exits']
    assert book.connection.execute("SELECT count(*) FROM tasks WHERE task_id LIKE 'option-daily-failure:%' AND status='BLOCKED'").fetchone()[0]==1


def test_task_cannot_execute_for_another_daily_account(daily_book):
    book,config,store,task=daily_book
    # A foreign archived request must not spend this account's resources.
    row=book.connection.execute('SELECT details FROM tasks WHERE task_id=?',
        ('option-exit-freeze:'+task['request']['exit_id'],)).fetchone()
    foreign=json.loads(row[0]);foreign['proposal']['account_id']='other'
    book.connection.execute('UPDATE tasks SET details=? WHERE task_id=?',
        (json.dumps(foreign),'option-exit-freeze:'+task['request']['exit_id']))
    result=DailyRunner(book,config,store).run('sample',as_of=CLOCK,option_tasks=[task])
    assert result['option_execution']['errors'][0]['code']=='OPTION_ACCOUNT_MISMATCH'
    assert book.sequence('sample')==2


def test_temporary_failure_is_cleared_only_after_native_execution(daily_book,monkeypatch):
    book,config,store,task=daily_book
    import personal_quant.options.exit_tasks as exits
    original=exits.execute_exit
    def unavailable(*args,**kwargs):
        raise QuantError('MISSING_EXECUTION_QUOTES','temporary unavailable artifact')
    monkeypatch.setattr(exits,'execute_exit',unavailable)
    blocked=DailyRunner(book,config,store).run('sample',as_of=CLOCK,option_tasks=[task])
    assert blocked['option_execution']['status']=='BLOCKED' and book.sequence('sample')==2
    monkeypatch.setattr(exits,'execute_exit',original)
    recovered=DailyRunner(book,config,store).run('sample',as_of=CLOCK,option_tasks=[task])
    assert recovered['option_execution']['status']=='SUCCESS' and book.sequence('sample')==3
    row=book.connection.execute("SELECT status,details FROM tasks WHERE task_id LIKE 'option-daily-failure:%'").fetchone()
    assert row[0]=='SUCCESS' and json.loads(row[1])['status']=='RECOVERED'
    assert json.loads(row[1])['code']=='MISSING_EXECUTION_QUOTES'


def test_daily_open_resumes_after_native_commit(tmp_path,monkeypatch,frozen_account):
    monkeypatch.chdir(tmp_path);source,task=frozen_account[2:];root=tmp_path/'runtime/demo'
    shutil.copytree(source,root);book=Ledger(root/'account.sqlite','demo')
    config=Config.load(ROOT/'configs/demo.toml');store=DataStore(root/'data')
    import personal_quant.options.simulation as simulation
    original=simulation.execute
    def interrupted(*args,**kwargs):
        original(*args,**kwargs);raise RuntimeError('opening interruption')
    try:
        monkeypatch.setattr(simulation,'execute',interrupted)
        with pytest.raises(RuntimeError,match='opening interruption'):
            DailyRunner(book,config,store).run('sample',as_of=task['request']['as_of'],option_tasks=[task])
        assert book.sequence('sample')==2
        monkeypatch.setattr(simulation,'execute',original)
        result=DailyRunner(book,config,store).run('sample',as_of=task['request']['as_of'],option_tasks=[task])
        assert result['option_execution']['status']=='SUCCESS' and book.sequence('sample')==2
        state=result['option_execution']['results'][0]['audit']['account']
        assert float(state['equity'])==99993 and float(state['option_cash_collateral'])==9500
        assert list(state['option_positions'].values())==['-1']
    finally:book.close()


def test_daily_task_requires_same_processing_clock(daily_book):
    book,config,store,task=daily_book
    result=DailyRunner(book,config,store).run('sample',as_of='2024-12-02T21:02:00Z',option_tasks=[task])
    assert result['option_execution']['errors'][0]['code']=='OPTION_PROCESSING_TIME_MISMATCH'
    assert book.sequence('sample')==2
