import copy

import pytest

from personal_quant.common import QuantError
from personal_quant.hedging.allocation import coverage

ASOF = '2026-10-09T21:00:00Z'


def row(**changes):
    result = dict(allocation_id='put-a', parent_id='parent-a', security_id='us-security-1',
                  contract_id='put-1', contract_version='terms-1', role='put_protection', state='actual',
                  share_start='0', share_end='100', contracts=1, shares_per_contract='100',
                  valid_from='2026-10-01T00:00:00Z', valid_until='2026-10-17T00:00:00Z', recorded_at=ASOF)
    return dict(result, **changes)


def contract(right='put', **changes):
    return dict(dict(security_id='us-security-1', right=right, shares_per_contract=100,
                     valid_from='2026-10-01T00:00:00Z', valid_until='2026-10-17T00:00:00Z', recorded_at=ASOF), **changes)


def check(rows, actual=None, inflight=None, shares='200', terms=None):
    if terms is None:
        terms = {('put-1', 'terms-1'): contract(), ('call-1', 'terms-1'): contract('call')}
    return coverage({'us-security-1': shares}, actual or {('put-1', 'terms-1'): 2}, inflight or {}, rows,
                    contract_terms=terms, as_of=ASOF, knowledge_cutoff=ASOF)


def test_collar_roles_can_share_but_do_not_double_protection():
    call = row(allocation_id='call-a', contract_id='call-1', role='call_coverage')
    result = check([row(), call], {('put-1', 'terms-1'): 1, ('call-1', 'terms-1'): -1})
    assert result['actual_protected_shares'] == {'us-security-1': '100'}
    assert result['inflight_intended_shares'] == {'us-security-1': '0'}
    assert result['unallocated_actual_contracts'] == [] and not result['creates_reservations']


@pytest.mark.parametrize('changes', [{'parent_id': 'parent-b'}, {'parent_id': 'parent-a'},
    {'parent_id': 'new-version-parent', 'role': 'call_coverage', 'contract_id': 'call-1'}])
def test_other_intent_or_same_role_cannot_reuse_shares(changes):
    duplicate = row(allocation_id='other', **changes)
    with pytest.raises(QuantError, match='重复') as exc:
        check([row(), duplicate], {('put-1', 'terms-1'): 2, ('call-1', 'terms-1'): -1})
    assert exc.value.code == 'DUPLICATE_PROTECTION'


def test_two_distinct_slices_and_inflight_not_actual():
    pending = row(allocation_id='put-b', parent_id='parent-b', state='inflight', share_start=100, share_end=200)
    result = check([row(), pending], inflight={('put-1', 'terms-1'): 1})
    assert result['actual_protected_shares']['us-security-1'] == '100'
    assert result['inflight_intended_shares']['us-security-1'] == '100'
    assert result['unallocated_actual_contracts'][0]['unallocated_contracts'] == '1'


@pytest.mark.parametrize('changes,code', [
    ({'share_end': 201, 'contracts': 3}, 'ALLOCATION_EXCEEDS_HOLDINGS'),
    ({'contracts': 3}, 'ALLOCATION_EXCEEDS_CONTRACTS'),
    ({'contract_version': 'future-terms'}, 'ALLOCATION_TERMS_MISMATCH'),
    ({'state': 'inflight'}, 'ALLOCATION_POSITION_MISMATCH'),
    ({'role': 'call_coverage'}, 'ALLOCATION_TERMS_MISMATCH'),
    ({'recorded_at': '2026-10-10T00:00:00Z'}, 'ALLOCATION_NOT_KNOWN'),
    ({'shares_per_contract': 10}, 'INVALID_ALLOCATION'),
    ({'contracts': True}, 'INVALID_ALLOCATION')])
def test_facts_limits_units_and_known_time(changes, code):
    with pytest.raises(QuantError) as exc:
        check([row(**changes)])
    assert exc.value.code == code


def test_expired_references_do_not_grant_coverage_or_hide_unrelated_options():
    expired = row(valid_until=ASOF)
    result = check([expired], {('put-1', 'terms-1'): 2, ('unrelated-call', 'terms-2'): -3})
    assert result['actual_protected_shares']['us-security-1'] == '0'
    assert result['inactive_allocations'] == ['put-a']
    assert len(result['unallocated_actual_contracts']) == 2


@pytest.mark.parametrize('changes', [{'security_id': 'proxy-etf'}, {'right': 'call'}, {'shares_per_contract': 50}])
def test_proxy_or_wrong_deliverable_cannot_claim_direct_protection(changes):
    terms = {('put-1', 'terms-1'): contract()}
    terms['put-1', 'terms-1'].update(changes)
    with pytest.raises(QuantError) as exc: check([row()], terms=terms)
    assert exc.value.code == 'ALLOCATION_TERMS_MISMATCH'


@pytest.mark.parametrize('changes,code', [
    ({'recorded_at': '2026-10-10T00:00:00Z'}, 'ALLOCATION_TERMS_NOT_KNOWN'),
    ({'valid_until': '2026-10-16T00:00:00Z'}, 'ALLOCATION_TERMS_EXPIRED'),
    ({'valid_from': '2026-10-02T00:00:00Z'}, 'ALLOCATION_TERMS_EXPIRED')])
def test_cannot_extend_contract_window_or_use_later_terms(changes, code):
    with pytest.raises(QuantError) as exc:
        check([row()], terms={('put-1', 'terms-1'): contract(**changes)})
    assert exc.value.code == code


def test_readonly_deterministic_and_duplicate_identity_rejected():
    rows = [row()]; original = copy.deepcopy(rows)
    a = check(rows); b = check(rows)
    assert a == b and rows == original and not a['executable']
    with pytest.raises(QuantError) as exc: check([row(), row()])
    assert exc.value.code == 'DUPLICATE_ALLOCATION'


def test_earlier_knowledge_cutoff_keeps_previously_known_protection():
    terms={('put-1','terms-1'):contract(recorded_at='2026-10-07T00:00:00Z')}
    result=coverage({'us-security-1':100},{('put-1','terms-1'):1},{},
        [row(recorded_at='2026-10-07T00:00:00Z')],contract_terms=terms,
        as_of=ASOF,knowledge_cutoff='2026-10-08T00:00:00Z')
    assert result['actual_protected_shares']['us-security-1']=='100'
