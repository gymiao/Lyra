from pathlib import Path
from personal_quant.portfolio import Ledger
from personal_quant.portfolio.report import account_report
from personal_quant.portfolio.report_state import report_state


def test_future_events_do_not_invalidate_past_report_but_late_facts_do(tmp_path):
    book=Ledger(tmp_path/'account.sqlite','demo');book.account('x')
    book.import_events('x',[{'event_id':'a','kind':'DEPOSIT','amount':'100','effective_at':'2024-07-01T20:00Z','source':'test','evidence_type':'test'}])
    report=account_report(book,'x','2024-07-02T20:00Z',{},tmp_path/'report')
    book.import_events('x',[{'event_id':'b','kind':'DEPOSIT','amount':'50','effective_at':'2024-07-03T20:00Z','source':'test','evidence_type':'test'}])
    assert report_state(book,report,'x','2024-07-02T20:00Z')['status']=='CURRENT'
    assert report_state(book,report,'x','2024-07-01T20:00Z')['status']=='AHEAD_OF_VIEW'
    assert report_state(book,report,'x','2024-07-04T20:00Z')['status']=='HISTORICAL'
    book.import_events('x',[{'event_id':'c','kind':'DEPOSIT','amount':'25','effective_at':'2024-07-02T19:00Z','source':'test','evidence_type':'test'}])
    assert report_state(book,report,'x','2024-07-02T20:00Z')['status']=='LEDGER_CHANGED'
    assert book.snapshot('x','2024-07-02T20:00Z')['settled_cash']=='125'
    book.close()
