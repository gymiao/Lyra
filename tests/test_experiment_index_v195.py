import json
from pathlib import Path
import pytest
from personal_quant.common import QuantError
from personal_quant.config import Config
from personal_quant.portfolio import Ledger
from personal_quant.portfolio.backup import restore_bundle
from personal_quant.workspace.service import create,worker,status
from personal_quant.workspace.experiment_index import index,annotate,export

ROOT=Path(__file__).resolve().parents[1]


def workspace(tmp_path,kind):
    root=tmp_path/kind
    create(root,{'schema_version':1,'kind':kind,'account_id':'demo-account','initial_cash':'100000'},Config.load(ROOT/'configs/demo.toml'))
    return root


def test_mixed_explicit_index_filters_and_reports_missing_workspace_without_writes(tmp_path):
    etf=workspace(tmp_path,'etf');options=workspace(tmp_path,'options')
    result=index({'workspaces':[str(etf),str(options),str(etf),str(tmp_path/'missing')]})
    assert result['read_only'] and result['status']=='PARTIAL' and len(result['errors'])==1
    assert len(result['experiments'])==2 and {r['kind'] for r in result['experiments']}=={'etf','options'}
    assert {r['status'] for r in result['experiments']}=={'NOT_STARTED'}
    filtered=index({'workspaces':[str(etf),str(options)],'filters':{'kind':'options','data_type':'synthetic'}})
    assert len(filtered['experiments'])==1 and filtered['experiments'][0]['workspace']==str(options)
    assert status(etf)['events']==status(options)['events']==1


def test_notes_are_bound_to_run_idempotent_conflicting_note_refused_and_export_restores(tmp_path):
    root=workspace(tmp_path,'etf');run=worker(root,'start')
    request={'run_id':run['run_id'],'request_id':'predeclared-research-purpose','note':'机械验证；不按最终收益挑参数'}
    assert not annotate(root,request)['repeated']
    assert annotate(root,request)['repeated']
    with pytest.raises(QuantError) as caught:annotate(root,{**request,'note':'changed'})
    assert caught.value.code=='EXPERIMENT_NOTE_CONFLICT'
    rows=index({'workspaces':[str(root)]})['experiments']
    assert len(rows)==1 and rows[0]['notes'][0]['note']==request['note']
    result=export(root,run['run_id'],tmp_path/'export')
    assert result['data_type']=='synthetic_simulation_bundle'
    restored=tmp_path/'restored';recovery=restore_bundle(tmp_path/'export',restored,'demo')
    recovered=index({'workspaces':[str(restored)]})
    assert recovered['experiments'][0]['notes']==rows[0]['notes']
    assert recovered['experiments'][0]['run_id']==run['run_id']
    book=Ledger(restored/Config.load(recovery['config']).runtime_dir/'account.sqlite','demo')
    assert book.sequence('demo-account')==1;book.close()
    with pytest.raises(QuantError) as caught:export(root,'unknown',tmp_path/'invalid-export')
    assert caught.value.code=='UNKNOWN_SIMULATION'


def test_index_cli_and_note_validation(tmp_path,capsys):
    from personal_quant.cli import main
    root=workspace(tmp_path,'etf');request=tmp_path/'index.json'
    request.write_text(json.dumps({'workspaces':[str(root)]}))
    assert main(['experiment','list','--file',str(request)])==0
    assert json.loads(capsys.readouterr().out)['experiments'][0]['status']=='NOT_STARTED'
    for body in [{},{'workspaces':[]},{'workspaces':[str(root)],'filters':{'unknown':'x'}}]:
        with pytest.raises(QuantError):index(body)
    for body in [{},{'run_id':'unknown','request_id':'x','note':''}]:
        with pytest.raises(QuantError) as caught:annotate(root,body)
        assert caught.value.code=='INVALID_EXPERIMENT_NOTE'


@pytest.mark.parametrize('filters',[{'start_on_or_after':'2025-02-30'},{'end_on_or_before':'2024/12/31'},
    {'start_on_or_after':'2025-01-01','end_on_or_before':'2024-01-01'}])
def test_invalid_period_filter_is_rejected_before_reading_any_workspace(filters):
    with pytest.raises(QuantError) as caught:index({'workspaces':['/missing'],'filters':filters})
    assert caught.value.code=='INVALID_EXPERIMENT_INDEX'
