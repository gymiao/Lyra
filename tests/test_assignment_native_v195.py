from native_tools import native_engine_root,native_dotnet
import json
import os
from pathlib import Path
import pytest
from personal_quant.common import QuantError,decimal as D,write_json
from personal_quant.config import Config
from personal_quant.portfolio import Ledger
from personal_quant.portfolio.backup import create_bundle,restore_bundle
from personal_quant.options.monthly_replay import monthly_replay
from personal_quant.options.wheel import decision
from personal_quant.workspace.service import create,worker
from test_wheel_native_v195 import wheel_inputs
from test_options_monthly_replay_v19 import monthly_signals
from test_options_monthly_natural_v19 import natural_path

ROOT=Path(__file__).resolve().parents[1]
ENGINE=Path(os.environ.get('LYRAX_TEST_ENGINE_ROOT',str(native_engine_root())))
DOTNET=Path(os.environ.get('LYRAX_TEST_DOTNET',str(native_dotnet())))


def test_native_partial_wheel_assignment_backup_and_unknown_action_block(tmp_path,monkeypatch):
    signals,path=wheel_inputs(tmp_path/'signals',True)
    put=signals[0]['selection']['legs'][0]['contract']['contract_id']
    for day in path['stocks']['SPY']:
        if '2024-11-07'<=day<'2024-11-20':
            path['stocks']['SPY'][day]='90';path['options'][put][day]={'bid':'5','ask':'5.1'}
        elif day=='2024-11-20':
            path['stocks']['SPY'][day]='100';path['options'][put][day]={'bid':'.01','ask':'.11'}
    request=tmp_path/'request.json'
    write_json(request,{'signals':signals,'packages':[2,2],'stock_basket':{},'execution_path':path,
                       'wheel':True,'wheel_end_session':'2024-12-19',
                       'assignment_scenarios':[{'contract_id':put,'session':'2024-11-08','quantity':1}]})
    root=tmp_path/'workspace'
    create(root,{'schema_version':1,'kind':'options','account_id':'demo-account','initial_cash':'100000'},Config.load(ROOT/'configs/demo.toml'))
    run=worker(root,'start',input_file=request,engine_root=ENGINE,dotnet=DOTNET,fee_per_contract=2)
    part=worker(root,'step',run['run_id'],'2024-11-11')
    assert part['events']==3
    receipts=part['details']['lifecycle_receipts']
    assert len(receipts)==1 and receipts[0]['kind']=='OPTION_ASSIGNMENT'
    book=Ledger.read_only(root/'runtime/demo/account.sqlite','demo')
    state=book.snapshot('demo-account',part['details']['as_of'],part['details']['prices'])
    assert state['positions']=={'SPY':'100'} and state['option_positions']=={put:'-1'}
    assert D(state['settled_cash'])==D('90696') and D(state['equity'])==D('99191')
    assert decision(book,'demo-account',part['details']['as_of'],{'underlying':'SPY','packages':2,'cash_buffer':10})['phase']=='PUT_OPEN'
    book.close()
    assert worker(root,'resume',run['run_id'],'2024-11-11')['repeated']
    monkeypatch.chdir(root);create_bundle(root/'runtime/demo',root/'config.json',tmp_path/'bundle')
    recovered=tmp_path/'recovered';restore_bundle(tmp_path/'bundle',recovered,'demo')
    expired=worker(recovered,'resume',run['run_id'],'2024-11-25')
    assert expired['events']==4
    book=Ledger(recovered/'runtime/demo/account.sqlite','demo')
    state=decision(book,'demo-account',expired['details']['as_of'],{'underlying':'SPY','packages':2,'cash_buffer':10})
    assert state['phase']=='STOCK' and state['status']=='BLOCKED' and 'INSUFFICIENT_COVERED_SHARES' in state['checks']
    # Corporate/fee facts after the native prefix must remain factual; no
    # synthetic lot rounding or old-world replay may overwrite them.
    book.import_events('demo-account',[
        {'event_id':'fractional-split','kind':'SPLIT','symbol':'SPY','ratio':'.995','source':'synthetic_action_receipt',
         'evidence_type':'test','effective_at':'2024-11-25T20:00:00Z'},
        {'event_id':'extra-fee','kind':'FEE','amount':1,'source':'synthetic_action_receipt',
         'evidence_type':'test','effective_at':'2024-11-25T20:00:00Z'}])
    fraction=decision(book,'demo-account','2024-11-25T21:00:00Z',{'underlying':'SPY','packages':1,'cash_buffer':10})
    assert 'NONSTANDARD_WHEEL_SHARES' in fraction['checks'] and fraction['status']=='BLOCKED'
    assert book.snapshot('demo-account','2024-11-25T21:00:00Z')['positions']=={'SPY':'99.500'}
    assert D(book.snapshot('demo-account','2024-11-25T21:00:00Z')['settled_cash'])==D('90695')
    from personal_quant.workspace import options_runner
    def forbidden(*a,**kw):raise AssertionError('changed account reached native engine')
    monkeypatch.setattr(options_runner,'monthly_replay',forbidden)
    monkeypatch.chdir(recovered)
    with pytest.raises(QuantError) as changed:options_runner.run('resume',run['run_id'],'2024-12-02')
    assert changed.value.code=='SIMULATION_EXTERNAL_FACTS'
    # A factual unknown action is retained without turning it into an invented
    # split, cash flow or native fill. Even study replay must now stop.
    from personal_quant.options.ledger import import_facts
    raw={'event_id':'unknown-action','kind':'UNKNOWN_OPTION_ACTION','contract_version':'',
         'quantity':1,'position_side':'SHORT','source':'synthetic_action_receipt','evidence_type':'test','effective_at':'2024-11-25T20:00:00Z'}
    raw['contract_version']=book.connection.execute('SELECT version_hash FROM option_contracts WHERE contract_id=?',(put,)).fetchone()[0]
    import_facts(book,'demo-account',[raw],expected_sequence=6)
    import_facts(book,'demo-account',[raw],expected_sequence=6)
    assert book.sequence('demo-account')==6
    assert book.connection.execute('SELECT count(*) FROM pending_option_events').fetchone()[0]==1
    book.close()
    def forbidden(*a,**kw):raise AssertionError('unresolved action reached native engine')
    monkeypatch.setattr('personal_quant.workspace.options_runner.monthly_replay',forbidden)
    from personal_quant.workspace import options_runner
    monkeypatch.chdir(recovered)
    with pytest.raises(QuantError) as error:
        options_runner.run('resume',run['run_id'],'2024-12-02')
    assert error.value.code=='UNRESOLVED_ACCOUNT_FACTS'


@pytest.mark.parametrize('template',['covered_call','collar'])
def test_intermediate_call_assignment_retains_receipt_and_blocks_uncovered_roll(tmp_path,template):
    signals=monthly_signals(tmp_path/'signals',template)
    path=natural_path(signals,100)
    leg=next(l for l in signals[0]['selection']['legs'] if l['contract']['right']=='CALL')
    identity=leg['contract']['contract_id']
    for day in path['stocks']['SPY']:
        if day>='2024-11-14':path['stocks']['SPY'][day]='110'
    scenario=[{'contract_id':identity,'session':'2024-11-15','quantity':1}]
    def run(end,name):
        known=[s for s in signals if s['decision_at'][:10]<=end]
        ids={l['contract']['contract_id'] for s in known for l in s['selection']['legs']}
        clipped={**path,'stocks':{s:{d:p for d,p in rows.items() if d<=end} for s,rows in path['stocks'].items()},
                 'options':{s:{d:p for d,p in rows.items() if d<=end} for s,rows in path['options'].items() if s in ids}}
        return monthly_replay(ENGINE,DOTNET,tmp_path/name,known,initial_cash=100000,fee_per_contract=2,
            stock_commission_bps=2,execution_path=clipped,retain_stock=True,rolling_end_session='2025-01-10',
            through=end,assignment_scenarios=scenario)
    proof=run('2024-11-18','partial')
    assert proof['ledger_bridge']['positions']=={}
    assert len(proof['lifecycle_receipts'])==1 and proof['lifecycle_receipts'][0]['kind']=='OPTION_ASSIGNMENT'
    assert D(proof['ledger_bridge']['settled_cash'])==(D('100596') if template=='covered_call' else D('100484'))
    with pytest.raises(QuantError) as error:run('2024-12-03','failed-roll')
    assert error.value.code=='LEAN_REPLAY_FAILED'
    native=json.loads((tmp_path/'failed-roll/engine-events.json').read_text())
    assert any(e['assignment'] and e['right']=='CALL' for e in native)
    stock_buys=[e for e in native if e['right'] is None and e['quantity']>0 and e['order_type']=='MarketOnClose']
    assert len(stock_buys)==1 and stock_buys[0]['quantity']==100
    assert not any(e['tag']==signals[1]['monthly_signal_id']+'|OPEN' for e in native)
