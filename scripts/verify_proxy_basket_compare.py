"""Public CLI proof: two stock holdings and a distinct synthetic proxy put."""
import argparse,json,os,subprocess,sys
from pathlib import Path
from personal_quant.common import decimal as D
from personal_quant.options.monthly_report import load_monthly_report
from personal_quant.strategies.archive import source_fingerprint


def main():
    p=argparse.ArgumentParser();p.add_argument('--workspace',type=Path,required=True)
    p.add_argument('--engine-root',type=Path,required=True);p.add_argument('--dotnet',type=Path,required=True)
    args=p.parse_args();root=args.workspace.absolute();root.mkdir(parents=True,exist_ok=False)
    project=Path(__file__).absolute().parents[1];sys.path.insert(0,str(project/'tests'))
    from test_options_monthly_replay_v19 import monthly_signals
    from test_options_monthly_path_v19 import execution
    signals=monthly_signals(root,'long_put',underlying='GLD');path,days,*_=execution(signals)
    path['stocks']['GLD']={str(day.date()):str(D(100)+D(i)*D('.1')) for i,day in enumerate(days)}
    request=dict(signals=signals,packages=[2,3],stock_basket={'SPY':60,'IEF':50},execution_path=path)
    (root/'request.json').write_text(json.dumps(request));(root/'demo.toml').write_bytes((project/'configs/demo.toml').read_bytes())
    fingerprint=source_fingerprint()
    command=[sys.executable,'-m','personal_quant.cli','--config','demo.toml','options','--action','monthly-compare',
        '--file','request.json','--engine-root',str(args.engine_root.absolute()),'--dotnet',str(args.dotnet.absolute()),
        '--destination',str(root/'comparison'),'--capital','100000','--fee-per-contract','2','--stock-commission-bps','2']
    result=subprocess.run(command,cwd=root,capture_output=True,text=True,env=dict(os.environ,PYTHONPATH=str(project/'src')))
    (root/'stdout.json').write_text(result.stdout);(root/'stderr.log').write_text(result.stderr)
    assert result.returncode==0,result.stderr
    report=load_monthly_report(root/'comparison');assert report==json.loads(result.stdout)
    control=json.loads((root/'comparison/stock/verification.json').read_text());stock_pnl=D(0);put_pnl=D(0)
    for i,cycle in enumerate(control['cycles']):
        assert cycle['stock_positions']==request['stock_basket'] and cycle['underlying_shares']==0
        entry=cycle['entry_submit_at'][:10];exit=cycle['exit_submit_at'][:10]
        for symbol,quantity in request['stock_basket'].items():
            buy=D(path['stocks'][symbol][entry]);sell=D(path['stocks'][symbol][exit])
            stock_pnl+=quantity*(sell-buy)-quantity*(buy+sell)*D('.0002')
        identity=signals[i]['selection']['legs'][0]['contract']['contract_id'];n=request['packages'][i]
        put_pnl+=100*n*(D(path['options'][identity][exit]['bid'])-D(path['options'][identity][entry]['ask']))-4*n
    assert abs(D(control['actual_equity'])-D(100000)-stock_pnl)<=D('.01')
    assert abs(D(report['comparison']['strategy_vs_stock_pnl'])-put_pnl)<D('.000001')
    assert report['metrics']['cash']['total_return']==0
    assert source_fingerprint()==fingerprint==report['source_fingerprint']
    proof=dict(status='PASSED',source_fingerprint=fingerprint,checks=1,command=command,exit_code=0,
        data_type='synthetic_variable_path',stock_basket=request['stock_basket'],option_underlying='GLD',
        independent_stock_pnl=str(stock_pnl),independent_option_increment=str(put_pnl),
        no_user_account_writes=True,report=str(root/'comparison/report.md'))
    (root/'verification.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2))
    print(json.dumps(proof,ensure_ascii=False))


if __name__=='__main__':main()
