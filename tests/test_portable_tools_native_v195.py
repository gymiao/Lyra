from native_tools import native_engine_root,native_dotnet
"""Copy the actual external tools, restore elsewhere, then continue native facts."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
from personal_quant.config import Config
from personal_quant.portfolio.backup import create_bundle,restore_bundle
from personal_quant.workspace.service import create,worker

ROOT=Path(__file__).resolve().parents[1]


def test_restored_native_workspace_continues_with_copied_lean_and_sdk(tmp_path,monkeypatch):
    source=tmp_path/'source';spec={'schema_version':1,'account_id':'demo-account','initial_cash':'100000','kind':'options'}
    create(source,spec,Config.load(ROOT/'configs/demo.toml'))
    start=worker(source,'start',input_file=ROOT/'examples/options/monthly-variable-path.json',
        engine_root=native_engine_root(),dotnet=native_dotnet(),fee_per_contract=2)
    first=worker(source,'step',start['run_id'],'2024-11-04')
    assert first['events']==4 and float(first['details']['equity'])==99994.5
    settings=source/'runtime/demo/simulation/options'/start['run_id']/'settings.json'
    original=hashlib.sha256(settings.read_bytes()).hexdigest()
    moved=tmp_path/'copied tools with spaces';moved.mkdir()
    subprocess.run(['git','clone','--local','--no-hardlinks','--quiet',str(native_engine_root()),str(moved/'lean')],
        env=dict(os.environ,GIT_LFS_SKIP_SMUDGE='1'),check=True,capture_output=True,timeout=180)
    shutil.copytree(native_engine_root()/'Launcher/bin/Release',moved/'lean/Launcher/bin/Release')
    shutil.copytree(native_dotnet().parent,moved/'sdk')
    monkeypatch.chdir(source);create_bundle(source/'runtime/demo',source/'config.json',tmp_path/'bundle')
    restored=tmp_path/'restored';result=restore_bundle(tmp_path/'bundle',restored,'demo')
    done=worker(restored,'resume',start['run_id'],'2025-01-10',engine_root=moved/'lean',dotnet=moved/'sdk/dotnet')
    assert done['events']==13
    settled=worker(restored,'resume',start['run_id'],'2025-01-13')
    assert settled['status']=='COMPLETED' and settled['events']==13
    assert settled['details']['equity']==done['details']['equity']
    assert worker(restored,'resume',start['run_id'],'2025-01-13')['repeated']
    runtime=restored/Config.load(result['config']).runtime_dir
    copied_settings=runtime/'simulation/options'/start['run_id']/'settings.json'
    assert hashlib.sha256(copied_settings.read_bytes()).hexdigest()==original
    # A second bundle must validate the relocated binding without dereferencing
    # or packaging any of these external executable directories.
    monkeypatch.chdir(restored);create_bundle(runtime,result['config'],tmp_path/'relocated-bundle')
