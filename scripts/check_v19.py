"""Full local engineering checks with durable evidence and one frozen input version."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from uuid import uuid4

from personal_quant.common import now_utc
from personal_quant.options.catalog import A8
from personal_quant.options.qualification import assess_engine
from personal_quant.strategies.archive import source_fingerprint


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--destination',type=Path)
    parser.add_argument('--engine-evidence',type=Path,default=os.environ.get('LYRAX_TEST_ENGINE_EVIDENCE'))
    parser.add_argument('--temporary-root',type=Path,default=Path('/tmp'))
    args=parser.parse_args()
    root=Path(__file__).absolute().parents[1]
    writable_alias=Path('/mnt/c/quant/project/lyra')
    if writable_alias.is_dir() and writable_alias.samefile(root):root=writable_alias
    destination=args.destination.absolute() if args.destination else root/'reports/v19-validation'/('full-'+uuid4().hex)
    if any(destination.resolve().is_relative_to((root/name).resolve()) for name in ('src','tests','configs','examples','scripts')):
        parser.error('Verification output must be outside source, tests, configurations, examples and scripts')
    destination.mkdir(parents=True,exist_ok=False)
    manifest=dict(status='RUNNING',started_at=now_utc(),python=sys.executable,source_hash=source_fingerprint(),
        scope='full pytest and local CLI engineering; online data, browser and natural forward observation are separately verified',
        complete_goal=False,checks=[])
    def save():
        pending=destination/'verification.pending.json'
        pending.write_text(json.dumps(manifest,indent=2));pending.replace(destination/'verification.json')
    def inputs():
        paths=[]
        for directory in ('src','tests','configs','examples','scripts'):
            paths.extend(p for p in (root/directory).rglob('*') if p.is_file()
                         and '__pycache__' not in p.parts and p.suffix!='.pyc')
        paths.extend(p for p in root.iterdir() if p.is_file() and
                     (p.name=='pyproject.toml' or p.suffix=='.lock'))
        paths.extend((root/'engines/lean').glob('*.cs'));paths.append(root/'engines/lean/LyraX.Options.csproj')
        return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}
    environment=dict(os.environ,MPLCONFIGDIR='/tmp/lyrax-mpl',PYTHONDONTWRITEBYTECODE='1',PYTHONPATH=str(root/'src'))
    def run(name,arguments):
        record=dict(name=name,command=[sys.executable,*map(str,arguments)],started_at=now_utc(),status='RUNNING')
        manifest['checks'].append(record);save();print('START '+name,flush=True)
        log=destination/(name+'.log')
        with log.open('w') as output:
            completed=subprocess.run(record['command'],cwd=root,env=environment,stdout=output,stderr=subprocess.STDOUT)
        record.update(status='PASSED' if completed.returncode==0 else 'FAILED',exit_code=completed.returncode,
                      completed_at=now_utc(),log=str(log));save()
        if completed.returncode:raise RuntimeError(name+' failed; see '+str(log))
        return log
    save()
    try:
        if any(not (root/path).is_file() for path in ('.tools/dotnet/dotnet','.tools/lean/Launcher/bin/Release/QuantConnect.Lean.Launcher.dll')):
            raise RuntimeError('Full checks require the isolated LEAN SDK and launcher; see docs/V19-USAGE.md')
        if not args.engine_evidence:raise RuntimeError('Specify --engine-evidence or LYRAX_TEST_ENGINE_EVIDENCE with the archived A8 lifecycle proof')
        evidence=args.engine_evidence.absolute();environment['LYRAX_TEST_ENGINE_EVIDENCE']=str(evidence)
        engine={template:assess_engine(evidence,template,project=root)['status'] for template in sorted(A8)}
        if any(status!='PASSED' for status in engine.values()):raise RuntimeError('A8 lifecycle evidence does not match current adapter sources')
        manifest.update(engine_evidence=str(evidence),engine_templates=engine,
            dependencies={name:importlib.metadata.version(name) for name in
                ('bt','ffn','pandas','numpy','streamlit','QuantLib','pytest','pyarrow','yfinance','exchange-calendars','pyxirr')})
        baseline=inputs();manifest['input_files']=baseline;save()
        run('pip-check',['-m','pip','check'])
        manifest['legacy_cli_proofs']={}
        for name,script,directory,status in (
                ('legacy-v1','verify_offline.py','offline-validation','PASSED_OFFLINE_ACCOUNTING'),
                ('legacy-v15','verify_v15.py','v15-validation','PASS_V15_END_TO_END'),
                ('legacy-v18','verify_v18.py','v18-validation','PASS_V18_CLI')):
            run(name,['scripts/'+script])
            pointer=json.loads((root/'reports'/directory/'latest.json').read_text())
            proof=Path(pointer['verification']) if 'verification' in pointer else Path(pointer['root'])/'verification.json'
            result=json.loads(proof.read_text())
            if result['status']!=status or result['source_hash']!=manifest['source_hash']:
                raise RuntimeError(name+' compatibility proof does not match verified sources')
            manifest['legacy_cli_proofs'][name]=str(proof);save()
        collected=run('collect',['-m','pytest','--collect-only','-q','-p','no:cacheprovider','tests'])
        match=re.search(r'(\d+) tests? collected',collected.read_text())
        if not match:raise RuntimeError('Full test collection count is missing')
        manifest['collected_tests']=int(match.group(1));save()
        temporary=Path(tempfile.mkdtemp(prefix='lyrax-v19-full-',dir=args.temporary_root.absolute()))
        manifest['test_temporary_directory']=str(temporary);save()
        log=run('pytest',['-m','pytest','-q','-x','-p','no:cacheprovider','tests',
                          '-o','tmp_path_retention_policy=failed','--basetemp='+str(temporary)])
        text=log.read_text();passed=re.search(r'(\d+) passed',text);skipped=re.search(r'(\d+) skipped',text)
        if not passed or int(passed.group(1))!=manifest['collected_tests'] or skipped:
            raise RuntimeError('Full verification requires every collected test to pass without skips')
        manifest['passed_tests']=int(passed.group(1));save()
        core=run('core-cli',['scripts/verify_v19.py'])
        core_proof=Path(core.read_text().strip().splitlines()[-1]);core_result=json.loads(core_proof.read_text())
        if core_result['status']!='PASSED' or core_result['source_hash']!=manifest['source_hash']:
            raise RuntimeError('Core CLI proof does not match verified sources')
        manifest['core_cli_proof']=str(core_proof)
        for name,script in (('model-cli','verify_model_greek.py'),('qualification-cli','verify_qualification_links.py')):
            workspace=destination/(name+'-workspace')
            run(name,['scripts/'+script,'--workspace',workspace])
            proof=json.loads((workspace/'verification.json').read_text())
            if proof['status']!='PASSED' or proof['source_fingerprint']!=manifest['source_hash']:
                raise RuntimeError(name+' proof does not match verified sources')
        if inputs()!=baseline or source_fingerprint()!=manifest['source_hash']:
            raise RuntimeError('Code, tests, configurations, fixtures or locks changed during verification')
        manifest.update(status='LOCAL_AUTOMATED_CHECKS_PASSED',completed_at=now_utc());save()
        print(destination/'verification.json');return 0
    except (RuntimeError,OSError,ValueError,KeyError,importlib.metadata.PackageNotFoundError) as exc:
        manifest.update(status='FAILED',reason=str(exc),completed_at=now_utc());save()
        print(str(exc),file=sys.stderr);return 1
    except KeyboardInterrupt:
        manifest.update(status='INTERRUPTED',completed_at=now_utc());save();return 130


if __name__=='__main__':raise SystemExit(main())
