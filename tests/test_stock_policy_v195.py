import pytest
from personal_quant.workspace.stock_policy import prepare
from personal_quant.common import QuantError
from personal_quant.execution.context import intent_context
from conftest import event

DAY='2024-11-01'
CYCLE={'signal_id':'frozen-option-cycle','stock_positions':{'SPY':100},'stock_entry':{'SPY':100},'stock_exit':{'SPY':100}}
PATH={'stocks':{'SPY':{DAY:'99'}},'options':{}}


def test_stock_plan_reserves_once_and_common_projection_tracks_partial_actual_fills(ledger,config):
    ledger.import_events('sample',[event('fund','DEPOSIT',amount=100000)])
    with ledger.transaction():
        identity=prepare(ledger,config,'sample','run',CYCLE,'BUY',DAY,PATH)
        assert prepare(ledger,config,'sample','run',CYCLE,'BUY',DAY,PATH)==identity
    state=ledger.snapshot('sample','2024-11-01T19:50:00Z')
    assert float(state['reserved_cash'])==9906.93
    ledger.import_events('sample',[event('partial','BUY',plan_id=identity,symbol='SPY',quantity=40,price=99,
        effective_at='2024-11-01T20:00:00Z',settlement_at='2024-11-04T21:00:00Z')])
    row=ledger.connection.execute('SELECT execution_status,reserved_cash FROM plans WHERE plan_id=?',(identity,)).fetchone()
    assert row[0]=='PARTIAL' and float(row[1])==5944.158
    ledger.import_events('sample',[event('rest','BUY',plan_id=identity,symbol='SPY',quantity=60,price=99,
        effective_at='2024-11-01T20:00:00Z',settlement_at='2024-11-04T21:00:00Z')])
    row=ledger.connection.execute('SELECT execution_status,reserved_cash FROM plans WHERE plan_id=?',(identity,)).fetchone()
    assert row[0]=='FILLED' and float(row[1])==0


@pytest.mark.parametrize('cash,code',[(11000,'WEIGHT_LIMIT'),(9000,'INSUFFICIENT_SETTLED_CASH')])
def test_stock_budget_and_concentration_block_before_creating_plan(ledger,config,cash,code):
    ledger.import_events('sample',[event('fund','DEPOSIT',amount=cash)])
    with pytest.raises(QuantError) as caught:prepare(ledger,config,'sample','run',CYCLE,'BUY',DAY,PATH)
    assert caught.value.code==code
    assert ledger.connection.execute('SELECT count(*) FROM plans').fetchone()[0]==0


def test_simulation_stock_context_cannot_masquerade_as_real_or_strategy_signal():
    with pytest.raises(QuantError):intent_context({'purpose':'simulation_stock','environment':'real','simulation_context':{}})


def test_simulation_stock_plan_renders_and_review_does_not_add_facts(tmp_path,monkeypatch,config):
    from pathlib import Path
    from test_ui_v195 import app_in
    from personal_quant.portfolio import Ledger
    app=app_in(tmp_path,monkeypatch)
    book=Ledger(Path('runtime/demo/account.sqlite'),'demo');book.account('sample')
    book.import_events('sample',[event('fund','DEPOSIT',amount=100000)])
    with book.transaction():identity=prepare(book,config,'sample','run',CYCLE,'BUY',DAY,PATH)
    book.import_events('sample',[event('fill','BUY',plan_id=identity,symbol='SPY',quantity=100,price=99,fee=1.98,
        effective_at='2024-11-01T20:00:00Z',settlement_at='2024-11-04T21:00:00Z')])
    book.close();app.run()
    next(x for x in app.text_input if x.label=='账户 ID').set_value('sample')
    app.sidebar.text_input[0].set_value('2024-11-04T21:30:00Z')
    app.sidebar.radio[0].set_value('调仓计划').run()
    assert not app.exception
    assert any('合成模拟的股票准备' in x.value for x in app.caption)
    assert not any(x.label=='按冻结月末目标修订未完成部分' for x in app.button)
    next(x for x in app.button if x.label=='查看实际执行偏差').click().run()
    assert not app.exception
    book=Ledger(Path('runtime/demo/account.sqlite'),'demo')
    assert book.sequence('sample')==2
    book.close()


def test_partial_stock_plan_backup_restores_exact_remaining_reservation(tmp_path,monkeypatch,config):
    from personal_quant.common import write_json
    from personal_quant.portfolio import Ledger
    from personal_quant.portfolio.backup import create_bundle,restore_bundle
    from personal_quant.config import Config
    monkeypatch.chdir(tmp_path)
    runtime=tmp_path/'runtime/demo';cfg=config;file=tmp_path/'config.json';write_json(file,cfg.content())
    book=Ledger(runtime/'account.sqlite','demo');book.account('sample')
    book.import_events('sample',[event('fund','DEPOSIT',amount=100000)])
    with book.transaction():identity=prepare(book,cfg,'sample','run',CYCLE,'BUY',DAY,PATH)
    fill=event('partial','BUY',plan_id=identity,symbol='SPY',quantity=40,price=99,
        effective_at='2024-11-01T20:00:00Z',settlement_at='2024-11-04T21:00:00Z')
    book.import_events('sample',[fill]);book.close()
    create_bundle(runtime,file,tmp_path/'bundle')
    restored=tmp_path/'restored';result=restore_bundle(tmp_path/'bundle',restored,'demo')
    database=restored/Config.load(result['config']).runtime_dir/'account.sqlite'
    assert database.is_file()
    book=Ledger(database,'demo')
    row=book.connection.execute('SELECT execution_status,reserved_cash FROM plans WHERE plan_id=?',(identity,)).fetchone()
    assert row[0]=='PARTIAL' and float(row[1])==5944.158
    assert book.import_events('sample',[fill])['duplicates']==1
    assert book.sequence('sample')==2
    book.close()
