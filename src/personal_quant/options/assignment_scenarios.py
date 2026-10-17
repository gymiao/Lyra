"""Explicit synthetic assignment fault inputs, never a real assignment forecast."""
import pandas as pd
from ..common import QuantError, decimal as D


def validate(rows, cycles, calendar, *, through, synthetic):
    if rows is None:
        return []
    if not through or not synthetic or not isinstance(rows, list) or not rows:
        raise QuantError('INVALID_ASSIGNMENT_SCENARIO', '指派故障场景只接受显式合成前缀及非空列表')
    result = []; seen = set()
    legs = {leg['contract_id']: (leg, cycle) for cycle in cycles for leg in cycle['legs']}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'contract_id', 'session', 'quantity'}:
            raise QuantError('INVALID_ASSIGNMENT_SCENARIO', '需合约ID、交易日、指派张数')
        identity = row['contract_id']
        if not isinstance(identity, str) or identity not in legs or identity in seen:
            raise QuantError('INVALID_ASSIGNMENT_SCENARIO', '指派合约需唯一且属于当前冻结周期')
        leg, cycle = legs[identity]
        try:
            day = pd.Timestamp(row['session'])
            quantity = D(row['quantity'])
            valid = (isinstance(row['session'], str) and day.strftime('%Y-%m-%d') == row['session']
                     and day in calendar.sessions and cycle['entry_submit_at'][:10] < row['session']
                     < min(leg['expiry'], cycle['exit_submit_at'][:10])
                     and type(row['quantity']) is int and 0 < quantity <= -D(leg['quantity']))
        except (ValueError, TypeError):
            valid = False
        if not valid:
            raise QuantError('INVALID_ASSIGNMENT_SCENARIO', '仅开仓后退出/到期前交易日，数量不超过实际空头')
        seen.add(identity)
        result.append({**row, 'underlying': leg['underlying'], 'right': leg['right'],
                       'strike': leg['strike'], 'expiry': leg['expiry']})
    return result


def validate_native(rows, events, contracts):
    """The pinned brokerage once assigned two despite requesting one: fail closed."""
    from .monthly_portfolio import event_contract
    native=[e for e in events if e['order_type']=='OptionExercise' and e['symbol']==e['order_symbol']
            and e['tag']=='SYNTHETIC_EXPLICIT_PARTIAL_ASSIGNMENT']
    seen=set()
    for e in native:
        identity=event_contract(e,contracts).contract_id
        matches=[row for row in rows if row['contract_id']==identity]
        if len(matches)!=1 or identity in seen:
            raise QuantError('LEAN_ASSIGNMENT_SCENARIO_MISMATCH','指派凭据重复或无对应冻结场景')
        row=matches[0]
        if (e['assignment'] is not True or e['in_the_money'] is not True or D(e['quantity'])!=D(row['quantity'])
                or pd.Timestamp(e['utc_time']).tz_convert('America/New_York').strftime('%Y-%m-%d')!=row['session']):
            raise QuantError('LEAN_ASSIGNMENT_SCENARIO_MISMATCH','原生指派日期/方向/数量与冻结场景不同')
        seen.add(identity)
    if seen!={row['contract_id'] for row in rows}:
        raise QuantError('LEAN_ASSIGNMENT_SCENARIO_MISMATCH','冻结场景尚未产生明确原生指派凭据，不生成成功账本')
