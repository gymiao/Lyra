"""Read-only report freshness against facts at the report's own effective time."""
from ..common import QuantError, digest, utc

FACT_FIELDS=('settled_cash','receivables','payables','positions','option_positions',
             'deposits','withdrawals','net_contributions','reserved_cash','reserved_positions',
             'available_cash','option_cash_collateral','option_covered_shares','anomalies')
FACT_FIELDS+=('equity','investment_pnl','option_market_value')


def report_state(book,report,account_id,view_at):
    if report.get('account_id')!=account_id or report.get('environment')!=book.environment:
        return {'status':'UNVERIFIED','reason':'报告与当前账户或环境不匹配'}
    if report.get('legacy_unverified_report'):
        return {'status':'UNVERIFIED','reason':'旧报告缺少可核验的发布清单'}
    try:
        report_at=utc(report['as_of']);view=utc(view_at)
        with book.transaction():
            snapshot=book.snapshot(account_id,report['as_of'],report.get('prices',{}))
            changed=[key for key in FACT_FIELDS if key in report and report[key]!=snapshot.get(key)]
            events=digest(book.active_events(account_id,report['as_of']))
        if report.get('effective_events_hash') and report['effective_events_hash']!=events:
            changed.append('effective_events')
        if changed:return {'status':'LEDGER_CHANGED','reason':'账本已变化，已发布报告待更新','changed_fields':changed}
        if report_at>view:return {'status':'AHEAD_OF_VIEW','reason':'报告晚于当前查看时点，请选择一致日期或重建报告'}
        if report_at<view:return {'status':'HISTORICAL','reason':'当前展示的是已发布历史报告，请核对估值截至时间'}
        if report.get('equity') is None:return {'status':'INCOMPLETE','reason':'持仓估值不完整，请补齐相应估值依据'}
        return {'status':'CURRENT','reason':'报告与当前查看时点及账本依据一致'}
    except (QuantError,ValueError,KeyError,TypeError) as exc:
        return {'status':'UNVERIFIED','reason':'无法核验报告依据：'+str(exc)}
