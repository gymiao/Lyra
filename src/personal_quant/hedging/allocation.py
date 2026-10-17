"""Validate explicit share slices against frozen holdings and option facts.

This is a read-only reference calculation, not another reservation ledger.
Share offsets identify coverage slices, not tax lots or broker share IDs.
"""
from collections import defaultdict

from ..common import QuantError, decimal as D, digest, utc

FIELDS = {'allocation_id', 'parent_id', 'security_id', 'contract_id', 'contract_version',
          'role', 'state', 'share_start', 'share_end', 'contracts', 'shares_per_contract',
          'valid_from', 'valid_until', 'recorded_at'}


def coverage(holdings, option_positions, inflight_positions, allocations, *, contract_terms, as_of, knowledge_cutoff):
    """Positions are keyed by (contract_id, version), with signed whole contracts.

    Put and covered-call roles in one parent may use the same share slice;
    separate parents may not. Inflight positions require caller-supplied,
    versioned plan facts and never contribute to actual protection.
    """
    clock, known = utc(as_of), utc(knowledge_cutoff)
    # View policy belongs to the adapter: known-then may use an earlier cutoff,
    # while explicitly labelled restatement can use later recorded receipts.
    if not isinstance(allocations, list) or not all(isinstance(x, dict) for x in allocations):
        raise QuantError('INVALID_ALLOCATION', '保护分配须为显式引用列表')
    shares = {key: D(value) for key, value in holdings.items()}
    if any(not isinstance(key, str) or not key or value < 0 for key, value in shares.items()):
        raise QuantError('INVALID_ALLOCATION', '稳定证券ID及非负实际持股数量必填')
    positions = {}
    for state, supplied in [('actual', option_positions), ('inflight', inflight_positions)]:
        for key, value in supplied.items():
            quantity = D(value)
            if (not isinstance(key, tuple) or len(key) != 2
                    or any(not isinstance(part, str) or not part for part in key)
                    or quantity != quantity.to_integral_value()):
                raise QuantError('INVALID_ALLOCATION', '确切合约版本及有符号整数张数必填')
            positions[state, key] = quantity
    used, slices, active, inactive, seen = defaultdict(int), defaultdict(list), [], [], set()
    totals = {state: defaultdict(lambda: D(0)) for state in ('actual', 'inflight')}
    for row in allocations:
        if (set(row) != FIELDS or any(not isinstance(row[k], str) or not row[k] for k in
                ('allocation_id', 'parent_id', 'security_id', 'contract_id', 'contract_version'))
                or not isinstance(row['role'], str) or row['role'] not in {'put_protection', 'call_coverage'}
                or not isinstance(row['state'], str) or row['state'] not in {'actual', 'inflight'}
                or type(row['contracts']) is not int or row['contracts'] <= 0):
            raise QuantError('INVALID_ALLOCATION', '分配身份/角色/状态/张数不完整')
        if row['allocation_id'] in seen:
            raise QuantError('DUPLICATE_ALLOCATION', '同一分配ID不能重复')
        seen.add(row['allocation_id'])
        start, end, unit = (D(row[k]) for k in ('share_start', 'share_end', 'shares_per_contract'))
        begin, until, received = (utc(row[k]) for k in ('valid_from', 'valid_until', 'recorded_at'))
        if (start < 0 or end <= start or unit <= 0 or end-start > unit*row['contracts'] or until <= begin):
            raise QuantError('INVALID_ALLOCATION', '股数切片/经核验交割单位/有效窗口无效')
        if received > known:
            raise QuantError('ALLOCATION_NOT_KNOWN', '知识截止时尚未收到保护分配依据')
        if not begin <= clock < until:
            inactive.append(row['allocation_id'])
            continue
        security = row['security_id']
        if security not in shares or end > shares[security]:
            raise QuantError('ALLOCATION_EXCEEDS_HOLDINGS', '分配不能超过冻结的实际持股')
        for previous, left, right in slices[security]:
            if max(start, left) < min(end, right) and (
                    row['parent_id'] != previous['parent_id'] or row['role'] == previous['role']):
                raise QuantError('DUPLICATE_PROTECTION', '跨意图或同角色不能重复引用同一股数切片')
        key = row['contract_id'], row['contract_version']
        terms = contract_terms.get(key)
        expected_right = 'put' if row['role'] == 'put_protection' else 'call'
        if (not isinstance(terms, dict) or set(terms) != {'security_id', 'right', 'shares_per_contract',
                                                      'valid_from', 'valid_until', 'recorded_at'}
                or terms['security_id'] != security or terms['right'] != expected_right
                or D(terms['shares_per_contract']) != unit):
            raise QuantError('ALLOCATION_TERMS_MISMATCH', '分配须与确切条款的标的/权利/交割单位一致；代理Put不算直接股数保护')
        if utc(terms['recorded_at']) > known:
            raise QuantError('ALLOCATION_TERMS_NOT_KNOWN', '知识截止时尚未取得条款版本')
        if not utc(terms['valid_from']) <= begin < until <= utc(terms['valid_until']):
            raise QuantError('ALLOCATION_TERMS_EXPIRED', '分配窗口必须包含于该合约条款有效窗口')
        signed = positions.get((row['state'], key), D(0))
        if ((row['role'] == 'put_protection' and signed <= 0)
                or (row['role'] == 'call_coverage' and signed >= 0)):
            raise QuantError('ALLOCATION_POSITION_MISMATCH', '分配方向与确切合约版本事实不符')
        used[row['state'], key] += row['contracts']
        if used[row['state'], key] > abs(signed):
            raise QuantError('ALLOCATION_EXCEEDS_CONTRACTS', '分配张数超过实际或明确在途张数')
        slices[security].append((row, start, end))
        active.append(row['allocation_id'])
        if row['role'] == 'put_protection':
            totals[row['state']][security] += end-start
    result = {'schema_version': 1, 'as_of': clock.isoformat(), 'knowledge_cutoff': known.isoformat(),
              'active_allocations': sorted(active), 'inactive_allocations': sorted(inactive),
              'actual_protected_shares': {k: str(totals['actual'][k]) for k in sorted(shares)},
              'inflight_intended_shares': {k: str(totals['inflight'][k]) for k in sorted(shares)},
              'unallocated_actual_contracts': [
                  {'contract_id': key[0], 'contract_version': key[1],
                   'signed_contracts': str(value), 'unallocated_contracts': str(abs(value)-used[state, key])}
                  for (state, key), value in sorted(positions.items())
                  if state == 'actual' and abs(value) > used[state, key]],
              'creates_reservations': False, 'executable': False,
              'basis_hash': digest({'holdings': holdings,
                  'positions': [{'state': state, 'contract_id': key[0], 'version': key[1], 'quantity': str(value)}
                                for (state, key), value in sorted(positions.items())],
                  'contract_terms': [{'contract_id': key[0], 'version': key[1], 'terms': value}
                                     for key, value in sorted(contract_terms.items())], 'allocations': allocations})}
    result['allocation_hash'] = digest(result)
    return result
