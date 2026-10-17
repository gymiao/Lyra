"""Isolated LEAN backtest proof using official packaged regression fixtures."""
import json
import os
from pathlib import Path
import subprocess
from ..common import QuantError, now_utc, write_json

LEAN_COMMIT='80e7843f645673bcbeaab963049f76f20f6785e1'
ALGORITHM='OptionEquityCoveredCallRegressionAlgorithm'


def smoke(engine_root, dotnet, destination):
    root=Path(engine_root).absolute();dotnet=Path(dotnet).absolute();destination=Path(destination).absolute()
    if destination.exists():raise QuantError('NONEMPTY_DESTINATION','引擎验证输出须为新目录')
    launcher=root/'Launcher/bin/Release/QuantConnect.Lean.Launcher.dll'
    if not launcher.is_file() or not dotnet.is_file():
        raise QuantError('LEAN_NOT_INSTALLED','需要已验证的隔离.NET SDK与LEAN编译产物')
    revision=subprocess.run(['git','-C',str(root),'rev-parse','HEAD'],capture_output=True,text=True,check=True).stdout.strip()
    if revision!=LEAN_COMMIT:raise QuantError('LEAN_VERSION_MISMATCH','仅接受已验证的LEAN源码提交')
    dirty=subprocess.run(['git','-C',str(root),'status','--porcelain'],capture_output=True,text=True,check=True).stdout.strip()
    if dirty:raise QuantError('LEAN_SOURCE_CHANGED','第三方工作树有修改，需独立重新验证版本')
    sdk=subprocess.run([str(dotnet),'--version'],capture_output=True,text=True,check=True).stdout.strip()
    if sdk!='10.0.100':raise QuantError('SDK_VERSION_MISMATCH','需要经过验证的隔离.NET SDK10.0.100')
    destination.mkdir(parents=True)
    command=[str(dotnet),str(launcher),'--config',str(root/'Launcher/config.json'),
             '--algorithm-type-name',ALGORITHM,'--data-folder',str(root/'Data'),
             '--results-destination-folder',str(destination),'--close-automatically','true']
    environment=dict(os.environ,DOTNET_CLI_HOME='/tmp/lyrax-dotnet-home')
    with (destination/'launcher.log').open('w') as log:
        try:result=subprocess.run(command,cwd=launcher.parent,env=environment,stdout=log,stderr=subprocess.STDOUT,timeout=180)
        except subprocess.TimeoutExpired as exc:raise QuantError('LEAN_TIMEOUT','验证超时，日志已保存') from exc
    summary_path=destination/(ALGORITHM+'-summary.json')
    if result.returncode or not summary_path.is_file():raise QuantError('LEAN_FAILED','LEAN运行失败，查看输出目录launcher.log')
    summary=json.loads(summary_path.read_text());state=summary.get('state',{})
    if state.get('Status')!='Completed' or state.get('RuntimeError'):
        raise QuantError('LEAN_FAILED','LEAN算法未完成或报告包含运行错误')
    proof={'status':'PASSED','engine':'LEAN','commit':revision,'sdk':sdk,'algorithm':ALGORITHM,
           'activity':'official_fixture_engine_smoke','data_type':'upstream_regression_fixture',
           'statistics':summary['statistics'],'orders':int(state['OrderCount']),'generated_at':now_utc(),
           'report_path':str(destination),'validates_lyrax_strategies':False,'no_account_writes':True,
           'limitations':['官方回归使用自身杠杆/交易假设，不能作为LyraX资金或风控验收',
                          '附带样本不代表授权完整历史链；编译依赖有上游审计警告，当前仅隔离验证']}
    write_json(destination/'engine-proof.json',proof)
    return proof
