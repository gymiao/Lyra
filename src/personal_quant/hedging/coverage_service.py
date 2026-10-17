"""Read-only coverage from a single ledger prefix and registered contract terms."""
import json

from ..common import QuantError, decimal as D, digest, now_utc, utc
from ..options.contracts import OptionContract
from ..options.ledger import verify_contract_evidence
from ..options.lifecycle import refresh, pending_resources
from ..strategies.archive import source_fingerprint
from .allocation import coverage

FIELDS = {'schema_version', 'as_of', 'knowledge_cutoff', 'ledger_seq', 'ledger_view',
          'security_ids', 'allocations', 'inflight_plan_ids'}


def account_coverage(book, account_id, request):
    if (not isinstance(request, dict) or set(request) not in (FIELDS,FIELDS|{'security_versions'})
            or type(request['schema_version']) is not int or request['schema_version'] != 1
            or type(request['ledger_seq']) is not int or request['ledger_seq'] < 0
            or request['ledger_view'] not in ('known_then', 'restated')
            or not isinstance(request['security_ids'], dict)
            or any(not isinstance(k, str) or not k or not isinstance(v, str) or not v
                   for k, v in request['security_ids'].items())
            or len(set(request['security_ids'].values())) != len(request['security_ids'])
            or not isinstance(request['inflight_plan_ids'], list)
            or any(not isinstance(p, str) or not p for p in request['inflight_plan_ids'])
            or len(set(request['inflight_plan_ids'])) != len(request['inflight_plan_ids'])):
        raise QuantError('INVALID_COVERAGE_REQUEST', '覆盖请求需显式序号/知识视图/唯一证券ID映射/分配及在途计划ID')
    clock, known, now = utc(request['as_of']), utc(request['knowledge_cutoff']), utc(now_utc())
    if clock > now or known > now:
        raise QuantError('FUTURE_COVERAGE', '不能预先报告未来账户或未来取得的凭据')
    restated = request['ledger_view'] == 'restated'
    if restated and book.environment != 'demo':
        raise QuantError('RESTATED_DEMO_ONLY', '重述覆盖仅限明确标记的demo研究')
    if not restated and known > clock:
        raise QuantError('INVALID_COVERAGE_TIME', '当时所知视图不能使用覆盖时点之后的凭据')
    mapping = request['security_ids']; sequence = request['ledger_seq']
    identity_basis=None
    if 'security_versions' in request:
        from .securities import resolve
        identity_basis=resolve(book.path.parent,book.environment,request['security_versions'],mapping,clock,known)
    with book.transaction():
        book._require_account(account_id)
        if sequence > book.sequence(account_id):
            raise QuantError('INVALID_LEDGER_SEQUENCE', '覆盖序号必须是该账户已存在前缀')
        rows = [dict(r) for r in book.connection.execute(
            'SELECT seq,event_id,content_hash,effective_at,recorded_at,payload FROM events '
            'WHERE account_id=? AND seq<=? ORDER BY seq', (account_id, sequence))]
        if any(utc(r['recorded_at']) > known for r in rows):
            raise QuantError('LEDGER_NOT_KNOWN', '知识截止时尚未取得请求前缀内的凭据')
        state = book.snapshot(account_id, clock, ledger_seq=sequence)
        if state.get('anomalies'):
            raise QuantError('COVERAGE_LEDGER_ANOMALY', '账户存在未解决异常，不能发布完整保护覆盖')
        holdings = {}
        for symbol, quantity in state['positions'].items():
            if symbol not in mapping:
                raise QuantError('MISSING_SECURITY_ID', '实际持仓缺稳定证券ID映射：'+symbol)
            holdings[mapping[symbol]] = quantity
        contracts, actual, terms, inflight, plan_basis = {}, {}, {}, {}, []
        for e in book.active_events(account_id, clock, ledger_seq=sequence):
            if e['kind'].startswith('OPTION_'):
                c = OptionContract.from_dict(e['contract']); contracts[c.contract_id] = c

        def add_terms(c):
            c.require_standard_vanilla()
            row = book.connection.execute('SELECT payload,created_at FROM option_contracts WHERE version_hash=?',
                                          (c.version_hash,)).fetchone()
            if row is None or OptionContract.from_dict(json.loads(row['payload'])).version_hash != c.version_hash:
                raise QuantError('COVERAGE_CONTRACT_CONFLICT', '账户引用与注册合约版本不符')
            if utc(row['created_at']) > known:
                raise QuantError('ALLOCATION_TERMS_NOT_KNOWN', '知识截止时尚未注册该条款')
            if book.environment == 'real': verify_contract_evidence(book.path.parent, c)
            # Keep unrelated options in account risk even without a scope mapping.
            if c.underlying not in mapping: return
            terms[c.contract_id, c.version_hash] = {
                'security_id': mapping[c.underlying], 'right': c.right.lower(),
                'shares_per_contract': str(c.deliverable_shares), 'valid_from': c.listed_at,
                'valid_until': c.exercise_cutoff_at, 'recorded_at': row['created_at']}

        for symbol, quantity in state.get('option_positions', {}).items():
            c = contracts[symbol]; add_terms(c); actual[c.contract_id, c.version_hash] = quantity
        if request['inflight_plan_ids']:
            bodies = {b['plan_id']: b for b in refresh(book, account_id, clock, persist=False, ledger_seq=sequence)}
            for plan_id in request['inflight_plan_ids']:
                if plan_id not in bodies:
                    raise QuantError('UNKNOWN_OPTION_PLAN', '在途计划不属于该账户')
                # A prefix is insufficient for resources: preserve audit payloads and
                # actual registration times, never backdate later manual submissions.
                audits = []
                for r in book.connection.execute("SELECT details FROM tasks WHERE task_id LIKE 'option-manual:%'"):
                    audit = json.loads(r[0])
                    if (audit['request']['plan_id'] == plan_id
                            and utc(audit['request']['as_of']) <= clock
                            and audit['request']['expected_sequence'] <= sequence):
                        if utc(audit['recorded_at']) > known:
                            raise QuantError('PLAN_NOT_KNOWN', '在途计划含知识截止后才记录的人工状态')
                        audits.append(audit)
                body = bodies[plan_id]
                manual = body.get('manual_execution', {})
                if not audits or not manual.get('pending'):
                    raise QuantError('NO_INFLIGHT_OPTION_ORDER', '只读取明确记录且未结束的人工在途订单，不把草案当在途')
                _, _, remaining = pending_resources(body, {k: D(v) for k, v in body['progress']['filled_contracts'].items()})
                legs = {x['contract']['contract_id']: OptionContract.from_dict(x['contract']) for x in body['selection']['legs']}
                for order in manual['orders']:
                    c = legs[order['contract_id']]; add_terms(c)
                    key = c.contract_id, c.version_hash
                    quantity = D(remaining.get(c.contract_id, 0)) * (1 if order['side'] == 'BUY' else -1)
                    if key in inflight and inflight[key]*quantity < 0:
                        raise QuantError('CONFLICTING_INFLIGHT_DIRECTIONS', '同合约相反在途方向不能净额冒充保护')
                    inflight[key] = inflight.get(key, D(0)) + quantity
                plan_basis.append({'plan_id': plan_id, 'payload_hash': digest(body), 'audit_hash': digest(audits)})
        result = coverage(holdings, actual, inflight, request['allocations'], contract_terms=terms,
                          as_of=clock, knowledge_cutoff=known)
    result.update(artifact_type='hedge_coverage', account_id=account_id, environment=book.environment,
                  ledger_seq=sequence, ledger_view=request['ledger_view'], ledger_basis_hash=digest(rows),
                  security_ids=mapping, security_identity_qualification='显式研究映射；证券身份注册/来源资格尚待接入',
                  inflight_plan_basis=plan_basis, source_fingerprint=source_fingerprint(),
                  meaning='账本事实覆盖参考；不生成计划或预留，不授予真实交易权限')
    if identity_basis is not None:
        result['security_identity_basis']=identity_basis
        result['security_identity_qualification']='已绑定登记版本；仅声明身份，不授予来源/交易资格'
    result['coverage_id'] = digest(result)
    return result
