from native_tools import native_engine_root,native_dotnet
import hashlib
import os
from pathlib import Path
import pytest
from personal_quant.common import QuantError
from personal_quant.options import adapter_resources as adapter

ROOT=Path(__file__).resolve().parents[1]


def test_verified_cache_reuses_binary_and_refuses_changed_output(tmp_path,monkeypatch):
    monkeypatch.setenv('LYRAX_ADAPTER_CACHE',str(tmp_path/'cache'))
    engine=Path(os.environ.get('LYRAX_TEST_ENGINE_ROOT',str(native_engine_root())))
    dotnet=Path(os.environ.get('LYRAX_TEST_DOTNET',str(native_dotnet())))
    def build(name):
        directory=tmp_path/name
        return adapter.build(engine,dotnet,directory,source_directory='source',binary_directory='bin',object_directory='obj',log_name='build.log')
    first=build('first')
    def forbidden(*args,**kwargs):raise AssertionError('identical verified cache should not compile again')
    monkeypatch.setattr(adapter,'_compile',forbidden)
    assert build('different directory with spaces')==first
    dll=lambda name:hashlib.sha256((tmp_path/name/'bin/LyraX.Options.dll').read_bytes()).hexdigest()
    assert dll('first')==dll('different directory with spaces')
    cached=next((tmp_path/'cache').glob('*/LyraX.Options.dll'));cached.write_bytes(b'changed cache')
    with pytest.raises(QuantError) as error:build('bad')
    assert error.value.code=='CORRUPT_ADAPTER_CACHE'
