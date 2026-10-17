"""Read-only summaries of separately funded paper workspaces; no merged ledger."""
from pathlib import Path
import sqlite3
from ..common import QuantError, decimal as D, utc, digest
from ..config import Config
from .ledger import Ledger
from .report import load_account_report


def aggregate(request,as_of):
    if set(request)!={'schema_version','max_age_seconds','workspaces'} or request['schema_version']!=1:
        raise QuantError('INVALID_PAPER_SUMMARY','汇总需要schema_version、明确时效和工作区清单')
    limit=D(request['max_age_seconds'])
    if limit<=0 or not isinstance(request['workspaces'],list) or not request['workspaces']:
        raise QuantError('INVALID_PAPER_SUMMARY','工作区不能空，时效须为正秒数')
    rows=[];identities=set();names=set();clock=utc(as_of)
    for entry in request['workspaces']:
        if set(entry)!={'name','workspace','config','report'} or not isinstance(entry['name'],str) or not entry['name']:
            raise QuantError('INVALID_PAPER_SUMMARY','工作区条目字段无效')
        root=Path(entry['workspace']).resolve()
        if not root.is_dir() or root in identities or entry['name'] in names:
            raise QuantError('DUPLICATE_PAPER_WORKSPACE','工作区缺失、路径或名称重复，禁止重复汇总')
        identities.add(root);names.add(entry['name'])
        def inside(value):
            value=Path(value)
            target=(root/value).resolve()
            if value.is_absolute() or '..' in value.parts or not target.is_relative_to(root):
                raise QuantError('UNSAFE_PAPER_SUMMARY','配置和报告必须位于各自工作区内')
            return target
        config=Config.load(inside(entry['config']))
        if config.environment!='paper':raise QuantError('PAPER_ONLY','只读汇总只接受独立paper工作区，不混入真实或demo资金')
        database=inside(config.runtime_dir)/'account.sqlite'
        if not database.is_file():raise QuantError('UNKNOWN_PAPER_WORKSPACE','工作区尚无账户数据库；汇总不会创建它')
        report=load_account_report(inside(entry['report']))
        if report['environment']!='paper' or report['currency']!='USD':raise QuantError('ENVIRONMENT_MISMATCH','报告账户类型或币种不一致')
        problems=[]
        age=(clock-utc(report['as_of'])).total_seconds()
        if age<0:problems.append('REPORT_IN_FUTURE')
        elif age>float(limit):problems.append('STALE_REPORT')
        connection=sqlite3.connect(database.as_uri()+'?mode=ro',uri=True);connection.row_factory=sqlite3.Row
        try:
            book=Ledger.__new__(Ledger);book.path=database;book.environment='paper';book.connection=connection
            account=connection.execute('SELECT * FROM accounts').fetchall()
            if len(account)!=1 or account[0]['id']!=report['account_id'] or account[0]['environment']!='paper':
                raise QuantError('ENVIRONMENT_MISMATCH','报告与工作区单账户不一致')
            if book.sequence(report['account_id'])!=report['ledger_seq']:problems.append('REPORT_LEDGER_CHANGED')
            snapshot=book.snapshot(report['account_id'],report['as_of'],report['prices'])
            for key in ['equity','settled_cash','positions','net_contributions','investment_pnl','option_positions']:
                if snapshot.get(key)!=report.get(key):problems.append('REPORT_FACTS_DIFFER:'+key)
            if snapshot['anomalies']:problems.append('ACCOUNT_ANOMALIES')
        finally:connection.close()
        if report['equity'] is None:problems.append('INCOMPLETE_VALUATION')
        rows.append({'name':entry['name'],'workspace':str(root),'account_id':report['account_id'],
            'as_of':report['as_of'],'report_id':report['report_id'],'equity':report['equity'],
            'settled_cash':report['settled_cash'],'net_contributions':report['net_contributions'],
            'investment_pnl':report['investment_pnl'],'status':'PASSED' if not problems else 'BLOCKED','issues':problems})
    reasons=[]
    if len({row['as_of'] for row in rows})!=1:reasons.append('DIFFERENT_VALUATION_TIMES')
    if any(row['status']!='PASSED' for row in rows):reasons.append('INCOMPLETE_OR_STALE_WORKSPACE')
    total=None if reasons else {key:str(sum((D(row[key]) for row in rows),D(0)))
        for key in ['equity','settled_cash','net_contributions','investment_pnl']}
    return {'status':'BLOCKED' if reasons else 'PASSED','data_type':'separate_paper_accounts','as_of':as_of,
            'request_hash':digest(request),'read_only':True,'workspaces':rows,'totals':total,'issues':reasons,
            'return':None,'reason':'只汇总独立模拟账户同一时点金额；不合并现金、事件、持仓或策略收益率，不自动选择赢家'}
