"""Explicit, versioned hedge objectives; no inferred investor risk settings."""
from dataclasses import dataclass
import json
from ..common import QuantError,decimal as D,digest,canonical

FIELDS={'schema_version','name','version','mode','scope','benchmark','tools','target_beta','protection_fraction',
        'funding','funding_symbol','max_cash','max_premium','max_notional','max_contracts','max_trade_units',
        'residual_beta_tolerance','max_overhedge_fraction','commission_bps','fixed_trade_fee','option_fee_per_contract',
        'min_abs_proxy_beta','exit_days_before_expiry','min_days_to_expiry','max_days_to_expiry'}
TOOLS={'reduce_stock','inverse_etf','protective_put','collar','proxy_put'}


@dataclass(frozen=True)
class HedgeSpec:
    encoded:str

    @classmethod
    def from_dict(cls,body):
        if (not isinstance(body,dict) or set(body)!=FIELDS or type(body['schema_version']) is not int or body['schema_version']!=1
                or any(not isinstance(body[k],str) or not body[k].strip() for k in ('name','version','benchmark','mode','funding'))
                or body['mode'] not in {'beta_target','share_protection'}
                or body['funding'] not in {'cash_only','sell_scope'}
                or not isinstance(body['scope'],list) or not body['scope']
                or any(not isinstance(s,str) or not s for s in body['scope']) or len(set(body['scope']))!=len(body['scope'])
                or not isinstance(body['tools'],list) or not body['tools'] or any(not isinstance(t,str) for t in body['tools']) or not set(body['tools'])<=TOOLS
                or len(set(body['tools']))!=len(body['tools'])):
            raise QuantError('INVALID_HEDGE_SPEC','对冲目标需完整显式字段、版本、范围、方法及工具白名单')
        for key in ('max_cash','max_premium','max_notional','residual_beta_tolerance','max_overhedge_fraction',
                    'commission_bps','fixed_trade_fee','option_fee_per_contract','min_abs_proxy_beta'):
            if D(body[key])<0:raise QuantError('INVALID_HEDGE_SPEC','预算/费用/容差须非负：'+key)
        for key in ('max_contracts','max_trade_units','exit_days_before_expiry','min_days_to_expiry','max_days_to_expiry'):
            if type(body[key]) is not int or body[key]<0:raise QuantError('INVALID_HEDGE_SPEC','整数限制无效：'+key)
        if body['max_trade_units']>10000 or body['max_contracts']>1000 or body['commission_bps']>=10000:
            raise QuantError('INVALID_HEDGE_SPEC','候选枚举或费用超出工程支持范围')
        if not body['min_days_to_expiry']<=body['max_days_to_expiry'] or body['exit_days_before_expiry']>=body['min_days_to_expiry']:
            raise QuantError('INVALID_HEDGE_SPEC','到期窗口必须在明确退出窗口之后')
        if body['funding']=='sell_scope' and body['funding_symbol'] not in body['scope']:
            raise QuantError('INVALID_HEDGE_SPEC','筹资证券必须在允许调整的持仓范围内')
        if body['funding']=='cash_only' and body['funding_symbol'] is not None:
            raise QuantError('INVALID_HEDGE_SPEC','纯现金筹资不得暗含卖出证券')
        if body['mode']=='beta_target':
            if body['target_beta'] is None or body['protection_fraction'] is not None or D(body['target_beta'])<0:
                raise QuantError('INVALID_HEDGE_SPEC','账户Beta目标必须明确非负，不能混用股数保护目标')
        elif body['target_beta'] is not None or body['protection_fraction'] is None or not 0<=D(body['protection_fraction'])<=1:
            raise QuantError('INVALID_HEDGE_SPEC','股数保护比例须明确0至1，不混用账户Beta目标')
        return cls(canonical(body))

    @property
    def spec_hash(self):return digest(self.content())

    def content(self):return json.loads(self.encoded)
