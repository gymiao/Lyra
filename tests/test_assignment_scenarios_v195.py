import pytest
from personal_quant.common import QuantError
from personal_quant.data.calendar import Calendar
from personal_quant.options.assignment_scenarios import validate


def test_assignment_fault_schema_and_quantity_boundary():
    calendar=Calendar.market('2024-11-01','2024-12-03')
    cycles=[{'entry_submit_at':'2024-11-01T15:40:00','exit_submit_at':'2024-11-21T15:40:00',
             'legs':[{'contract_id':'put','quantity':-2,'expiry':'2024-11-20',
                      'right':'PUT','strike':95,'underlying':'SPY'}]}]
    row={'contract_id':'put','session':'2024-11-08','quantity':1}
    assert validate([row],cycles,calendar,through='2024-11-11',synthetic=True)[0]['quantity']==1
    for change in ({'quantity':3},{'quantity':True},{'quantity':0},{'session':'2024-11-09'},
                   {'session':'2024-11-01'},{'session':'2024-11-20'},{'contract_id':'unknown'}):
        with pytest.raises(QuantError) as error:
            validate([{**row,**change}],cycles,calendar,through='2024-11-11',synthetic=True)
        assert error.value.code=='INVALID_ASSIGNMENT_SCENARIO'
    with pytest.raises(QuantError):validate([row,row],cycles,calendar,through='2024-11-11',synthetic=True)
    with pytest.raises(QuantError):validate([row],cycles,calendar,through=None,synthetic=True)
    with pytest.raises(QuantError):validate([row],cycles,calendar,through='2024-11-11',synthetic=False)


def test_native_assignment_quantity_mismatch_is_rejected_before_ledger():
    from personal_quant.options.assignment_scenarios import validate_native
    from personal_quant.options.contracts import OptionContract
    # Independent explicit terms, no native engine outputs reused as expectation.
    c=OptionContract.from_dict({'contract_id':'test-put','underlying':'SPY',
        'currency':'USD','right':'PUT','style':'AMERICAN','settlement':'PHYSICAL','strike':'95',
        'expiry':'2026-10-16','quote_multiplier':100,'exercise_cash':'9500','deliverable_shares':100,
        'listed_at':'2026-09-01T13:30:00Z','last_trade_at':'2026-10-16T20:00:00Z',
        'exercise_cutoff_at':'2026-10-16T21:30:00Z','evidence_hash':'synthetic-test','deliverable_cash':0,'tick_size':'.01','revision':'test/1'})
    row={'contract_id':c.contract_id,'session':'2026-10-09','quantity':1}
    native={'order_type':'OptionExercise','symbol':'put','order_symbol':'put',
        'tag':'SYNTHETIC_EXPLICIT_PARTIAL_ASSIGNMENT','underlying':'SPY','expiry':c.expiry,'right':'PUT',
        'strike':95,'assignment':True,'in_the_money':True,'quantity':1,'utc_time':'2026-10-09T19:00:00Z'}
    validate_native([row],[native],{c.contract_id:c})
    for events in ([{**native,'quantity':2}],[native,native],[],[{**native,'assignment':False}]):
        with pytest.raises(QuantError) as error:validate_native([row],events,{c.contract_id:c})
        assert error.value.code=='LEAN_ASSIGNMENT_SCENARIO_MISMATCH'
