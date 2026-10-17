"""Frozen fact-prefix diagnostics; no invented quotes or execution permission."""
import json
from ..common import QuantError, digest, utc


def capture(book, account_id, before_sequence, as_of):
    clock = utc(as_of).isoformat()
    rows = book.connection.execute(
        'SELECT seq,payload FROM events WHERE account_id=? AND seq>? ORDER BY seq',
        (account_id, before_sequence)).fetchall()
    views = []
    for row in rows:
        fact = json.loads(row['payload'])
        # Sequence distinguishes facts even when their effective timestamps coincide.
        state = book.snapshot(account_id, fact['effective_at'], ledger_seq=row['seq'])
        prefix = book.connection.execute(
            'SELECT seq,payload FROM events WHERE account_id=? AND seq<=? ORDER BY seq',
            (account_id, row['seq'])).fetchall()
        views.append({'event_id': fact['event_id'], 'event_hash': digest(fact),
                      'ledger_seq': row['seq'], 'effective_at': fact['effective_at'],
                      'ledger_prefix_hash': digest([dict(item) for item in prefix]),
                      'status': 'REVIEW_REQUIRED' if state['anomalies'] else 'NO_ACCOUNT_ANOMALY',
                      'snapshot': state, 'valuation_status': 'NOT_EVALUATED'})
    final = book.snapshot(account_id, clock)
    value = {'schema_version': 1, 'account_id': account_id,
             'before_sequence': before_sequence, 'after_sequence': book.sequence(account_id),
             'as_of': clock, 'prefixes': views, 'final_snapshot': final,
             'has_intermediate_anomaly': any(v['status']=='REVIEW_REQUIRED' for v in views),
             'current_account_anomaly': bool(final['anomalies']),
             'meaning': '按入账序号重建生效时点；保留中间异常。预留/待核实按审计时状态；'
                        '无估值报价、压力或来源资格，不代表当时实时知识、异常已核实或可执行'}
    return {**value, 'audit_hash': digest(value)}


def validate(book, account_id, value):
    if (not isinstance(value, dict) or value.get('schema_version') != 1
            or value.get('account_id') != account_id
            or value.get('audit_hash') != digest({k:v for k,v in value.items() if k!='audit_hash'})):
        raise QuantError('CORRUPT_OPTION_AUDIT', '逐凭据风险审计哈希或账户不一致')
    rows = book.connection.execute(
        'SELECT seq,payload FROM events WHERE account_id=? AND seq>? AND seq<=? ORDER BY seq',
        (account_id, value['before_sequence'], value['after_sequence'])).fetchall()
    if [row['seq'] for row in rows] != [v['ledger_seq'] for v in value['prefixes']]:
        raise QuantError('CORRUPT_OPTION_AUDIT', '逐凭据风险审计缺少事实前缀')
    for row, view in zip(rows, value['prefixes']):
        fact = json.loads(row['payload'])
        prefix = book.connection.execute(
            'SELECT seq,payload FROM events WHERE account_id=? AND seq<=? ORDER BY seq',
            (account_id, row['seq'])).fetchall()
        if (view['event_id'] != fact['event_id'] or view['event_hash'] != digest(fact)
                or view['effective_at'] != fact['effective_at']
                or view['ledger_prefix_hash'] != digest([dict(item) for item in prefix])):
            raise QuantError('CORRUPT_OPTION_AUDIT', '逐凭据风险审计与原始账本前缀不一致')
        expected = book.snapshot(account_id, fact['effective_at'], ledger_seq=row['seq'])
        for key in ('settled_cash','receivables','payables','positions','option_positions'):
            if view['snapshot'].get(key) != expected.get(key):
                raise QuantError('CORRUPT_OPTION_AUDIT', '逐凭据财务余额与原始账本前缀不一致')


def history(book, account_id):
    """Read existing audits without manufacturing proof for legacy imports."""
    result = []
    for row in book.connection.execute(
            "SELECT details FROM tasks WHERE task_id LIKE 'option-receipt-batch:%' "
            "OR task_id LIKE 'option-resolution:%' ORDER BY rowid"):
        audit = json.loads(row['details'])
        if audit['account_id'] != account_id:
            continue
        value = audit.get('risk_history')
        if value is not None:
            validate(book, account_id, value)
        result.append({'audit_task_id': audit.get('audit_task_id'),
                       'request_id': audit['request']['request_id'] if 'request' in audit else audit['event_id'],
                       'proof_status': 'FROZEN_PREFIXES' if value is not None else 'LEGACY_UNVERIFIED',
                       'risk_history': value})
    return result
