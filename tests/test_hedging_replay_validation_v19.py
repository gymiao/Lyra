import pytest
from personal_quant.common import QuantError,utc
from personal_quant.hedging.execution_replay import validate


@pytest.mark.parametrize('kind',[[],{},None,True,123])
def test_non_string_replay_kind_has_structured_error_before_account_access(kind):
    clock=utc('2024-11-01T20:00:00Z');known=utc('2024-11-04T21:30:00Z')
    request=dict(plan_kind=kind,plan_id='unknown',execution_at=clock.isoformat(),processing_at=known.isoformat())
    with pytest.raises(QuantError) as exc:validate(None,'sample',request,clock,known)
    assert exc.value.code=='INVALID_HEDGE_EXECUTION_REPLAY'
