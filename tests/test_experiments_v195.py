from pathlib import Path
from dataclasses import replace
import pytest
from personal_quant.config import Config
from personal_quant.common import QuantError
from personal_quant.workspace.service import create,status,worker
from personal_quant.workspace.experiments import clone,compare

ROOT=Path(__file__).resolve().parents[1]


def test_cloning_creates_independently_funded_account(tmp_path):
    cfg=Config.load(ROOT/'configs/demo.toml')
    spec={'schema_version':1,'account_id':'demo-account','initial_cash':'100000','kind':'etf'}
    first=create(tmp_path/'first',spec,cfg);second=clone(tmp_path/'first',tmp_path/'second')
    assert first['identity']['workspace_id']!=second['identity']['workspace_id']
    assert second['events']==1 and second['identity']['initial_cash']=='100000'
    assert status(tmp_path/'first')['events']==1
    with pytest.raises(QuantError) as caught:compare([{'name':'a','workspace':str(tmp_path/'first'),'run_id':'missing'},{'name':'b','workspace':str(tmp_path/'second'),'run_id':'missing'}])
    assert caught.value.code=='INCOMPLETE_EXPERIMENT'


def test_complete_independent_cash_experiments_compare_without_counting_funding_as_return(tmp_path):
    cfg=replace(Config.load(ROOT/'configs/demo.toml'),evaluation_end='2024-07-03')
    spec={'schema_version':1,'account_id':'demo-account','initial_cash':'100000','kind':'etf'}
    request=[]
    for name in ('baseline','candidate'):
        directory=tmp_path/name
        create(directory,spec,cfg)
        started=worker(directory,'start')
        done=worker(directory,'resume',started['run_id'],'2024-07-03')
        assert done['status']=='COMPLETED' and done['events']==1
        request.append({'name':name,'workspace':str(directory),'run_id':started['run_id']})
    result=compare(request)
    assert result['status']=='PASSED' and result['read_only']
    assert all(metrics['total_return']==0 and metrics['max_drawdown']==0 for metrics in result['metrics'].values())
    assert all(set(values.values())=={100000} for values in result['curves'].values())
    # The reader must reject an extra deposit even if it occurs after the curve.
    from personal_quant.portfolio import Ledger
    book=Ledger(tmp_path/'candidate/runtime/demo/account.sqlite','demo')
    try:book.import_events('demo-account',[{'event_id':'extra','kind':'DEPOSIT','amount':'500','effective_at':'2024-07-05T21:00:00Z','source':'test','evidence_type':'test'}])
    finally:book.close()
    with pytest.raises(QuantError) as caught:compare(request)
    assert caught.value.code=='EXTERNAL_FLOWS_PRESENT'
