from pathlib import Path
import pytest
from personal_quant.config import Config
from personal_quant.workspace.service import create
from personal_quant.workspace.capital import preview,validate
from personal_quant.portfolio import Ledger
from personal_quant.common import QuantError
ROOT=Path(__file__).resolve().parents[1]


def setup(tmp_path):
    root=tmp_path/'workspace';create(root,{'schema_version':1,'kind':'options','account_id':'demo-account','initial_cash':'100000'},Config.load(ROOT/'configs/demo.toml'))
    book=Ledger(root/'runtime/demo/account.sqlite','demo')
    book.import_events('demo-account',[{'event_id':'buy','kind':'BUY','symbol':'SPY','quantity':'100','price':'100','fee':'0',
        'effective_at':'2024-07-01T20:30:00Z','settlement_at':'2024-07-02T20:30:00Z','source':'test','evidence_type':'test'}])
    book.close();return root


def claim(name,budget,shares):
    return {'strategy_id':name,'cash_budget':budget,'requirements':{'premium':'100','collateral':'0','fees':'2','buffer':'10'},'coverage_shares':{'SPY':shares}}


def request(rows):return {'schema_version':1,'account_id':'demo-account','as_of':'2024-07-03T20:30:00Z','prices':{'SPY':'100'},'allocations':rows}


def test_two_strategies_cannot_reuse_same_cash_or_hundred_shares(tmp_path):
    root=setup(tmp_path);result=preview(root,request([claim('first','60000','100'),claim('second','40000','100')]))
    assert result['status']=='PREVIEW_ONLY' and result['check_status']=='BLOCKED'
    assert 'SHARED_CASH_EXCEEDED' in result['checks'] and 'SHARED_COVERAGE_EXCEEDED:SPY' in result['checks']
    assert result['available_cash']=='90000' and result['available_shares']=={'SPY':'100'}
    book=Ledger.read_only(root/'runtime/demo/account.sqlite','demo')
    assert book.sequence('demo-account')==2 and not book.connection.execute('SELECT 1 FROM option_plans').fetchone();book.close()


def test_valid_budget_sum_and_new_deposit_invalidate_readonly_preview(tmp_path):
    root=setup(tmp_path);req=request([claim('first','30000','40'),claim('second','20000','60')]);result=preview(root,req)
    assert result['check_status']=='PASSED' and result['unallocated_cash']=='40000'
    assert validate(root,req,result)['status']=='CURRENT'
    book=Ledger(root/'runtime/demo/account.sqlite','demo');book.import_events('demo-account',[{'event_id':'new-deposit','kind':'DEPOSIT','amount':'100',
        'effective_at':'2024-07-03T20:00:00Z','source':'test','evidence_type':'test'}]);book.close()
    assert validate(root,req,result)['status']=='STALE'


def test_understated_requirements_and_duplicate_strategy_are_rejected(tmp_path):
    root=setup(tmp_path);result=preview(root,request([claim('first','100','0')]))
    assert result['check_status']=='BLOCKED' and 'STRATEGY_REQUIREMENT_EXCEEDS_BUDGET' in result['checks']
    with pytest.raises(QuantError):preview(root,request([claim('same','200','0'),claim('same','200','0')]))
