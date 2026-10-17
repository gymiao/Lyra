"""Read-only proposals from an immutable risk archive and explicit policy."""
from ..common import QuantError,digest
from ..strategies.archive import source_fingerprint
from .archive import load
from .spec import HedgeSpec
from .sizing import stock_candidate


def preview(book,account_id,request):
    fields={'exposure_id','spec','method','proxy','funding_quote'}
    if not isinstance(request,dict) or set(request) not in (fields,{'exposure_id','spec','method','option'}):
        raise QuantError('INVALID_HEDGE_PREVIEW','预览需归档风险ID、完整目标、方法和候选/筹资报价')
    book._require_account(account_id)
    risk=load(book.path.parent/'hedging/exposures',request['exposure_id'])
    if risk['account_id']!=account_id or risk['environment']!=book.environment:
        raise QuantError('ENVIRONMENT_MISMATCH','风险归档不属于指定账户/环境')
    spec=HedgeSpec.from_dict(request['spec'])
    if 'option' in request:
        from .option_preview import preview_options
        result=preview_options(book,account_id,risk,spec,request['method'],request['option'])
    else:result=stock_candidate(risk,spec,request['method'],request['proxy'],funding_quote=request['funding_quote'])
    result.update(account_id=account_id,environment=book.environment,as_of=risk['as_of'],
        data_types=risk['data_types'],spec=spec.content(),source_fingerprint=source_fingerprint(),
        remaining_gates=['证券/产品及单位资格','现时资源及对账复核','候选冻结和逐阶段计划','执行价与成交/结算证据'])
    result['preview_hash']=digest(result);return result
