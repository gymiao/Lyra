from pathlib import Path
import pandas as pd
import pytest
from personal_quant.data.fixture import create_fixture
from personal_quant.workspace.csv_package import preview,commit
from personal_quant.workspace.packages import verify
from personal_quant.common import QuantError


def test_csv_preview_mapping_dedup_commit_and_content_change_are_explicit(tmp_path):
    file,calendar=create_fixture(tmp_path/'fixture')
    frame=pd.read_csv(file);frame=frame.rename(columns={'close':'收盘价'})
    frame=pd.concat([frame,frame.iloc[:1]]);file.write_text(frame.to_csv(index=False))
    content=file.read_bytes();mapping={'收盘价':'close'}
    result=preview(content,mapping,calendar_file=calendar,calendar_kind='synthetic_test_sessions')
    assert result['duplicates_removed']==1 and result['financial_events_added']==0
    imported=commit(file,mapping,tmp_path/'package',result['preview_id'],calendar_file=calendar,calendar_kind='synthetic_test_sessions')
    assert imported['status']=='IMPORTED' and verify(tmp_path/'package')['roles']
    file.write_bytes(content+b'\n')
    with pytest.raises(QuantError) as error:commit(file,mapping,tmp_path/'other',result['preview_id'],calendar_file=calendar,calendar_kind='synthetic_test_sessions')
    assert error.value.code=='CSV_PREVIEW_CHANGED' and not (tmp_path/'other').exists()


def test_csv_ambiguous_available_timezone_is_rejected(tmp_path):
    file,calendar=create_fixture(tmp_path/'fixture');frame=pd.read_csv(file)
    frame['available_at']='2024-07-01T21:00:00'
    with pytest.raises(QuantError) as error:preview(frame.to_csv(index=False).encode(),{},calendar_file=calendar,calendar_kind='synthetic_test_sessions')
    assert error.value.code=='AMBIGUOUS_CSV_TIMEZONE'
