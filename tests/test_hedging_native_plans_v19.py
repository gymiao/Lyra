import pytest
from personal_quant.common import QuantError
from personal_quant.hedging.native_plans import save,validate_references
from personal_quant.hedging.allocation_store import resources
from test_hedging_groups_v19 import request as original
from test_hedging_archive_v19 import frozen_risk
from test_hedging_exposure_v19 import risk_market


def request(fixture):
    book,*_=fixture;parent,group=original(fixture)
    return dict(schema_version=1,request_id='native',hedge_id=parent['hedge_id'],parent_version=parent['version_hash'],
        expected_resource_hash=resources(book,'sample'),as_of=parent['decision_at'],option_risk=None,
        stock_stages=group['stages'],include_option_close=False,reason='Explicit existing synthetic stock native reference')


def test_preview_and_stock_binding_do_not_generate_fake_fills(frozen_risk):
    book,*_=frozen_risk;req=request(frozen_risk);before=resources(book,'sample')
    assert save(book,'sample',req)['status']=='PREVIEW' and resources(book,'sample')==before
    generated=save(book,'sample',req,commit=True)
    assert generated['option_plan_id'] is None and len(generated['group']['stages'])==1
    assert generated['creates_reservations'] is False and book.sequence('sample')==2
    assert save(book,'sample',req,commit=True)==generated
    validate_references(book)


@pytest.mark.parametrize('change,code',[
    ({'expected_resource_hash':'old'},'STALE_HEDGE_RESOURCES'),
    ({'stock_stages':[]},'HEDGE_CANDIDATE_PLAN_MISMATCH'),
    ({'option_risk':{}},'INVALID_NATIVE_HEDGE_PLANS'),
    ({'as_of':'2025-02-01T21:30:00Z'},'HEDGE_INTENT_EXPIRED')])
def test_invalid_native_generation_is_atomic(frozen_risk,change,code):
    book,*_=frozen_risk;req=request(frozen_risk);before=resources(book,'sample')
    with pytest.raises(QuantError) as exc:save(book,'sample',{**req,**change},commit=True)
    assert exc.value.code==code and resources(book,'sample')==before


def test_external_capital_does_not_revive_old_unsubmitted_parent(frozen_risk):
    from conftest import event
    book,*_=frozen_risk;req=request(frozen_risk)
    book.import_events('sample',[event('later-deposit','DEPOSIT',amount=100)])
    req['expected_resource_hash']=resources(book,'sample')
    with pytest.raises(QuantError) as exc:save(book,'sample',req,commit=True)
    assert exc.value.code=='HEDGE_CAPITAL_CHANGED'
