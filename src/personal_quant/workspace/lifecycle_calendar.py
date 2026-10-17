"""Read-only calendar of recorded positions and settlements; no expiry inference."""
import json
from datetime import date
from zoneinfo import ZoneInfo
from ..common import utc,decimal as D,digest,QuantError
from ..options.contracts import OptionContract

TRADE_KINDS={'BUY','SELL','OPTION_TRADE','OPTION_EXERCISE','OPTION_ASSIGNMENT','OPTION_EXPIRY','OPTION_CASH_SETTLEMENT'}


def calendar_view(book,account_id,as_of):
    clock=utc(as_of);events=book.active_events(account_id,as_of)
    snapshot=book.snapshot(account_id,as_of)
    versions={event['contract_version'] for event in events if event.get('contract_version')}
    quantities={}
    for event in events:
        version=event.get('contract_version')
        if not version:continue
        sign=(1 if event['trade_side']=='BUY' else -1) if event['kind']=='OPTION_TRADE' else (-1 if event['position_side']=='LONG' else 1)
        quantities[version]=quantities.get(version,D(0))+sign*D(event['quantity'])
    contracts=[];pending=[];decisions=[];calendar_checks=[]
    for version in sorted(versions):
        row=book.connection.execute('SELECT payload FROM option_contracts WHERE version_hash=?',(version,)).fetchone()
        contract=OptionContract.from_dict(json.loads(row[0]))
        quantity=str(quantities.get(version,D(0)))
        phase='OPEN_RECORDED' if D(quantity) else 'CLOSED_RECORDED'
        if D(quantity) and clock>utc(contract.exercise_cutoff_at):phase='PAST_CUTOFF_REQUIRE_RECEIPT'
        contracts.append({'contract_id':contract.contract_id,'contract_version':version,'underlying':contract.underlying,
                          'recorded_contracts':quantity,'expiry':contract.expiry,'last_trade_at':contract.last_trade_at,
                          'exercise_cutoff_at':contract.exercise_cutoff_at,'status':phase,
                          'calendar_days_to_expiry':(date.fromisoformat(contract.expiry)-clock.astimezone(ZoneInfo('America/New_York')).date()).days})
    for event in events:
        settlement=event.get('settlement_at')
        if event['kind'] in TRADE_KINDS and (settlement is None or utc(settlement)>clock):
            pending.append({'event_id':event['event_id'],'kind':event['kind'],'symbol':event.get('symbol'),
                            'settlement_at':settlement,'status':'UNKNOWN' if settlement is None else 'PENDING'})
    exists=lambda name:book.connection.execute('SELECT 1 FROM sqlite_master WHERE name=?',(name,)).fetchone()
    if exists('option_plans'):
        for row in book.connection.execute('SELECT payload FROM option_plans WHERE account_id=?',(account_id,)):
            plan=json.loads(row[0])
            if utc(plan['decision_at'])<=clock:
                decisions.append({'plan_id':plan['plan_id'],'decision_at':plan['decision_at'],
                    'applicable_session':None,'applicable_close':None,'source':'RECORDED_PLAN',
                    'meaning':'计划依据；未归档适用日时保持未知，不从成交日期倒推'})
    if exists('simulation_runs'):
        root=book.path.parent/'simulation';workspace=root/'workspace.json'
        identity=json.loads(workspace.read_text()) if workspace.is_file() else {}
        if identity.get('kind')=='options' and identity.get('account_id')==account_id:
            for row in book.connection.execute('SELECT run_id FROM simulation_runs'):
                directory=root/'options'/row[0]
                try:
                    settings=json.loads((directory/'settings.json').read_text());index=json.loads((directory/'calendar-index.json').read_text())
                    if (digest(index)!=settings['calendar_index_hash'] or index['request_hash']!=settings['request_hash']
                            or digest({'workspace':identity['workspace_id'],'settings':settings})!=row[0]):
                        raise ValueError('calendar index hash')
                    for entry in index['signals']:
                        if utc(entry['decision_at'])<=clock:
                            decisions.append({**entry,'run_id':row[0],'source':'FROZEN_SIGNAL',
                                'meaning':'冻结规则依据；generation_mode标识历史重建，不表示实际已成交'})
                except (OSError,ValueError,KeyError,TypeError) as exc:
                    calendar_checks.append({'run_id':row[0],'status':'UNVERIFIED_DECISION_INDEX','error_type':type(exc).__name__})
    paid={e['reference_event_id']:e for e in events if e['kind']=='DIVIDEND_PAYMENT' and e.get('reference_event_id')}
    dividends=[]
    for event in events:
        if event['kind']=='DIVIDEND_ACCRUAL':
            payment=paid.get(event['event_id']);expected=event.get('settlement_at')
            dividends.append({'event_id':event['event_id'],'symbol':event['symbol'],'accrual_at':event['effective_at'],
                'amount':event['amount'],'expected_payment_at':expected,
                'paid_at':payment['effective_at'] if payment else None,
                'status':'PAID_RECORDED' if payment else 'PENDING' if expected else 'UNKNOWN_PAYMENT_DATE'})
        elif event['kind']=='DIVIDEND_PAYMENT' and not event.get('reference_event_id'):
            dividends.append({'event_id':event['event_id'],'symbol':event['symbol'],'accrual_at':None,
                'amount':event['amount'],'expected_payment_at':None,'paid_at':event['effective_at'],'status':'PAID_RECORDED'})
    return {'account_id':account_id,'as_of':clock.isoformat(),'environment':book.environment,
            'data_type':'simulated_account' if book.environment=='demo' else 'recorded_account',
            'contracts':contracts,'pending_settlements':pending,'decisions':decisions,'calendar_checks':calendar_checks,
            'dividends':dividends,'dividend_evidence':'RECORDED' if dividends else 'UNKNOWN_NO_RECEIPTS','read_only':True,
            'account_checks':snapshot['anomalies'],
            'meaning':'到期日期只提醒核对；持仓关闭和现金到账仅依据账本事件，不自动生成行权或结算事实'}
