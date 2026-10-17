"""Scoped v1.95 verification; release gates require the full suite and no skips."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from personal_quant.common import now_utc,write_json
from personal_quant.strategies.archive import source_fingerprint


def complete_results(expected,collected,rows):
    """All collected cases must pass every phase exactly once; no substitutes."""
    phases=Counter((row['nodeid'],row['phase']) for row in rows)
    required=Counter((node,phase) for node in expected for phase in ('setup','call','teardown'))
    return bool(expected) and Counter(expected)==Counter(collected) and phases==required and all(
        row['outcome']=='passed' and not row.get('wasxfail') for row in rows)


def release_groups(root,output,environment):
    command=[sys.executable,'-m','pytest','--collect-only','-q','tests','-p','no:cacheprovider']
    collection=subprocess.run(command,cwd=root,env=environment,text=True,capture_output=True)
    (output/'collection.log').write_text(collection.stdout+collection.stderr)
    expected=[line for line in collection.stdout.splitlines() if line.startswith('tests/') and '::' in line]
    if collection.returncode or not expected or re.search(r'\b\d+ skipped\b',collection.stdout):
        raise RuntimeError('完整测试收集失败或跳过；保留collection.log，不缩减范围')
    files=sorted({node.split('::')[0] for node in expected})
    ui=[name for name in files if 'ui' in Path(name).stem or 'AppTest' in (root/name).read_text()]
    groups=[('ui',ui),('integration',[name for name in files if name not in ui])]
    write_json(output/'expected-nodeids.json',expected)
    return expected,[(name,paths) for name,paths in groups if paths]


def input_hashes(root):
    extensions={'.py','.cs','.csproj','.json','.csv','.toml','.yaml','.yml','.sh','.example'}
    files=[]
    for name in ('src','tests','engines','scripts','configs','examples','templates'):
        files.extend(path for path in (root/name).rglob('*') if path.is_file() and path.suffix in extensions
                     and not {'bin','obj','__pycache__'} & set(path.relative_to(root).parts))
    files.extend(path for path in root.iterdir() if path.is_file() and (path.suffix=='.lock' or path.name in {'pyproject.toml','environment.yml','GOAL.md'}))
    return {str(path.relative_to(root)):hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(set(files))}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--scope',choices=['core','native','release'],default='core')
    parser.add_argument('--destination',type=Path,required=True)
    parser.add_argument('--temp-root',type=Path,help='pytest临时产物父目录；完整原生/发布默认使用报告所在磁盘')
    args=parser.parse_args()
    root=Path(__file__).absolute().parents[1]
    writable=Path('/mnt/c/quant/project/lyra')
    if writable.exists() and writable.samefile(root):root=writable
    output=args.destination.absolute();output.mkdir(parents=True,exist_ok=False)
    if args.scope=='release':tests=['tests']
    elif args.scope=='native':tests=['tests/test_options_prefix_v195.py','tests/test_options_monthly_replay_v19.py','tests/test_option_workspace_v195.py',
                                   'tests/test_options_long_vol_v195.py','tests/test_options_credit_v195.py','tests/test_options_delivery_v195.py',
                                   'tests/test_options_monthly_natural_v19.py','tests/test_options_natural_prefix_v195.py','tests/test_option_natural_workspace_v195.py','tests/test_options_report_v195.py',
                                   'tests/test_options_credit_qualification_v195.py','tests/test_options_credit_activation_v195.py',
                                   'tests/test_options_vol_qualification_v195.py','tests/test_options_vol_activation_v195.py','tests/test_options_rolling_v195.py','tests/test_rolling_workspace_v195.py',
                                   'tests/test_wheel_native_v195.py','tests/test_wheel_workspace_v195.py','tests/test_rolling_natural_v195.py',
                                   'tests/test_option_workspace_plans_v195.py','tests/test_option_deferred_workspace_v195.py',
                                   'tests/test_stock_preparation_v195.py','tests/test_stock_preparation_workspace_v195.py',
                                   'tests/test_option_prefix_exit_v195.py','tests/test_option_exit_receipt_v195.py','tests/test_prefix_exit_backup_v195.py',
                                   'tests/test_prepared_natural_v195.py','tests/test_adapter_resources_v195.py',
                                   'tests/test_partial_prefix_exit_backup_v195.py','tests/test_option_worker_state_v195.py',
                                   'tests/test_portable_tools_native_v195.py','tests/test_option_experiments_v195.py',
                                   'tests/test_option_experiment_delivery_v195.py','tests/test_comparison_package_v195.py',
                                   'tests/test_option_planned_comparison_v195.py','tests/test_option_cross_strategy_v195.py',
                                   'tests/test_option_setup_native_v195.py','tests/test_assignment_native_v195.py','tests/test_adapter_cache_v195.py']
    else:tests=['tests/test_ui_v195.py','tests/test_ui.py','tests/test_report_state_v195.py','tests/test_workspace_v195.py',
               'tests/test_option_checkpoint_v195.py','tests/test_portable_tools_v195.py','tests/test_lifecycle_calendar_v195.py','tests/test_wheel_state_v195.py','tests/test_option_execution_window_v195.py','tests/test_single_session_calendar_v195.py','tests/test_stock_policy_v195.py','tests/test_simulation_source_archive_v195.py','tests/test_jobs_v195.py','tests/test_experiments_v195.py',
               'tests/test_risk_lab_v195.py','tests/test_risk_controls_v195.py','tests/test_experiment_index_v195.py','tests/test_experiment_ui_v195.py',
               'tests/test_option_setup_v195.py','tests/test_option_setup_ui_v195.py','tests/test_simulation_disk_failure_v195.py',
               'tests/test_assignment_scenarios_v195.py','tests/test_workspace_diagnostic_v195.py','tests/test_workspace_readiness_v195.py',
               'tests/test_workspace_maintenance_v195.py','tests/test_daily.py','tests/test_backup.py']
    if args.scope=='core':tests.extend(['tests/test_batch_v195.py','tests/test_calendar_diagnostic_v195.py','tests/test_release_gate_v195.py'])
    if args.scope=='native':tests.append('tests/test_batch_native_v195.py')
    if args.scope in {'native','release'}:
        from personal_quant.processes import native_tools
        try:native_tools(root)
        except ValueError as exc:parser.error(str(exc))
    if any(not (root/test).exists() for test in tests):parser.error('测试分组引用不存在的路径')
    fingerprint=source_fingerprint();inputs=input_hashes(root)
    write_json(output/'inputs.json',inputs)
    temporary_root=(args.temp_root.absolute() if args.temp_root else
        output/'pytest-temp' if args.scope in {'native','release'} or shutil.disk_usage(tempfile.gettempdir()).free<1024**3 else Path(tempfile.gettempdir()))
    temporary_root.mkdir(parents=True,exist_ok=True)
    environment=dict(os.environ,MPLCONFIGDIR='/tmp/lyrax-mpl',PYTHONDONTWRITEBYTECODE='1')
    environment.pop('LYRAX_TEST_REPORT_FILE',None)
    if args.scope=='release':expected,groups=release_groups(root,output,environment)
    else:expected=None;groups=[(args.scope,tests)]
    phases=[];collected=[];reports=[];commands=[];summaries=[]
    for name,paths in groups:
        receipt=output/(name+'-results.jsonl')
        command=[sys.executable,'-m','pytest','-q',*paths,'-p','no:cacheprovider','-o','faulthandler_timeout=0',
                 '--basetemp',tempfile.mkdtemp(prefix='lyrax-v195-'+name+'-',dir=temporary_root)]
        commands.append(command)
        with (output/(name+'-pytest.log')).open('w') as log:
            process=subprocess.run(command,cwd=root,env=dict(environment,LYRAX_TEST_REPORT_FILE=str(receipt)),stdout=log,stderr=subprocess.STDOUT)
        summary=(output/(name+'-pytest.log')).read_text();summaries.append(summary)
        evidence_error=None
        try:
            nodes=json.loads(Path(str(receipt)+'.collection.json').read_text()) if Path(str(receipt)+'.collection.json').is_file() else []
            rows=[json.loads(line) for line in receipt.read_text().splitlines()] if receipt.is_file() else []
        except (OSError,ValueError) as exc:
            nodes=[];rows=[];evidence_error=type(exc).__name__
        selected=[node for node in expected if node.split('::')[0] in paths] if expected is not None else nodes
        valid=process.returncode==0 and complete_results(selected,nodes,rows)
        phases.append({'name':name,'exit_code':process.returncode,'status':'PASSED' if valid else 'FAILED','collected':len(nodes),
                       'evidence_error':evidence_error})
        collected.extend(nodes);reports.extend(rows)
        write_json(output/'phases.json',phases)
    (output/'pytest.log').write_text('\n'.join(summaries))
    skipped=any(row['outcome']=='skipped' or row.get('wasxfail') for row in reports)
    coverage=complete_results(expected if expected is not None else collected,collected,reports)
    unchanged=source_fingerprint()==fingerprint and input_hashes(root)==inputs
    passed=all(phase['status']=='PASSED' for phase in phases) and coverage and not skipped and unchanged
    result={'status':'PASSED' if passed else 'FAILED','scope':args.scope,
            'source_hash':fingerprint,'source_unchanged':unchanged,'commands':commands,'exit_code':0 if passed else 1,
            'phases':phases,'collected':len(collected),'complete_collection_coverage':coverage,
            'skipped':skipped,'temporary_root':str(temporary_root),'input_files':len(inputs),'completed_at':now_utc(),'complete_version':False}
    write_json(output/'verification.json',result);print(json.dumps(result));return 0 if result['status']=='PASSED' else 1

if __name__=='__main__':raise SystemExit(main())
