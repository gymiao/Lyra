from pathlib import Path
import pytest

from personal_quant.common import QuantError
from personal_quant.locks import publish_directory


def test_transient_permission_failure_keeps_atomic_publication(tmp_path,monkeypatch):
    staged=tmp_path/'.pending';staged.mkdir();(staged/'proof').write_text('immutable evidence')
    target=tmp_path/'published';original=Path.rename;attempts=[];delays=[]
    def rename(self,destination):
        attempts.append(1)
        if len(attempts)<3:raise PermissionError('directory shared')
        return original(self,destination)
    monkeypatch.setattr(Path,'rename',rename)
    monkeypatch.setattr('personal_quant.locks.time.sleep',delays.append)
    publish_directory(staged,target)
    assert len(attempts)==3 and delays==[.1,.2]
    assert not staged.exists() and (target/'proof').read_text()=='immutable evidence'


def test_permanent_denial_is_bounded_and_does_not_publish(tmp_path,monkeypatch):
    staged=tmp_path/'.pending';staged.mkdir();target=tmp_path/'published';attempts=[]
    def rename(self,destination):
        attempts.append(1);raise PermissionError('permanent denial')
    monkeypatch.setattr(Path,'rename',rename);monkeypatch.setattr('personal_quant.locks.time.sleep',lambda _:None)
    with pytest.raises(QuantError) as exc:publish_directory(staged,target)
    assert exc.value.code=='PUBLICATION_PERMISSION_DENIED' and len(attempts)==5
    assert staged.exists() and not target.exists()


def test_existing_archive_is_never_replaced(tmp_path):
    staged=tmp_path/'.pending';staged.mkdir();target=tmp_path/'published';target.mkdir()
    (target/'proof').write_text('original')
    with pytest.raises(QuantError) as exc:publish_directory(staged,target)
    assert exc.value.code=='PUBLICATION_CONFLICT' and (target/'proof').read_text()=='original'

