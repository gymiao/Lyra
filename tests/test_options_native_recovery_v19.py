"""Native LEAN assignment facts through interrupted receipt and review recovery."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import pytest
from test_options_activation_v19 import engine_evidence
from personal_quant.common import decimal as D,digest,utc
from personal_quant.options.contracts import OptionContract
from personal_quant.options.qualification import assess_engine
from personal_quant.options.ledger import register_contract
from personal_quant.options.receipts import import_batch
from personal_quant.options.incidents import status,save
from personal_quant.hedging.monitor import monitor
from personal_quant.portfolio import Ledger
from personal_quant.portfolio.schema import apply_workbench_schema,apply_v18_schema,apply_v19_schema
from personal_quant.portfolio.backup import create_bundle,verify_bundle,restore_bundle


@pytest.mark.parametrize('case,template,assigned_shares,assigned_cash',[
    ('bull_call_partial_assignment','bull_call_debit_spread',-100,'110386'),
    ('bear_put_partial_assignment','bear_put_debit_spread',100,'90386')])
def test_native_assignment_restart_preserves_prefix_and_recovery(tmp_path,monkeypatch,case,template,assigned_shares,assigned_cash,engine_evidence):
    proof=Path(engine_evidence);assert assess_engine(proof,template)['status']=='PASSED'
    monkeypatch.chdir(tmp_path)
    directory=proof.parent/case
    native=json.loads((directory/'engine-events.json').read_text())
    terms=json.loads((directory/'input.json').read_text())
    source=sqlite3.connect('file:'+str(directory/'bridge.sqlite')+'?mode=ro',uri=True)
    try:rows=[json.loads(r[0]) for r in source.execute('SELECT payload FROM events ORDER BY seq')]
    finally:source.close()
    assert len(rows)==5 and D(rows[0]['amount'])==100000
    actual={str(e['order_id'])+':'+str(e['event_id']):e for e in native if e['order_type']!='OptionExercise' or e['symbol']==e['order_symbol']}
    # Independently cross-check supplied bridge facts against real native events
    # and frozen vanilla terms before using them as this test's statement.
    for row in rows[1:]:
        e=actual[row['event_id']];c=OptionContract.from_dict(row['contract']);c.require_standard_vanilla()
        assert D(row['quantity'])==abs(D(e['quantity'])) and D(row['price'])==D(e['price']) and D(row['fee'])==D(e['fee'])
        assert utc(row['effective_at'])==utc(e['utc_time'])
        leg=next(l for l in terms['legs'] if l['right']==c.right and D(l['strike'])==c.strike and l['expiry']==c.expiry)
        assert c.quote_multiplier==100 and c.deliverable_shares==100 and c.exercise_cash==c.strike*100
        if e['order_type']=='OptionExercise':
            assert row['kind']==('OPTION_ASSIGNMENT' if e['assignment'] else 'OPTION_EXERCISE')
            assert row['position_side']==('LONG' if D(leg['quantity'])>0 else 'SHORT')
        else:assert row['kind']=='OPTION_TRADE' and row['action']=='OPEN'
        row['account_id']='sample'
    rows[0]['account_id']='sample'
    root=tmp_path/'runtime/demo';book=Ledger(root/'account.sqlite','demo');book.account('sample')
    with book.transaction():apply_workbench_schema(book.connection);apply_v18_schema(book.connection);apply_v19_schema(book.connection)
    for row in rows[1:]:register_contract(book,row.pop('contract'))
    book.import_events('sample',rows[:3]);assert book.sequence('sample')==3
    assert D(book.snapshot('sample',rows[2]['effective_at'])['settled_cash'])==99886
    def request(identity,row,sequence):return dict(request_id=identity,rows=[row],expected_sequence=sequence,expected_hash=digest([row]))
    assignment=request('native-assignment',rows[3],3);recovery=request('native-recovery',rows[4],4)
    from personal_quant.options import receipt_risk
    def fail_capture(*args,**kwargs):raise RuntimeError('fault after financial fact, before audit')
    with monkeypatch.context() as fault:
        fault.setattr(receipt_risk,'capture',fail_capture)
        with pytest.raises(RuntimeError,match='before audit'):import_batch(book,'sample',assignment,rows[3]['effective_at'])
    assert book.sequence('sample')==3
    book.close();book=Ledger(root/'account.sqlite','demo')
    audit=import_batch(book,'sample',assignment,rows[3]['effective_at'])
    first=audit['risk_history']['prefixes'][0]['snapshot']
    assert first['positions']=={'SPY':str(assigned_shares)} and D(first['settled_cash'])==D(assigned_cash)
    assert book.sequence('sample')==4
    def fail_audit(*args,**kwargs):raise RuntimeError('fault before publishing recovery audit')
    with monkeypatch.context() as fault:
        fault.setattr(book,'record_task',fail_audit)
        with pytest.raises(RuntimeError,match='recovery audit'):import_batch(book,'sample',recovery,rows[4]['effective_at'])
    assert book.sequence('sample')==4
    book.close();book=Ledger(root/'account.sqlite','demo')
    end=rows[4]['effective_at'];completed=import_batch(book,'sample',recovery,end)
    assert import_batch(book,'sample',recovery,end)==completed and book.sequence('sample')==5
    final=book.snapshot('sample',end,{})
    assert final['positions']=={} and final['option_positions']=={} and D(final['settled_cash'])==100386
    # -210 +100 -4 +500 =386. Assignment/exercise delivery is represented once.
    assert D(final['equity'])==100386 and D(final['net_contributions'])==100000
    if assigned_shares<0:
        assert status(book,'sample',end)['status']=='BLOCKED' and monitor(book,'sample',end)['status']=='BLOCKED'
        book.reconcile('sample',dict(account_id='sample',currency='USD',as_of=end,cash_basis='settled',cash=100386,positions={},option_positions={},equity=100386))
        rid=book.connection.execute('SELECT max(id) FROM reconciliations').fetchone()[0]
        incident=status(book,'sample',end)['incidents'][0]
        frozen=tmp_path/'review';frozen.mkdir();blob=(directory/'engine-events.json').read_bytes();(frozen/'native-events.json').write_bytes(blob)
        review=dict(schema_version=1,request_id='native-fact-review',incident_id=incident['incident_id'],expected_hash=incident['view_hash'],expected_sequence=5,
            as_of=end,recovery_event_ids=[rows[4]['event_id']],reconciliation_id=rid,reviewer='synthetic-native-verifier',reason='Native later exercise offsets prior assigned short; retain original -100 prefix',
            evidence_type='test',evidence_files={'native-events.json':hashlib.sha256(blob).hexdigest()})
        accepted=save(book,'sample',review,frozen,commit=True)
        assert save(book,'sample',review,frozen,commit=True)==accepted and status(book,'sample',end)['status']=='REVIEWED'
        assert monitor(book,'sample',end)['status']=='NO_ACTION'
    cfg=tmp_path/'demo.toml';cfg.write_bytes((Path(__file__).absolute().parents[1]/'configs/demo.toml').read_bytes())
    create_bundle(root,cfg,tmp_path/'bundle');verify_bundle(tmp_path/'bundle','demo');restore_bundle(tmp_path/'bundle',tmp_path/'restored','demo')
    restored=Ledger(tmp_path/'restored/runtime/demo/account.sqlite','demo')
    try:
        assert restored.sequence('sample')==5
        assert D(restored.snapshot('sample',end,{})['settled_cash'])==100386
        assert status(restored,'sample',end)==status(book,'sample',end)
    finally:restored.close();book.close()
