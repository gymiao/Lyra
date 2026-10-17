"""Frozen monthly baskets, retaining every original instrument decision."""
import re
from ..common import QuantError,digest,decimal as D
from .monthly import validate_frozen
from .catalog import MONTHLY_RESEARCH


def normalize(signals,packages=None,*,minimum_batches=2,wheel=False):
    if not isinstance(signals,list) or len(signals)<minimum_batches:
        raise QuantError('INVALID_MONTHLY_REPLAY','至少两个冻结月度批次')
    multi=isinstance(signals[0],list)
    batches=signals if multi else [[s] for s in signals]
    if any(not isinstance(batch,list) or not 1<=len(batch)<=10 for batch in batches):
        raise QuantError('INVALID_MONTHLY_REPLAY','每月需1到10个明确冻结标的，不混用单信号/批次格式')
    batches=[[validate_frozen(s) for s in batch] for batch in batches]
    counts=[[1]*len(batch) for batch in batches] if packages is None else packages if multi else [[n] for n in packages] if isinstance(packages,list) else None
    if (not isinstance(counts,list) or len(counts)!=len(batches) or any(not isinstance(n,list) or len(n)!=len(batch)
            or any(type(q) is not int or not 1<=q<=100 for q in n) for batch,n in zip(batches,counts))):
        raise QuantError('INVALID_MONTHLY_REPLAY','包数须逐月逐标的明确匹配，每项整数1到100')
    identities=None;template=None;decisions=[]
    for batch in batches:
        if len({s['selection']['underlying'] for s in batch})!=len(batch):
            raise QuantError('DUPLICATE_MONTHLY_UNDERLYING','同月每个期权标的仅一份冻结决定')
        if any(s['selection']['data_type']!='synthetic' for s in batch):
            raise QuantError('FIXTURE_ONLY','多标的机械回放不冒充真实历史资格')
        current=[(s['intent']['scope'],s['selection']['underlying'],s['selection']['template_id']) for s in batch]
        if identities is None:identities=current;template=current[0][2]
        same=([(scope,u) for scope,u,_ in current]==[(scope,u) for scope,u,_ in identities]) if wheel else current==identities
        if not same or any((t not in {'cash_secured_put','covered_call'} if wheel else t!=template or t not in MONTHLY_RESEARCH) or not re.fullmatch(r'[A-Z][A-Z0-9.-]{0,15}',u) for _,u,t in current):
            raise QuantError('INVALID_MONTHLY_REPLAY','各月须同模板、同显式标的/范围及顺序，不能隐式改变组合')
        for field in ('decision_at','applicable_session','applicable_close'):
            if len({s[field] for s in batch})!=1:raise QuantError('MONTHLY_BATCH_CLOCK_MISMATCH','同批决定及成交时点须一致')
        if len({(s['selection']['expiry'],s['selection']['exit_days_before_expiry']) for s in batch})!=1:
            raise QuantError('MONTHLY_BATCH_EXIT_MISMATCH','同批合约须同退出日与到期日，不隐式改退出规则')
        decisions.append(batch[0]['decision_at'])
    if decisions!=sorted(set(decisions)):raise QuantError('INVALID_MONTHLY_REPLAY','批次按决定时点严格递增')
    if wheel and (multi or batches[0][0]['selection']['template_id']!='cash_secured_put' or any(n!=counts[0] for n in counts)):
        raise QuantError('INVALID_WHEEL_PATH','Wheel需单标的、固定包数、先现金担保Put，阶段按实际交割验证')
    return batches,counts,multi


def flat(signals):
    return [s for batch in signals for s in batch] if signals and isinstance(signals[0],list) else signals


def signal_id(batch):
    return batch[0]['monthly_signal_id'] if len(batch)==1 else 'monthly-basket:'+digest([s['monthly_signal_id'] for s in batch])


def event_identity(event,descriptors):
    """Match performance descriptors without coupling math to full term validation."""
    matches=[identity for identity,c in descriptors.items() if c['expiry']==event['expiry']
             and c['right']==event['right'] and D(c['strike'])==D(event['strike'])]
    if event.get('underlying') is not None:matches=[identity for identity in matches if descriptors[identity].get('underlying')==event['underlying']]
    if len(matches)!=1:raise QuantError('LEAN_UNIT_MAPPING_FAILED','需标的/到期日/类型/行权价唯一匹配原冻结合约，不能猜测合约身份')
    return matches[0]


def event_contract(event,contracts):
    descriptors={identity:dict(underlying=c.underlying,expiry=c.expiry,right=c.right,strike=c.strike) for identity,c in contracts.items()}
    return contracts[event_identity(event,descriptors)]
