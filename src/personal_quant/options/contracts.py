"""Explicit vanilla contract units; unknown adjusted deliverables fail closed."""
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from ..common import QuantError, decimal, digest, utc


@dataclass(frozen=True)
class OptionContract:
    contract_id: str
    underlying: str
    right: str
    strike: Decimal
    expiry: str
    last_trade_at: str
    exercise_cutoff_at: str
    listed_at: str
    style: str
    settlement: str
    currency: str
    quote_multiplier: Decimal
    deliverable_shares: Decimal
    deliverable_cash: Decimal
    exercise_cash: Decimal
    tick_size: Decimal
    revision: str
    evidence_hash: str
    market_timezone: str = 'America/New_York'

    @classmethod
    def from_dict(cls, body):
        try:
            obj = cls(**body)
        except TypeError as exc:
            raise QuantError('INVALID_OPTION_CONTRACT', '合约字段缺失或包含未知字段') from exc
        for name in ('strike','quote_multiplier','deliverable_shares','deliverable_cash','exercise_cash','tick_size'):
            object.__setattr__(obj, name, decimal(getattr(obj, name)))
        if obj.right not in {'CALL','PUT'} or obj.style not in {'AMERICAN','EUROPEAN'} or obj.settlement not in {'PHYSICAL','CASH'}:
            raise QuantError('INVALID_OPTION_CONTRACT', '期权类型、行权方式或结算方式无效')
        if obj.currency != 'USD' or obj.market_timezone != 'America/New_York':
            raise QuantError('UNSUPPORTED_OPTION_MARKET', '当前合约适配仅支持纽约时区/USD')
        if any(getattr(obj, n) <= 0 for n in ('strike','quote_multiplier','exercise_cash','tick_size')) or obj.deliverable_shares < 0 or obj.deliverable_cash < 0:
            raise QuantError('INVALID_OPTION_CONTRACT', '乘数/价格/行权现金必须为正，交割物不能为负')
        if not all(isinstance(getattr(obj, n), str) and getattr(obj, n).strip() for n in ('contract_id','underlying','revision','evidence_hash')):
            raise QuantError('INVALID_OPTION_CONTRACT', '合约身份、修订和单位证据不可为空')
        try:
            expiry = date.fromisoformat(obj.expiry)
            listed, last, cutoff = map(utc, (obj.listed_at,obj.last_trade_at,obj.exercise_cutoff_at))
        except (TypeError,ValueError) as exc:
            raise QuantError('INVALID_OPTION_CONTRACT', '日期和带时区的合约时间无效') from exc
        if listed >= last or last > cutoff or cutoff.date() > expiry:
            raise QuantError('INVALID_OPTION_CONTRACT', '合约挂牌、最后交易、行权截止和到期次序无效')
        if obj.settlement == 'PHYSICAL' and obj.deliverable_shares == 0:
            raise QuantError('INVALID_OPTION_CONTRACT', '实物交割必须明确证券交割物')
        if obj.settlement == 'CASH' and (obj.deliverable_shares or obj.deliverable_cash):
            raise QuantError('INVALID_OPTION_CONTRACT', '现金结算不能同时声明实物交割物')
        return obj

    def content(self):
        return {key: str(value) if isinstance(value,Decimal) else value for key,value in asdict(self).items()}

    @property
    def version_hash(self):
        return digest(self.content())

    def require_standard_vanilla(self):
        if self.exercise_cash != self.strike*self.quote_multiplier or (self.settlement == 'PHYSICAL' and
                (self.deliverable_shares != self.quote_multiplier or self.deliverable_cash != 0)):
            raise QuantError('UNSUPPORTED_DELIVERABLE', '调整合约/现金加证券交割物需独立核验，标准腿计算已阻断')


@dataclass(frozen=True)
class Leg:
    kind: str
    quantity: Decimal
    entry_price: Decimal
    strike: Decimal = Decimal('0')
    multiplier: Decimal = Decimal('1')
    expiry: str | None = None
    fee: Decimal = Decimal('0')

    @classmethod
    def from_dict(cls, body):
        try: obj = cls(**body)
        except TypeError as exc: raise QuantError('INVALID_OPTION_LEG','腿字段无效') from exc
        for name in ('quantity','entry_price','strike','multiplier','fee'):
            object.__setattr__(obj,name,decimal(getattr(obj,name)))
        if obj.kind not in {'STOCK','CALL','PUT'} or obj.quantity == 0 or obj.entry_price < 0 or obj.fee < 0 or obj.multiplier <= 0:
            raise QuantError('INVALID_OPTION_LEG','腿种类/数量/价格/乘数/费用无效')
        if obj.kind == 'STOCK':
            if obj.multiplier != 1 or obj.strike != 0 or obj.expiry is not None:
                raise QuantError('INVALID_OPTION_LEG','证券腿按实际股数计算，不带期权乘数/行权价/到期日')
        elif obj.strike <= 0 or not obj.expiry or obj.quantity != obj.quantity.to_integral_value():
            raise QuantError('INVALID_OPTION_LEG','期权腿需正行权价、到期日及整张数量')
        else:
            try: date.fromisoformat(obj.expiry)
            except (TypeError,ValueError) as exc: raise QuantError('INVALID_OPTION_LEG','到期日无效') from exc
        return obj

    def content(self):
        return {key: str(value) if isinstance(value,Decimal) else value for key,value in asdict(self).items()}
