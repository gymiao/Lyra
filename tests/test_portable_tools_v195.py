import json
from pathlib import Path
import shutil
import pytest
from personal_quant.common import QuantError
from personal_quant.workspace import portable_tools as tools


def installed(tmp_path,monkeypatch):
    root=tmp_path/'original';lean=root/'lean';sdk=root/'sdk'
    for relative in ['Launcher/config.json','Data/market-hours/market-hours-database.json',
        'Data/symbol-properties/symbol-properties-database.csv','Data/symbol-properties/security-database.csv',
        'Launcher/bin/Release/QuantConnect.Lean.Launcher.dll']:
        path=lean/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(relative.encode())
    for relative in ['dotnet','sdk/10.0.100/compiler.dll','shared/runtime.dll']:
        path=sdk/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(relative.encode())
    def output(args,**kwargs):
        if args[-1]=='--version':return '10.0.100\n'
        return tools.LEAN_COMMIT+'\n' if args[-1]=='HEAD' else ''
    monkeypatch.setattr(tools.subprocess,'check_output',output)
    return root,lean,sdk/'dotnet'


def test_relocation_preserves_content_and_run_identity_and_refuses_changed_binary(ledger,tmp_path,monkeypatch):
    root,lean,dotnet=installed(tmp_path,monkeypatch)
    manifest=tools.fingerprint(lean,dotnet);directory=tmp_path/'runtime/simulation/options/run';directory.mkdir(parents=True)
    settings={'engine_root':str(lean),'dotnet':str(dotnet)};original=dict(settings)
    tools.bind(ledger,directory,'run',settings,manifest)
    other=tmp_path/'moved directory with spaces';shutil.copytree(root,other)
    moved=tools.resolve(ledger,directory,'run',engine_root=other/'lean',dotnet=other/'sdk/dotnet')
    assert moved=={'engine_root':str(other/'lean'),'dotnet':str(other/'sdk/dotnet')}
    assert settings==original and ledger.sequence('sample')==0
    assert tools.archived(ledger,directory,'run')[1]==manifest
    assert ledger.connection.execute("SELECT count(*) FROM tasks WHERE task_id LIKE 'simulation-tool-relocation:%'").fetchone()[0]==1
    # Changed supporting runtime bytes must fail even when version strings match.
    (other/'sdk/shared/runtime.dll').write_bytes(b'different runtime')
    before=ledger.connection.execute('SELECT count(*) FROM tasks').fetchone()[0]
    with pytest.raises(QuantError) as caught:tools.resolve(ledger,directory,'run')
    assert caught.value.code=='SIMULATION_TOOLS_CHANGED'
    assert ledger.connection.execute('SELECT count(*) FROM tasks').fetchone()[0]==before
    assert ledger.sequence('sample')==0


def test_manifest_tamper_and_incomplete_path_override_are_rejected(ledger,tmp_path,monkeypatch):
    _,lean,dotnet=installed(tmp_path,monkeypatch);manifest=tools.fingerprint(lean,dotnet)
    directory=tmp_path/'runtime/simulation/options/run';directory.mkdir(parents=True)
    tools.bind(ledger,directory,'run',{'engine_root':str(lean),'dotnet':str(dotnet)},manifest)
    with pytest.raises(QuantError) as caught:tools.resolve(ledger,directory,'run',engine_root=lean)
    assert caught.value.code=='SIMULATION_TOOL_PATHS_REQUIRED'
    changed={**manifest,'sdk_version':'unknown'};(directory/'tool-manifest.json').write_text(json.dumps(changed))
    with pytest.raises(QuantError) as caught:tools.archived(ledger,directory,'run')
    assert caught.value.code=='CORRUPT_SIMULATION_TOOLS'


@pytest.mark.parametrize('kind',['dirty','version'])
def test_unqualified_tool_versions_or_dirty_source_fail_before_binding(tmp_path,monkeypatch,kind):
    _,lean,dotnet=installed(tmp_path,monkeypatch);original=tools.subprocess.check_output
    def output(args,**kwargs):
        if kind=='dirty' and args[-1]=='--porcelain':return ' M Engine.cs\n'
        if kind=='version' and args[-1]=='--version':return 'different-sdk\n'
        return original(args,**kwargs)
    monkeypatch.setattr(tools.subprocess,'check_output',output)
    with pytest.raises(QuantError) as caught:tools.fingerprint(lean,dotnet)
    assert caught.value.code==('LEAN_SOURCE_CHANGED' if kind=='dirty' else 'LEAN_VERSION_MISMATCH')
