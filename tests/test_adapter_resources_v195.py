from native_tools import native_engine_root,native_dotnet
import hashlib
from pathlib import Path
from personal_quant.options.adapter_resources import build,adapter_root,source_hashes

ROOT=Path(__file__).resolve().parents[1]


def test_build_uses_copied_resources_and_is_reproducible_across_paths(tmp_path):
    original=adapter_root();before=source_hashes(original);hashes=[]
    for name in ['first','second directory with spaces']:
        directory=tmp_path/name;directory.mkdir()
        result=build(native_engine_root(),native_dotnet(),directory,
            source_directory='source',binary_directory='bin',object_directory='obj',log_name='build.log')
        assert result==before and source_hashes(directory/'source')==before
        hashes.append(hashlib.sha256((directory/'bin/LyraX.Options.dll').read_bytes()).hexdigest())
    assert hashes[0]==hashes[1]
    assert source_hashes(original)==before
