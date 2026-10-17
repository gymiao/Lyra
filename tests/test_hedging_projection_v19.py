import pytest
from personal_quant.common import QuantError
from personal_quant.hedging.monitor import require_projected_coverage
from personal_quant.hedging.allocation_store import resources,update
from test_hedging_parent_bindings_v19 import bound_option
from test_hedging_archive_v19 import frozen_risk
from test_hedging_exposure_v19 import risk_market


@pytest.mark.parametrize('quantity',[0,60,99])
def test_reduction_cannot_leave_active_protection_slice_uncovered(bound_option,quantity):
    book,_,req=bound_option;update(book,'sample',req,commit=True)
    before=resources(book,'sample');clock=req['coverage_request']['as_of']
    with pytest.raises(QuantError) as exc:require_projected_coverage(book,'sample',clock,{'SPY':quantity})
    assert exc.value.code=='HEDGE_PROJECTED_COVERAGE'
    assert resources(book,'sample')==before and book.sequence('sample')==3


@pytest.mark.parametrize('quantity',[100,140])
def test_retaining_or_increasing_shares_creates_no_second_reservation(bound_option,quantity):
    book,_,req=bound_option;update(book,'sample',req,commit=True);before=resources(book,'sample')
    result=require_projected_coverage(book,'sample',req['coverage_request']['as_of'],{'SPY':quantity,'IEF':5})
    assert result['required_shares']=={'SPY':'100'} and not result['creates_reservations']
    assert resources(book,'sample')==before and book.sequence('sample')==3


def test_explicit_retirement_allows_reduction_but_preserves_actual_option(bound_option):
    book,_,req=bound_option;first=update(book,'sample',req,commit=True)
    retired=dict(req,request_id='retire',expected_version=first['version_hash'],
        expected_resource_hash=resources(book,'sample'),changes=[],retire_ids=['protection'],parent_versions={})
    update(book,'sample',retired,commit=True)
    result=require_projected_coverage(book,'sample',req['coverage_request']['as_of'],{'SPY':60})
    assert result['required_shares']=={} and book.sequence('sample')==3
    assert book.snapshot('sample',req['coverage_request']['as_of'])['option_positions']


def test_omitted_position_is_not_silently_assumed_zero(bound_option):
    book,_,req=bound_option;update(book,'sample',req,commit=True)
    with pytest.raises(QuantError) as exc:require_projected_coverage(book,'sample',req['coverage_request']['as_of'],{})
    assert exc.value.code=='INVALID_PROJECTED_POSITIONS'

