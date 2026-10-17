import hashlib
import json
from pathlib import Path
import subprocess
import sys
import pytest
from personal_quant.common import QuantError
from personal_quant.config import Config
from personal_quant.workspace.service import create,status
from personal_quant.workspace.diagnostic import export,view

ROOT=Path(__file__).resolve().parents[1]


def test_export_allowlist_does_not_include_private_files_or_config_values(tmp_path):
    root=tmp_path/'workspace'
    create(root,{'schema_version':1,'kind':'options','account_id':'private-account-name','initial_cash':'100000'},Config.load(ROOT/'configs/demo.toml'))
    runtime=root/'runtime/demo';(runtime/'private-broker-statement.csv').write_text('secret-raw-statement')
    folder=runtime/'simulation/options'/('a'*64);folder.mkdir(parents=True)
    (folder/'settings.json').write_text(json.dumps({'api_key':'secret-api-key','path':'private-local-path'}))
    original=status(root)['events'];result=view(root)
    assert result['event_count']==1 and result['read_only']
    destination=tmp_path/'diagnostic'
    command=[sys.executable,'-m','personal_quant','workspace','diagnostic','--workspace',str(root),'--destination',str(destination)]
    completed=subprocess.run(command,capture_output=True,text=True,cwd='/tmp')
    assert completed.returncode==0,completed.stderr
    assert set(p.name for p in destination.iterdir())=={'manifest.json','diagnostic.json'}
    content=(destination/'diagnostic.json').read_text()
    assert not any(secret in content for secret in ['private-account-name','secret-api-key','private-local-path','secret-raw-statement',str(root)])
    manifest=json.loads((destination/'manifest.json').read_text())
    assert manifest['files']['diagnostic.json']==hashlib.sha256(content.encode()).hexdigest()
    assert status(root)['events']==original
    with pytest.raises(QuantError):export(root,destination)
    with pytest.raises(QuantError):export(root,runtime/'diagnostic')
