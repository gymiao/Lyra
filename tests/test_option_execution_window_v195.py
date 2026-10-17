import pytest
from personal_quant.options.execution_window import assess
from personal_quant.common import QuantError

MONTHLY={'decision_at':'2024-11-29T18:30:00Z','applicable_session':'2024-12-02'}


def authority(day='2024-12-03',at='2024-12-03T20:40:00Z',until='2024-12-03T21:00:00Z',maximum=5):
    return {'as_of':at,'valid_until':until,'execution_window':{'session':day,'maximum_sessions':maximum}}


def test_delay_requires_explicit_window_and_uses_current_session_close():
    current=authority()
    assert assess(MONTHLY,current,'demo')['checks']==[]
    assert assess(MONTHLY,{k:v for k,v in current.items() if k!='execution_window'},'demo')['checks']==['INVALID_EXECUTION_WINDOW']
    assert assess(MONTHLY,current,'real')['checks']==['DEFERRED_EXECUTION_DEMO_ONLY']
    assert assess(MONTHLY,current,'paper')['checks']==['DEFERRED_EXECUTION_DEMO_ONLY']


@pytest.mark.parametrize('body',[
    authority(maximum=1),
    authority(day='2024-12-09',at='2024-12-09T20:40:00Z',until='2024-12-09T21:00:00Z'),
    authority(day='2024-12-07',at='2024-12-07T20:40:00Z',until='2024-12-07T21:00:00Z'),
    authority(at='2024-12-03T20:40:01Z'),
    authority(until='2024-12-02T21:00:00Z'),
    authority(maximum=100),
])
def test_late_non_session_overlong_or_wrong_deadline_is_blocked(body):
    assert 'INVALID_EXECUTION_WINDOW' in assess(MONTHLY,body,'demo')['checks']


@pytest.mark.parametrize('maximum',[0,-1,True,1.5,'5'])
def test_window_length_is_a_positive_integer(maximum):
    with pytest.raises(QuantError) as caught:assess(MONTHLY,authority(maximum=maximum),'demo')
    assert caught.value.code=='INVALID_OPTION_EXECUTION_WINDOW'


def test_early_close_window_uses_calendar_and_does_not_mutate_frozen_signal():
    monthly={'decision_at':'2024-10-31T20:30:00Z','applicable_session':'2024-11-01'}
    body=authority(day='2024-11-29',at='2024-11-29T17:40:00Z',until='2024-11-29T18:00:00Z',maximum=20)
    assert assess(monthly,body,'demo')['checks']==[]
    assert monthly=={'decision_at':'2024-10-31T20:30:00Z','applicable_session':'2024-11-01'}
