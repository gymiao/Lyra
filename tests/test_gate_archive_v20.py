import importlib.util
from pathlib import Path
import sys
import tarfile
import pytest
ROOT=Path(__file__).resolve().parents[1]


def module(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT/'scripts'))
    spec=importlib.util.spec_from_file_location('lyrax_gate_archive_test',ROOT/'scripts/check_v20.py')
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result


def test_partition_keeps_every_module_once_with_independent_node_counts(monkeypatch):
    gate=module(monkeypatch);paths=['a.py','b.py','c.py','d.py']
    expected=['a.py::first','a.py::second','b.py::third','c.py::fourth','d.py::fifth']
    groups=gate.partition(paths,expected,3)
    assert len(groups)==3 and sorted(p for group in groups for p in group)==paths
    assert sorted(sum(sum(node.startswith(p+'::') for node in expected) for p in group) for group in groups)==[1,2,2]


def test_archive_verified_bytes_and_link_metadata_before_freeing_owned_temp(tmp_path,monkeypatch):
    gate=module(monkeypatch);directory=tmp_path/'phase-temp';directory.mkdir();(directory/'receipt.json').write_text('{"events":7}')
    outside=tmp_path/'outside';outside.write_text('not an archive member');(directory/'evidence-link').symlink_to(outside)
    archive=tmp_path/'evidence.tar.gz';receipt=gate.archive_temp(directory,archive)
    assert receipt['readback_verified'] and not directory.exists() and outside.read_text()=='not an archive member'
    with tarfile.open(archive) as tar:
        assert tar.extractfile('phase-temp/receipt.json').read()==b'{"events":7}'
        assert tar.getmember('phase-temp/evidence-link').issym() and all('outside' not in m.name for m in tar.getmembers())


def test_archive_mismatch_keeps_originals_and_does_not_report_freeing_space(tmp_path,monkeypatch):
    gate=module(monkeypatch);directory=tmp_path/'phase-temp';directory.mkdir();file=directory/'receipt';file.write_text('original evidence')
    real=gate.temp_manifest
    monkeypatch.setattr(gate,'temp_manifest',lambda p:{**real(p),'injected-missing-member':{'kind':'file','sha256':'wrong'}})
    with pytest.raises(RuntimeError,match='originals retained'):gate.archive_temp(directory,tmp_path/'bad.tar.gz')
    assert file.read_text()=='original evidence'
