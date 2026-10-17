import json
from pathlib import Path
import pytest
from personal_quant.common import QuantError,digest
from personal_quant.data.store import DataStore
from personal_quant.execution.daily import DailyRunner
from personal_quant.options.ledger import register_contract
from personal_quant.options.receipts import import_batch,advance
from personal_quant.portfolio import Ledger
from personal_quant.portfolio.backup import create_bundle,verify_bundle,restore_bundle,_validate_references
from test_options_ledger_v19 import contract,option_event
from conftest import event

CLOCK='2026-10-10T00:00:00Z'


@pytest.fixture
def account(tmp_path,monkeypatch,config):
    monkeypatch.chdir(tmp_path);root=tmp_path/'runtime/demo';book=Ledger(root/'account.sqlite','demo');book.account('sample')
    c=contract(book,'PUT',100);body=c.content()
    body.update(expiry='2026-10-09',last_trade_at='2026-10-09T20:00:00Z',exercise_cutoff_at='2026-10-09T22:30:00Z')
    c=register_contract(book,body)
    try:yield book,c,config,DataStore(root/'data')
    finally:book.close()


def batch(rows,seq,identity='statement-1'):
    return {'request_id':identity,'rows':rows,'expected_sequence':seq,'expected_hash':digest(rows)}


@pytest.mark.parametrize('kind,cash,side,shares,expected_cash,expected_stock',[
    ('OPTION_EXPIRY',10000,'BUY',0,9800,{}),
    ('OPTION_ASSIGNMENT',10000,'SELL',0,200,{'SPY':'100'}),
    ('OPTION_EXERCISE',10200,'BUY',100,10000,{})])
def test_daily_lifecycle_supplied_facts_cash_stock_and_repeat(account,kind,cash,side,shares,expected_cash,expected_stock):
    book,c,config,store=account
    rows=[event('deposit','DEPOSIT',amount=cash)]
    if shares:rows.append(event('stock','BUY',symbol='SPY',quantity=shares,price=100,settlement_at='2024-07-02T20:00:00Z'))
    rows.append(option_event('open','OPTION_TRADE',c,action='OPEN',trade_side=side,price=2))
    book.import_events('sample',rows)
    notice=option_event('notice',kind,c,position_side='SHORT' if side=='SELL' else 'LONG')
    if kind=='OPTION_EXPIRY':notice.update(effective_at='2026-10-09T22:31:00Z',settlement_at='2026-10-09T22:31:00Z')
    request=batch([notice],book.sequence('sample'))
    result=DailyRunner(book,config,store).run('sample',as_of=CLOCK,option_receipts=request)
    assert result['option_receipts']['status']=='SUCCESS'
    state=book.snapshot('sample',CLOCK,{'SPY':90})
    assert float(state['settled_cash'])==expected_cash and state['positions']==expected_stock
    assert state['option_positions']=={} and state['option_cash_collateral']=='0'
    seq=book.sequence('sample');repeated=DailyRunner(book,config,store).run('sample',as_of=CLOCK,option_receipts=request)
    assert repeated['option_receipts']['audits']==result['option_receipts']['audits'] and book.sequence('sample')==seq
    assert repeated['report_id']==result['report_id']


@pytest.mark.parametrize('boundary',['native_commit','daily_commit'])
def test_receipt_crash_recovery_backup_and_audit_tamper(account,tmp_path,monkeypatch,boundary):
    book,c,config,store=account
    book.import_events('sample',[event('deposit','DEPOSIT',amount=10000),
        option_event('open','OPTION_TRADE',c,action='OPEN',trade_side='BUY',price=2)])
    notice=option_event('expire','OPTION_EXPIRY',c,position_side='LONG')
    notice.update(effective_at='2026-10-09T22:31:00Z',settlement_at='2026-10-09T22:31:00Z')
    request=batch([notice],2)
    import personal_quant.options.receipts as receipts
    original=receipts.import_batch
    def interrupted(*args,**kwargs):
        original(*args,**kwargs);raise RuntimeError('receipt interruption')
    def after(name,result):
        if name=='option_receipts':raise RuntimeError('receipt interruption')
    if boundary=='native_commit':monkeypatch.setattr(receipts,'import_batch',interrupted)
    with pytest.raises(RuntimeError,match='receipt interruption'):
        DailyRunner(book,config,store,after_step=after if boundary=='daily_commit' else None).run(
            'sample',as_of=CLOCK,option_receipts=request)
    assert book.sequence('sample')==3
    monkeypatch.setattr(receipts,'import_batch',original)
    result=DailyRunner(book,config,store).run('sample',as_of=CLOCK,option_receipts=request)
    assert result['option_receipts']['status']=='SUCCESS' and result['equity']=='9800'
    assert book.sequence('sample')==3
    if boundary=='native_commit':
        path=tmp_path/'config.toml';path.write_bytes((Path(__file__).resolve().parents[1]/'configs/demo.toml').read_bytes())
        create_bundle(book.path.parent,path,tmp_path/'bundle');verify_bundle(tmp_path/'bundle','demo')
        restore_bundle(tmp_path/'bundle',tmp_path/'restored','demo')
        restored=Ledger(tmp_path/'restored/runtime/demo/account.sqlite','demo')
        try:assert restored.sequence('sample')==3 and restored.snapshot('sample',CLOCK)['equity']=='9800'
        finally:restored.close()
        identity=result['option_receipts']['audits'][0]['audit_task_id']
        audit=result['option_receipts']['audits'][0];audit['request_hash']='tampered'
        book.connection.execute('UPDATE tasks SET details=? WHERE task_id=?',(json.dumps(audit),identity))
        with pytest.raises(QuantError,match='凭据'): _validate_references(book.path.parent,book)


def test_pending_receipt_blocks_simulation_and_resolves_without_resurrection(account):
    book,c,config,store=account;body=c.content();body['contract_id']='NEW-TERM'
    from personal_quant.options.contracts import OptionContract
    unknown=OptionContract.from_dict(body)
    raw=option_event('unregistered','OPTION_TRADE',unknown,action='OPEN',trade_side='BUY',price=2)
    request=batch([raw],0)
    blocked=DailyRunner(book,config,store).run('sample',as_of=CLOCK,option_receipts=request,
        option_tasks=[{'kind':'OPEN','request':{}}])
    assert blocked['option_receipts']['pending_events']==['unregistered']
    assert blocked['option_execution']['not_processed']==1 and book.sequence('sample')==0
    # Pending facts block even without a repeated batch argument.
    assert DailyRunner(book,config,store).run('sample',as_of=CLOCK)['option_receipts']['status']=='BLOCKED'
    register_contract(book,body)
    with pytest.raises(QuantError,match='显式解决'):
        import_batch(book,'sample',batch([raw],0,'bypass-resolution'),CLOCK)
    assert book.sequence('sample')==0
    resolved=DailyRunner(book,config,store).run('sample',as_of=CLOCK,option_receipts=request,
        option_resolutions=[{'event_id':'unregistered','expected_sequence':0,'expected_hash':digest(raw)}])
    assert resolved['option_receipts']['status']=='SUCCESS' and book.sequence('sample')==1
    repeated=DailyRunner(book,config,store).run('sample',as_of=CLOCK,option_receipts=request)
    assert repeated['option_receipts']['pending_events']==[] and book.sequence('sample')==1


def test_future_hash_conflict_and_stale_batch_do_not_write(account):
    book,c,config,store=account
    raw=option_event('notice','OPTION_EXPIRY',c,position_side='LONG')
    raw.update(effective_at='2026-10-09T22:31:00Z')
    with pytest.raises(QuantError,match='尚未到达'):import_batch(book,'sample',batch([raw],0),'2026-10-09T20:00:00Z')
    with pytest.raises(QuantError,match='预检哈希'):import_batch(book,'sample',{**batch([raw],0),'expected_hash':'bad'},CLOCK)
    result=advance(book,'sample',CLOCK,batch=batch([raw],1));assert result['errors'][0]['code']=='STALE_PREVIEW'
    assert book.sequence('sample')==0 and book.connection.execute("SELECT count(*) FROM tasks WHERE task_id LIKE 'option-receipt-batch:%'").fetchone()[0]==0


def test_same_request_id_cannot_change_facts(account):
    book,c,_,_=account
    raw=option_event('unknown','UNKNOWN_OPTION_ACTION',c,position_side='LONG')
    import_batch(book,'sample',batch([raw],0),CLOCK)
    with pytest.raises(QuantError,match='不能更换'):
        import_batch(book,'sample',batch([{**raw,'quantity':2}],0),CLOCK)
    assert book.connection.execute('SELECT count(*) FROM pending_option_events').fetchone()[0]==1


def test_known_event_cannot_be_replaced_by_unknown_receipt(account):
    book,c,_,_=account
    raw=option_event('existing','OPTION_TRADE',c,action='OPEN',trade_side='BUY',price=2)
    book.import_events('sample',[raw])
    with pytest.raises(QuantError,match='已入账事实冲突'):
        import_batch(book,'sample',batch([{**raw,'kind':'UNKNOWN_OPTION_ACTION'}],1),CLOCK)
    assert book.sequence('sample')==1 and book.connection.execute('SELECT count(*) FROM pending_option_events').fetchone()[0]==0
