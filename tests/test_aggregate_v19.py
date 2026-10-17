from dataclasses import replace
from pathlib import Path
import pytest
from personal_quant.common import QuantError,write_json
from personal_quant.portfolio import Ledger
from personal_quant.portfolio.report import account_report
from personal_quant.portfolio.aggregate import aggregate
from conftest import event


def setup(tmp_path,config,monkeypatch):
    items=[]
    for name,amount in [('alpha',1000),('beta',2000)]:
        root=tmp_path/name;root.mkdir();monkeypatch.chdir(root)
        cfg=replace(config,environment='paper',runtime_dir='runtime/paper');write_json(root/'config.json',cfg.content())
        book=Ledger(Path(cfg.runtime_dir)/'account.sqlite','paper');book.account('sample')
        book.import_events('sample',[event('deposit','DEPOSIT',amount=amount)])
        account_report(book,'sample','2024-07-31T21:00:00Z',{},Path('report'));book.close()
        items.append({'name':name,'workspace':str(root),'config':'config.json','report':'report'})
    return {'schema_version':1,'max_age_seconds':3600,'workspaces':items}


def test_two_independent_paper_accounts_sum_capital_without_profit_or_writes(tmp_path,config,monkeypatch):
    request=setup(tmp_path,config,monkeypatch)
    result=aggregate(request,'2024-07-31T21:30:00Z')
    assert result['status']=='PASSED' and result['read_only']
    assert result['totals']=={'equity':'3000','settled_cash':'3000','net_contributions':'3000','investment_pnl':'0'}
    assert result['return'] is None
    for item in request['workspaces']:
        book=Ledger(Path(item['workspace'])/'runtime/paper/account.sqlite','paper')
        assert book.sequence('sample')==1;book.close()


def test_stale_duplicate_and_changed_ledger_do_not_create_misleading_total(tmp_path,config,monkeypatch):
    request=setup(tmp_path,config,monkeypatch)
    assert aggregate(request,'2024-08-01T21:00:00Z')['totals'] is None
    with pytest.raises(QuantError):aggregate({**request,'workspaces':[request['workspaces'][0]]*2},'2024-07-31T21:30:00Z')
    book=Ledger(Path(request['workspaces'][0]['workspace'])/'runtime/paper/account.sqlite','paper')
    book.import_events('sample',[event('extra','DEPOSIT',amount=100)]);book.close()
    result=aggregate(request,'2024-07-31T21:30:00Z')
    assert result['totals'] is None
    assert 'REPORT_LEDGER_CHANGED' in result['workspaces'][0]['issues']
