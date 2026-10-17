import pandas as pd
import pytest
from personal_quant.cli import parser,execute
from personal_quant.options.receipt_risk import history
from personal_quant.options.incidents import status
from test_options_receipts_v19 import account,CLOCK
from test_options_receipt_risk_v19 import exercise_pair


@pytest.mark.parametrize('entrypoint',['options','generic'])
def test_public_csv_import_preserves_intermediate_delivery_anomaly(account,tmp_path,entrypoint):
    book,_,config,_=account
    _,batch=exercise_pair(account)
    file=tmp_path/'native-style-test-statement.csv'
    pd.DataFrame(batch['rows']).to_csv(file,index=False)
    commands=([ 'options','--action','import-facts'] if entrypoint=='options' else ['import-events'])+['--account-id','sample','--file',str(file),'--as-of',CLOCK]
    hash_key='expected_hash' if entrypoint=='options' else 'batch_hash'
    preview=execute(parser().parse_args(commands),config)
    assert preview['expected_sequence']==3 and preview.get('pending_events',[])==[]
    assert book.sequence('sample')==3 and history(book,'sample')==[]
    args=parser().parse_args([*commands,'--commit','--expected-sequence','3','--expected-hash',preview[hash_key]])
    result=execute(args,config)
    assert result['added']==2 and book.sequence('sample')==5
    assert book.snapshot('sample',CLOCK)['positions']=={}
    audits=history(book,'sample')
    assert len(audits)==1
    assert audits[0]['risk_history']['prefixes'][0]['snapshot']['positions']=={'SPY':'-100'}
    assert status(book,'sample',CLOCK)['status']=='BLOCKED'
    repeat=execute(args,config)
    assert repeat==result and book.sequence('sample')==5 and len(history(book,'sample'))==1
    # A fresh preview of the same file must report zero new financial facts;
    # the prior anomaly remains in its original immutable audit.
    again=execute(parser().parse_args(commands),config)
    assert again['expected_sequence']==5
    duplicate=execute(parser().parse_args([*commands,'--commit','--expected-sequence','5','--expected-hash',again[hash_key]]),config)
    assert duplicate['added']==0 and duplicate['duplicates']==2 and book.sequence('sample')==5
    assert len(history(book,'sample'))==2 and history(book,'sample')[-1]['risk_history']['prefixes']==[]
    assert status(book,'sample',CLOCK)['status']=='BLOCKED'


def test_mixed_statement_preserves_stock_delivery_and_internal_fee(account):
    from personal_quant.options.receipts import import_statement
    from conftest import event
    book,_,_,_=account;_,batch=exercise_pair(account)
    rows=[batch['rows'][0],event('internal-fee','FEE',amount=5,effective_at=batch['rows'][0]['effective_at']),batch['rows'][1]]
    result=import_statement(book,'sample',rows,3,CLOCK)
    assert result['added']==3 and book.sequence('sample')==6 and result['has_intermediate_anomaly']
    assert book.snapshot('sample',CLOCK)['positions']=={} and book.snapshot('sample',CLOCK)['settled_cash']=='19595'
    prefixes=history(book,'sample')[0]['risk_history']['prefixes']
    assert [p['snapshot']['positions'] for p in prefixes]==[{'SPY':'-100'},{'SPY':'-100'},{}]
    assert status(book,'sample',CLOCK)['status']=='BLOCKED'


def test_generic_statement_audit_failure_rolls_back_all_financial_facts(account,monkeypatch):
    from personal_quant.options.receipts import import_statement
    book,_,_,_=account;_,batch=exercise_pair(account)
    with monkeypatch.context() as fault:
        def reject(*args,**kwargs):raise RuntimeError('synthetic audit publication fault')
        fault.setattr(book,'record_task',reject)
        with pytest.raises(RuntimeError,match='publication fault'):import_statement(book,'sample',batch['rows'],3,CLOCK)
    assert book.sequence('sample')==3 and history(book,'sample')==[]
    assert import_statement(book,'sample',batch['rows'],3,CLOCK)['added']==2
    assert book.sequence('sample')==5 and status(book,'sample',CLOCK)['status']=='BLOCKED'
