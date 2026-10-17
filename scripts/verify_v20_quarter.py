"""Public CLI proof for the custom three-month model-data options workflow."""
import argparse,json,os,subprocess,sys
from pathlib import Path
from personal_quant.config import Config
from personal_quant.common import now_utc,write_json
from personal_quant.processes import python_command,python_environment
from personal_quant.strategies.archive import source_fingerprint


def main():
    p=argparse.ArgumentParser();p.add_argument('--destination',type=Path,required=True);p.add_argument('--engine-root',type=Path,required=True);p.add_argument('--dotnet',type=Path,required=True)
    a=p.parse_args();r=Path(__file__).absolute().parents[1];out=a.destination.absolute();out.mkdir(parents=True,exist_ok=False)
    source=source_fingerprint();checks=[]
    cfg=Config.load(r/'configs/demo.toml').content();cfg['evaluation_end']='2024-10-31';write_json(out/'config.json',cfg)
    write_json(out/'workspace-spec.json',{'schema_version':1,'kind':'options','account_id':'demo-account','initial_cash':'100000','input_bundle':str(out/'data')})
    def cli(name,*args):
        cmd=[*python_command('personal_quant'),'--config',str(out/'config.json'),*map(str,args)]
        proc=subprocess.run(cmd,cwd=r,env=python_environment(),text=True,capture_output=True)
        (out/(name+'.stdout.json')).write_text(proc.stdout);(out/(name+'.stderr.log')).write_text(proc.stderr)
        checks.append({'name':name,'command':cmd,'exit_code':proc.returncode});assert proc.returncode==0,(name,proc.stderr)
        return json.loads(proc.stdout)
    generated=cli('generate','input-package','scenario','--file',r/'configs/v20-scenario.json','--destination',out/'data')
    cli('verify-input','input-package','verify','--source',out/'data')
    cli('init','workspace','init','--workspace',out/'workspace','--spec',out/'workspace-spec.json')
    setup=json.loads((r/'configs/v195-option-setup.json').read_text());setup.update(template_id='long_call',input_bundle=str(out/'data'))
    setup['selection_parameters'].update(minimum_dte=14,target_dte=21,maximum_dte=35,exit_days_before_expiry=3)
    write_json(out/'setup.json',setup)
    prepared=cli('prepare','simulation','prepare','--workspace',out/'workspace','--file',out/'setup.json');assert prepared['cycle_count']==3
    run=cli('start','simulation','start','--workspace',out/'workspace','--file',prepared['request_file'],'--engine-root',a.engine_root,'--dotnet',a.dotnet,'--fee-per-contract',2)
    result=cli('batch','simulation','batch','--workspace',out/'workspace','--run-id',run['run_id'],'--through','2024-10-31','--max-seconds',600,'--min-free-bytes',0)
    assert result['status']=='COMPLETED',result
    repeated=cli('repeat','simulation','batch','--workspace',out/'workspace','--run-id',run['run_id'],'--through','2024-10-31','--max-seconds',600,'--min-free-bytes',0)
    assert repeated['events']==result['events'] and repeated['details']['equity']==result['details']['equity']
    cli('diagnostic','workspace','diagnostic','--workspace',out/'workspace','--destination',out/'diagnostic')
    assert source_fingerprint()==source
    write_json(out/'verification.json',{'status':'PASSED','source_hash':source,'source_unchanged':True,'checks':checks,'cycles':generated['cycles'],
        'data_type':'synthetic_QuantLib_model_quotes','events':result['events'],'equity':result['details']['equity'],'completed_at':now_utc(),'complete_version':False})
    print(json.dumps({'status':'PASSED','commands':len(checks),'cycles':generated['cycles'],'events':result['events'],'equity':result['details']['equity']}))

if __name__=='__main__':main()
