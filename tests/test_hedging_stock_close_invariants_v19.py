import json
from copy import deepcopy
import pytest
from personal_quant.common import QuantError,canonical,digest
from personal_quant.hedging.groups import save,history
from personal_quant.hedging.allocation_store import resources
from test_hedging_groups_v19 import request,native_stock
from test_hedging_archive_v19 import frozen_risk
from test_hedging_exposure_v19 import risk_market


def two_exits(fixture):
    book,*_=fixture;_,req=request(fixture)
    native_stock(book,'close-one',side='BUY');native_stock(book,'close-two',side='BUY')
    req['expected_resource_hash']=resources(book,'sample')
    exits=[dict(stage_id=name,plan_kind='stock',plan_id=plan,action='CLOSE',depends_on=['sale'])
        for name,plan in [('restore','close-one'),('restore-again','close-two')]]
    return req,exits


def test_two_reverse_plans_cannot_each_consume_same_original_stock_obligation(frozen_risk):
    book,*_=frozen_risk;req,exits=two_exits(frozen_risk);before=resources(book,'sample')
    req['stages']+=exits
    with pytest.raises(QuantError) as exc:save(book,'sample',req,commit=True)
    assert exc.value.code=='DUPLICATE_HEDGE_CLOSE'
    assert history(book,'sample')==[] and resources(book,'sample')==before and book.sequence('sample')==2


def test_rehashed_archive_cannot_introduce_second_reverse_obligation(frozen_risk):
    book,*_=frozen_risk;req,exits=two_exits(frozen_risk);req['stages'].append(exits[0])
    group=save(book,'sample',req,commit=True)
    task=book.connection.execute("SELECT task_id,details FROM tasks WHERE task_id LIKE 'hedge-group:%'").fetchone()
    forged=json.loads(task['details']);new=deepcopy(forged['stages'][-1]);new.update(exits[1])
    native=dict(book.connection.execute('SELECT * FROM plans WHERE plan_id=?',('close-two',)).fetchone())
    new['initial_plan_hash']=digest(native);forged['stages'].append(new);forged['request']['stages'].append(exits[1])
    forged['group_basis']['stages']=forged['stages'];forged['group_id']=digest(forged['group_basis'])
    forged['request_hash']=digest(forged['request']);forged['record_hash']=digest({k:v for k,v in forged.items() if k!='record_hash'})
    book.connection.execute('UPDATE tasks SET details=? WHERE task_id=?',(canonical(forged),task['task_id']))
    with pytest.raises(QuantError) as exc:history(book,'sample')
    assert exc.value.code=='CORRUPT_HEDGE_GROUP' and book.sequence('sample')==2
    assert isinstance(exc.value.__cause__,QuantError) and exc.value.__cause__.code=='DUPLICATE_HEDGE_CLOSE'


@pytest.mark.parametrize('field,value',[('historical_slice',True),('native_lines',[]),('close_obligation_id','forged')])
def test_rehashed_root_cannot_claim_revision_only_stage_flags(frozen_risk,field,value):
    book,*_=frozen_risk;_,req=request(frozen_risk);save(book,'sample',req,commit=True)
    r=book.connection.execute("SELECT task_id,details FROM tasks WHERE task_id LIKE 'hedge-group:%'").fetchone()
    forged=json.loads(r['details']);forged['stages'][0][field]=value
    forged['group_basis']['stages']=forged['stages'];forged['group_id']=digest(forged['group_basis'])
    forged['record_hash']=digest({k:v for k,v in forged.items() if k!='record_hash'})
    book.connection.execute('UPDATE tasks SET details=? WHERE task_id=?',(canonical(forged),r['task_id']))
    from personal_quant.hedging.stage_gate import require_for_plan
    with pytest.raises(QuantError) as exc:require_for_plan(book,'sample','stock',req['stages'][0]['plan_id'],'OPEN','2025-01-17T21:30:00Z')
    assert exc.value.code=='CORRUPT_HEDGE_GROUP' and str(exc.value.__cause__)=='root stage contract'
