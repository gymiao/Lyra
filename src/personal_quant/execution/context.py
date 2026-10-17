"""Typed plan intent: monthly strategy signals or explicit hedge stages."""
from ..common import QuantError


def intent_context(body):
    if body.get('purpose')=='simulation_stock':
        context=body.get('simulation_context')
        if (body.get('environment')!='demo' or body.get('signal') is not None or not isinstance(context,dict)
                or context.get('schema_version')!=1 or not all(isinstance(context.get(k),str) and context[k]
                    for k in ('run_id','cycle_id','eligible_session','valid_through_session','reason'))):
            raise QuantError('CORRUPT_SIMULATION_STOCK_PLAN','模拟股票计划必须有明确周期身份，不借用股票策略信号')
        return context
    if body.get('purpose') == 'hedge_stage':
        context = body.get('hedge_context')
        if (not isinstance(context, dict) or context.get('schema_version') != 1
                or not all(isinstance(context.get(k), str) and context[k]
                           for k in ('hedge_id', 'parent_version', 'eligible_session',
                                     'valid_through_session', 'reason'))
                or body.get('signal') is not None):
            raise QuantError('CORRUPT_HEDGE_STOCK_PLAN', '对冲股票计划缺少独立父意图，不能借用策略信号')
        if (context.get('action','OPEN') not in {'OPEN','CLOSE'} or (context.get('action')=='CLOSE'
                and (not isinstance(context.get('opening_plan_id'),str) or not context['opening_plan_id']))):
            raise QuantError('CORRUPT_HEDGE_STOCK_PLAN','股票退出须明确原OPEN计划')
        return context
    if body.get('purpose') not in {None, 'monthly_strategy'}:
        raise QuantError('UNKNOWN_PLAN_PURPOSE', '股票计划用途不受支持')
    return body['signal']
