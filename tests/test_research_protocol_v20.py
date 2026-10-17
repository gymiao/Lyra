from copy import deepcopy
import pytest
from personal_quant.common import QuantError
from personal_quant.workspace.research_protocol import normalize


def specification():
    return {'schema_version':1,'question':'预声明固定规则在分离窗口和费用压力下的差异',
        'input_bundle':'/tmp/example','initial_cash':100000,'templates':['long_call'],
        'windows':[{'name':'dev','purpose':'development','decision_start':'2024-01-01','decision_end':'2024-03-31'},
                   {'name':'evaluation','purpose':'assessment','decision_start':'2024-04-01','decision_end':'2024-07-31'}],
        'costs':[{'name':'base','fee_per_contract':2,'stock_commission_bps':2,'spread_multiplier':1}],
        'selection_parameters':{'long_call':{}},'packages':1,'exit_policy':'scheduled_close','cash_interest':0}


def test_research_windows_reject_overlap_reversed_purpose_and_implicit_exit():
    spec=specification();assert normalize(spec)==spec
    for change in ['overlap','purpose','exit','cost']:
        bad=deepcopy(spec)
        if change=='overlap':bad['windows'][1]['decision_start']='2024-03-01'
        elif change=='purpose':bad['windows'][0]['purpose']='assessment'
        elif change=='exit':bad['exit_policy']='guess'
        else:bad['costs'][0]['fee_per_contract']=-1
        with pytest.raises(QuantError):normalize(bad)


def test_missing_calendar_decision_cannot_disappear_from_coverage_denominator():
    from personal_quant.data.calendar import Calendar
    from personal_quant.workspace.research_protocol import coverage
    calendar=Calendar.market('2024-01-01','2024-04-02')
    window={'decision_start':'2024-01-01','decision_end':'2024-03-31'}
    result=coverage(calendar,[{'decision_session':'2024-01-31'},{'decision_session':'2024-03-28'}],window)
    assert result['candidate_decisions']==3 and result['covered_decisions']==2
    assert result['missing_decisions']==['2024-02-29'] and not result['complete']
    assert result['coverage_fraction']==2/3
