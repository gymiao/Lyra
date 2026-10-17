import pytest
from personal_quant.common import QuantError,digest
from personal_quant.data.paged import ingest,materialize,TransientPageError
from personal_quant.workspace.forward_inputs import append


class Recorded:
    provider_id='recorded-fault-fixture';schema_version=1
    def __init__(self):self.calls=0
    def fetch(self,request,cursor):
        self.calls+=1
        if self.calls==1:raise TransientPageError('recorded 429')
        return {'records':[{'record_id':'quote-1','bid':1 if cursor is None else 2}],
                'next_cursor':'second' if cursor is None else None,'evidence_reference':'fixture/recorded-page'}
    def normalize(self,row):return row


def test_paged_retry_incremental_overlap_and_repeated_request(tmp_path):
    adapter=Recorded();delays=[]
    first=ingest(adapter,tmp_path,{},max_pages=1,sleep=delays.append)
    assert first['status']=='PAGE_BUDGET_PAUSED' and len(first['pages'])==1 and delays==[.1]
    second=ingest(adapter,tmp_path,{},sleep=delays.append)
    assert second['complete'] and len(second['pages'])==2
    calls=adapter.calls
    assert ingest(adapter,tmp_path,{})['repeated'] and calls==adapter.calls
    data=materialize(tmp_path,digest(second['identity']))
    assert data['records']==[{'record_id':'quote-1','bid':2}] and len(data['revisions'])==1
    assert not data['executable']


def test_forward_append_never_rewrites_and_rejects_injected_production_clock(tmp_path):
    request={'session':'2024-07-01','observed_at':'2024-07-01T20:00:00Z','available_at':'2024-07-01T20:01:00Z',
             'processed_at':'2024-07-01T20:02:00Z','input_bundle_id':'a'*64,'data_type':'synthetic'}
    first=append(tmp_path,request,clock='2024-07-01T21:00:00Z',test_clock=True)
    assert not first['natural_forward_verified']
    assert append(tmp_path,request,clock='2024-07-01T21:00:00Z',test_clock=True)['repeated']
    with pytest.raises(QuantError):append(tmp_path,{**request,'input_bundle_id':'b'*64})
    with pytest.raises(QuantError):append(tmp_path,request,clock='2024-07-01T21:00:00Z')
