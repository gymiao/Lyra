import json
from pathlib import Path
import pytest
from personal_quant.common import QuantError,digest
from personal_quant.options.contracts import OptionContract
from personal_quant.options.ledger import register_contract
from personal_quant.options.receipts import import_batch
from personal_quant.options.lifecycle import resolve_pending
from personal_quant.options.receipt_risk import history
from personal_quant.portfolio import Ledger
from personal_quant.portfolio.backup import create_bundle,verify_bundle,restore_bundle,_validate_references
from test_options_receipts_v19 import account,batch,CLOCK
from test_options_ledger_v19 import option_event
from conftest import event


def resolve(account):
    book,c,_,_=account
    book.import_events('sample',[event('fund','DEPOSIT',amount=1000)])
    body=c.content();body['contract_id']='MISSING-TERMS-RISK'
    unknown=OptionContract.from_dict(body)
    raw=option_event('unknown-open','OPTION_TRADE',unknown,action='OPEN',trade_side='BUY',price=2)
    import_batch(book,'sample',batch([raw],1),CLOCK)
    register_contract(book,body)
    audit=resolve_pending(book,'sample','unknown-open',expected_sequence=1,expected_hash=digest(raw))
    return book,raw,audit


def test_resolved_fact_prefix_persists_replay_and_full_restore(account,tmp_path):
    book,raw,audit=resolve(account)
    risk=audit['risk_history']
    assert risk['before_sequence']==1 and risk['after_sequence']==2
    assert risk['prefixes'][0]['event_id']=='unknown-open'
    assert risk['prefixes'][0]['snapshot']['payables']=='200'
    assert risk['prefixes'][0]['snapshot']['option_positions']=={'MISSING-TERMS-RISK':'1'}
    assert risk['prefixes'][0]['valuation_status']=='NOT_EVALUATED'
    assert resolve_pending(book,'sample','unknown-open',expected_sequence=1,expected_hash=digest(raw))==audit
    assert len(history(book,'sample'))==2 and book.sequence('sample')==2
    path=tmp_path/'config.toml';path.write_bytes((Path(__file__).resolve().parents[1]/'configs/demo.toml').read_bytes())
    create_bundle(book.path.parent,path,tmp_path/'bundle');verify_bundle(tmp_path/'bundle','demo')
    restore_bundle(tmp_path/'bundle',tmp_path/'restored','demo')
    restored=Ledger(tmp_path/'restored/runtime/demo/account.sqlite','demo')
    try:assert history(restored,'sample')==history(book,'sample')
    finally:restored.close()


def test_resolved_audit_tamper_not_hidden_by_exact_replay(account):
    book,raw,audit=resolve(account)
    audit['risk_history']['prefixes'][0]['snapshot']['payables']='0'
    book.connection.execute('UPDATE tasks SET details=? WHERE task_id=?',
                            (json.dumps(audit),audit['audit_task_id']))
    with pytest.raises(QuantError,match='逐凭据'):
        resolve_pending(book,'sample','unknown-open',expected_sequence=1,expected_hash=digest(raw))
    with pytest.raises(QuantError,match='逐凭据'):_validate_references(book.path.parent,book)
