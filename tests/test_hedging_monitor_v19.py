import json
import pytest

from personal_quant.common import QuantError,canonical
from personal_quant.hedging.monitor import monitor,require_planning
from personal_quant.hedging.allocation_store import update,resources
from personal_quant.execution.daily import DailyRunner
from personal_quant.execution.plans import PlanService
from personal_quant.strategies import signal
from personal_quant.portfolio import Ledger
from test_daily import scenario,MONTH_END
from test_hedging_parent_bindings_v19 import bound_option
from test_hedging_archive_v19 import frozen_risk
from test_hedging_exposure_v19 import risk_market
from test_hedging_groups_v19 import request
from personal_quant.hedging.groups import save as save_group
from test_ui import setup_ui,button


def corrupt(book):
    book.connection.execute('INSERT INTO tasks VALUES(?,?,?,?)',
        ('hedge-intent:broken','DRAFT','{"bad":true}',MONTH_END))


def test_empty_monitor_is_read_only_and_does_not_invent_protection(ledger):
    before=resources(ledger,'sample')
    result=monitor(ledger,'sample',MONTH_END)
    assert result['status']=='NO_ACTION' and result['current_coverage'] is None
    assert resources(ledger,'sample')==before and ledger.sequence('sample')==0


def test_current_coverage_is_distinct_from_frozen_parent_and_archive(bound_option):
    book,parent,req=bound_option;original=update(book,'sample',req,commit=True)
    clock=req['coverage_request']['as_of'];before=resources(book,'sample')
    first=monitor(book,'sample',clock);second=monitor(book,'sample',clock)
    assert first['status']==second['status']=='SUCCESS'
    assert first['parents']==second['parents'] and first['allocation_archive']==second['allocation_archive']
    assert first['current_coverage']['actual_protected_shares']['security-us-spy']=='100'
    assert first['allocation_archive']==original and first['parents'][0]['decision_at']==parent['decision_at']
    assert not first['executable'] and resources(book,'sample')==before
    overdue=monitor(book,'sample','2026-10-10T00:00:00Z')
    assert overdue['status']=='BLOCKED'
    assert any(c['code']=='HEDGE_EXPIRED_POSITION_UNRESOLVED' for c in overdue['checks'])


def test_changed_group_is_visible_and_blocks_shared_gate(frozen_risk):
    book,*_=frozen_risk;_,req=request(frozen_risk);save_group(book,'sample',req,commit=True)
    body=json.loads(book.connection.execute("SELECT payload FROM plans WHERE plan_id='native-sale'").fetchone()[0])
    body['sizing']['lines'][0]['quantity']='39'
    book.connection.execute("UPDATE plans SET payload=? WHERE plan_id='native-sale'",(canonical(body),))
    result=monitor(book,'sample','2026-10-10T00:00:00Z')
    assert result['status']=='BLOCKED' and result['progress']==[]
    assert result['checks'][0]['code']=='CORRUPT_HEDGE_GROUP'
    with pytest.raises(QuantError) as exc:require_planning(book,'sample','2026-10-10T00:00:00Z')
    assert exc.value.code=='HEDGE_MONITOR_BLOCKED'


def test_daily_records_corruption_and_never_creates_plan(ledger,market,config,tmp_path,monkeypatch):
    cfg,store,_,_,expected=scenario(ledger,market,config,tmp_path,monkeypatch)
    corrupt(ledger)
    runner=DailyRunner(ledger,cfg,store)
    first=runner.run('sample',as_of=MONTH_END,reconciliation=expected)
    second=runner.run('sample',as_of=MONTH_END,reconciliation=expected)
    for result in (first,second):
        assert result['status']=='BLOCKED' and result['planning']['code']=='HEDGE_MONITOR_BLOCKED'
        assert result['hedging']['checks'][0]['code']=='CORRUPT_HEDGE_INTENT'
        assert {'hedge_before_execution','hedge_after_facts'}<={s['name'] for s in result['steps']}
    assert ledger.sequence('sample')==1 and ledger.connection.execute('SELECT count(*) FROM plans').fetchone()[0]==0


def test_direct_plan_creation_cannot_bypass_daily_gate(ledger,market,config,tmp_path,monkeypatch):
    cfg,store,frame,calendar,expected=scenario(ledger,market,config,tmp_path,monkeypatch)
    ledger.reconcile('sample',expected)
    metadata=store.load()[1];value=signal(frame,calendar,cfg,'2024-07-31','fixed',metadata['snapshot_id'])
    corrupt(ledger)
    with pytest.raises(QuantError) as exc:PlanService(ledger,cfg).create('sample',value,frame,metadata,calendar,MONTH_END)
    assert exc.value.code=='HEDGE_MONITOR_BLOCKED'
    assert ledger.sequence('sample')==1 and ledger.connection.execute('SELECT count(*) FROM plans').fetchone()[0]==0


def test_all_pages_show_hedge_failure_without_mutating_facts(tmp_path,monkeypatch):
    app=setup_ui(tmp_path,monkeypatch).run();button(app,'建立空账户').click().run()
    from pathlib import Path
    book=Ledger(Path('runtime/demo/account.sqlite'),'demo');corrupt(book)
    seq=book.sequence('demo-account');book.close()
    for page in ['账户总览','策略研究','调仓计划','运行状态']:
        app.sidebar.radio[0].set_value(page).run()
        assert not app.exception,page
        assert any('只读对冲视图' in c.value for c in app.caption)
        assert any('CORRUPT_HEDGE_INTENT' in str(df.value) for df in app.dataframe)
    book=Ledger(Path('runtime/demo/account.sqlite'),'demo')
    assert book.sequence('demo-account')==seq and book.connection.execute('SELECT count(*) FROM plans').fetchone()[0]==0
    book.close()

