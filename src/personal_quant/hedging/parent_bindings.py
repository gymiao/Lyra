"""Bind share-coverage references to immutable selected parent decisions."""
from collections import defaultdict

from ..common import QuantError, decimal as D
from .intents import records
from .intent_actions import history as closures


def resolve(book,account_id,allocations,versions,*,changed=(),old=None):
    if (not isinstance(versions,dict) or set(versions)!={r['allocation_id'] for r in allocations}
            or any(not isinstance(v,str) or not v for v in versions.values())):
        raise QuantError('HEDGE_PARENT_BINDINGS_REQUIRED','每个保留的保护分配须明确确切父版本')
    parents={r['version_hash']:r for r in records(book,account_id)}
    closed={r['hedge_id'] for r in closures(book,account_id)}
    heads={}
    for parent in parents.values():
        if parent['hedge_id'] not in heads or parent['revision']>heads[parent['hedge_id']]['revision']:
            heads[parent['hedge_id']]=parent
    previous=(old or {}).get('parent_versions',{})
    basis={};used=defaultdict(lambda:D(0))
    for row in allocations:
        identity=row['allocation_id'];version=versions[identity]
        parent=parents.get(version)
        if parent is None:raise QuantError('UNKNOWN_HEDGE_PARENT_VERSION','保护分配的父版本不属于该账户')
        if (row['parent_id']!=parent['hedge_id'] or row['security_id'] not in parent['scope']):
            raise QuantError('HEDGE_ALLOCATION_SCOPE_MISMATCH','保护分配父ID/稳定证券范围与原决定不符')
        if identity in previous and previous[identity]!=version:
            raise QuantError('ALLOCATION_PARENT_VERSION_CONFLICT','原分配ID不能静默换父版本；须退出并用新ID登记')
        if identity in changed or identity not in previous:
            if parent['hedge_id'] in closed:
                raise QuantError('HEDGE_INTENT_CLOSED','不能向已关闭父意图新增或修改保护分配')
            if heads[parent['hedge_id']]['version_hash']!=version:
                raise QuantError('STALE_HEDGE_INTENT_VERSION','新增保护引用须绑定最新父修订')
        matching=[leg for leg in parent['candidate'].get('selection',{}).get('legs',[])
                  if leg['contract']['contract_id']==row['contract_id']]
        if len(matching)!=1:
            raise QuantError('HEDGE_ALLOCATION_CANDIDATE_MISMATCH','保护合约未在原父候选中选定')
        leg=matching[0];contract=leg['contract'];role=row['role']
        from ..options.contracts import OptionContract
        terms=OptionContract.from_dict(contract)
        if (terms.version_hash!=row['contract_version'] or
                (role=='put_protection' and (terms.right!='PUT' or D(leg['quantity_per_package'])<=0)) or
                (role=='call_coverage' and (terms.right!='CALL' or D(leg['quantity_per_package'])>=0))):
            raise QuantError('HEDGE_ALLOCATION_CANDIDATE_MISMATCH','保护角色/方向或确切合约版本与父候选不符')
        packages=D(parent['candidate']['planned_total_packages'])
        key=version,terms.version_hash
        used[key]+=D(row['contracts'])
        if used[key]>packages*abs(D(leg['quantity_per_package'])):
            raise QuantError('HEDGE_ALLOCATION_EXCEEDS_TARGET','已成交和在途保护张数合计超过该父冻结目标')
        basis[identity]={'parent_version':version,'parent_record_hash':parent['record_hash'],
                         'candidate_hash':parent['candidate']['preview_hash']}
    return basis


def validate(book,account_id,record):
    if record.get('schema_version')!=2:return
    # Historical references remain valid after closure or a later parent revision.
    basis=resolve(book,account_id,record['allocations'],record['parent_versions'],old=record)
    if basis!=record['parent_basis']:
        raise QuantError('CORRUPT_ALLOCATION_PARENT','保护分配原父/候选引用改变')

