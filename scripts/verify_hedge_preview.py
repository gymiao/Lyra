"""Actual read-only hedge-preview CLI checks using an archived synthetic risk."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from personal_quant.hedging.archive import load
from personal_quant.portfolio import Ledger
from personal_quant.strategies.archive import source_fingerprint


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--workspace',type=Path,required=True)
    parser.add_argument('--destination',type=Path,required=True);args=parser.parse_args()
    destination=Path(os.path.abspath(args.destination));destination.mkdir(parents=True,exist_ok=False)
    shutil.copytree(args.workspace/'runtime',destination/'runtime');shutil.copyfile(args.workspace/'demo.toml',destination/'demo.toml')
    roots=destination/'runtime/demo/hedging/exposures';identities=[p.name for p in roots.iterdir() if not p.name.startswith('.')]
    assert len(identities)==1;body=load(roots,identities[0]);assert body['data_types']==['synthetic']
    template=Path(__file__).resolve().parents[1]/'templates/demo-hedge-spec.json';spec=json.loads(template.read_text())
    spec.update(scope=['IEF'],benchmark='GLD',target_beta=.8,tools=['reduce_stock'],residual_beta_tolerance=.01)
    item={'exposure_id':identities[0],'spec':spec,'method':'reduce_stock','funding_quote':None,
        'proxy':{'symbol':'IEF','execution_price':200,'market_price':200,'beta':1.5,'trade_unit':1,
            'product_type':'etf','product_evidence':'synthetic test declaration, not provider qualification'}}
    fingerprint=source_fingerprint();checks=[];ids=[]
    book=Ledger(destination/'runtime/demo/account.sqlite','demo');before=(book.sequence('sample'),book.connection.execute('SELECT count(*) FROM tasks').fetchone()[0]);book.close()
    for name,invalid in [('preview',False),('repeat',False),('invalid_policy',True)]:
        request={**item,'spec':{**spec,'target_beta':None}} if invalid else item
        file=destination/(name+'.json');file.write_text(json.dumps(request))
        command=[sys.executable,'-m','personal_quant.cli','--config','demo.toml','hedge-preview','--account-id','sample','--file',file.name]
        process=subprocess.run(command,cwd=destination,capture_output=True,text=True,env=os.environ.copy())
        (destination/(name+'.stdout.json')).write_text(process.stdout);(destination/(name+'.stderr.json')).write_text(process.stderr)
        assert process.returncode==(2 if invalid else 0),process.stderr
        result=json.loads(process.stderr if invalid else process.stdout)
        if invalid:assert result['code']=='INVALID_HEDGE_SPEC'
        else:
            assert result['status']=='SELECTED_FOR_RESEARCH' and result['incremental_quantity']=='-37'
            assert result['target_position']=='63' and abs(float(result['B_post'])-23900)<1e-6
            assert float(result['E_post'])==30000 and not result['executable'];ids.append(result['preview_hash'])
        checks.append({'case':name,'command':command,'exit_code':process.returncode,'status':result['status']})
    book=Ledger(destination/'runtime/demo/account.sqlite','demo')
    try:assert before==(book.sequence('sample'),book.connection.execute('SELECT count(*) FROM tasks').fetchone()[0])
    finally:book.close()
    assert len(set(ids))==1 and source_fingerprint()==fingerprint
    (destination/'verification.json').write_text(json.dumps({'status':'PASSED','checks':checks,'source_fingerprint':fingerprint,
        'data_type':'synthetic_frozen_reference_research','B_post':23900,'E_post':30000,
        'account_unchanged':True,'limits':'No executable plan, product qualification, actual transaction or options candidate.'},ensure_ascii=False,indent=2))
    print(json.dumps({'status':'PASSED','checks':len(checks),'verification':str(destination/'verification.json')}))


if __name__=='__main__':main()
