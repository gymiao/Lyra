from copy import deepcopy
import pytest
from personal_quant.common import QuantError,decimal as D
from personal_quant.hedging.stock_units import quantity,stage_quantities


def split(identity,seq,date,ratio,symbol='SPY'):
    return dict(kind='SPLIT',event_id=identity,seq=seq,effective_at=date,symbol=symbol,ratio=ratio,plan_id='')


def test_partial_receipts_before_and_after_split_use_their_own_units():
    events=[dict(kind='SELL',event_id='before',seq=3,effective_at='2025-01-16T21:00:00Z',symbol='SPY',quantity='20',plan_id='sale'),
        split('two-for-one',4,'2025-01-17T14:30:00Z','2'),
        dict(kind='SELL',event_id='after',seq=5,effective_at='2025-01-17T21:00:00Z',symbol='SPY',quantity='10',plan_id='sale')]
    result=stage_quantities(events,'sale',[dict(symbol='SPY',side='SELL',quantity='40')],'2025-01-15T21:30:00Z','2025-01-17T21:30:00Z',origin_seq=2)
    assert result['expected']=={('SPY','SELL'):D(80)}
    assert result['filled']=={('SPY','SELL'):D(50)} and result['remaining']=={('SPY','SELL'):D(30)}
    assert [a['event_id'] for a in result['actions']]==['two-for-one']
    # Target 40 old shares: first 20 old shares become 40, then 10 new shares.
    # Fees/cash are financial facts and are absent from the unit transformation.
    assert events[0]['quantity']=='20' and events[-1]['quantity']=='10'


def test_reverse_split_preserves_fractional_tail_without_lot_rounding():
    events=[split('reverse',3,'2025-01-17T14:30:00Z','.5')]
    result=quantity(events,'SPY',41,'2025-01-15T21:30:00Z','2025-01-17T21:30:00Z',origin_seq=2)
    assert D(result['quantity'])==D('20.5') and D(result['factor'])==D('.5')


def test_future_and_other_stock_actions_do_not_change_current_units():
    events=[split('known',3,'2025-01-17T14:30:00Z','2'),split('other',4,'2025-01-17T14:30:00Z','3','IEF'),split('future',5,'2025-01-23T14:30:00Z','10')]
    old=quantity(events,'SPY',40,'2025-01-15T21:30:00Z','2025-01-17T21:30:00Z',origin_seq=2)
    changed=deepcopy(events);changed[-1]['ratio']='1000'
    assert quantity(changed,'SPY',40,'2025-01-15T21:30:00Z','2025-01-17T21:30:00Z',origin_seq=2)==old
    assert D(old['quantity'])==80


def test_same_timestamp_uses_ledger_order_and_rejects_unknown_origin():
    clock='2025-01-17T14:30:00Z';events=[split('split',4,clock,2)]
    assert D(quantity(events,'SPY',20,clock,clock,origin_seq=3)['quantity'])==40
    assert D(quantity(events,'SPY',20,clock,clock,origin_seq=5)['quantity'])==20
    with pytest.raises(QuantError) as exc:quantity(events,'SPY',20,clock,clock)
    assert exc.value.code=='AMBIGUOUS_UNIT_TIME'


def test_completed_direction_stays_completed_after_split():
    events=[dict(kind='SELL',event_id='filled',seq=3,effective_at='2025-01-16T21:00:00Z',symbol='SPY',quantity='40',plan_id='sale'),split('split',4,'2025-01-17T14:30:00Z',2)]
    value=stage_quantities(events,'sale',[dict(symbol='SPY',side='SELL',quantity=40)],'2025-01-15T21:30:00Z','2025-01-17T21:30:00Z',origin_seq=2)
    assert value['remaining']=={} and value['filled']==value['expected']


@pytest.mark.parametrize('problem,code',[('duplicate','DUPLICATE_UNIT_FACT'),('ratio','INVALID_UNIT_RATIO'),('oversold','UNRESOLVED_HEDGE_EXECUTION')])
def test_invalid_unit_facts_do_not_create_a_remaining_target(problem,code):
    events=[split('split',4,'2025-01-17T14:30:00Z',2)]
    if problem=='duplicate':events.append(deepcopy(events[0]))
    if problem=='ratio':events[0]['ratio']=0
    if problem=='oversold':events.append(dict(kind='SELL',event_id='excess',seq=5,effective_at='2025-01-17T21:00:00Z',symbol='SPY',quantity=81,plan_id='sale'))
    with pytest.raises(QuantError) as exc:stage_quantities(events,'sale',[dict(symbol='SPY',side='SELL',quantity=40)],'2025-01-15T21:30:00Z','2025-01-17T21:30:00Z',origin_seq=2)
    assert exc.value.code==code


def test_legacy_stage_unknown_prefix_is_preserved_and_same_clock_split_blocked():
    from personal_quant.hedging.stock_units import stage_basis
    stage=dict(lines=[dict(symbol='SPY',side='SELL',quantity=40)])
    body=dict(as_of='2025-01-17T14:30:00Z')
    clock,seq=stage_basis(stage,body)
    assert seq is None and clock==body['as_of']
    events=[split('same-clock',4,clock,2)]
    with pytest.raises(QuantError) as exc:quantity(events,'SPY',40,clock,clock,origin_seq=seq)
    assert exc.value.code=='AMBIGUOUS_UNIT_TIME'


def test_deleted_original_clock_is_not_replaced_by_current_time():
    from personal_quant.hedging.stock_units import stage_basis
    with pytest.raises(QuantError) as exc:stage_basis({},dict(sizing={}))
    assert exc.value.code=='INVALID_STOCK_UNIT_BASIS'
