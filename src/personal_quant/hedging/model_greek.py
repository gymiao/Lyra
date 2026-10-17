"""Reproduce Delta from explicit, time-qualified QuantLib inputs."""
import hashlib
from pathlib import Path
from zoneinfo import ZoneInfo

from ..common import QuantError, decimal as D, utc
from ..options import pricing


MODEL_FIELDS={'pricing','model','engine','model_version','pricing_source_hash','input_observations'}
PRICING_FIELDS={'right','style','spot','strike','valuation_date','expiry','volatility','rate',
                'dividend_yield','multiplier','contracts','market_price','discrete_dividends'}
INPUT_NAMES={'spot','volatility','rate','dividend_yield','discrete_dividends'}
OBSERVATION_FIELDS={'value','source','as_of','available_at','received_at','max_age_seconds','data_type','raw_file'}


def require_mark(item,spot,*,require_complete=False):
    """A qualified model cannot apply Delta estimated at a different stock price."""
    if item.get('data_type')!='model':return
    model=item.get('model_inputs')
    args=model.get('pricing') if isinstance(model,dict) else None
    if not isinstance(args,dict):
        if require_complete:raise QuantError('MODEL_INPUT_REQUIRED','实际模型Delta需完整定价输入')
        return
    if spot is None or args.get('spot') is None or D(args['spot'])!=D(spot):
        raise QuantError('MODEL_GREEK_PRICE_MISMATCH','模型Delta的标的原价与本次冻结估值不同')


def validate(item,contract,*,evidence_type,evidence_files):
    """Input acquisition must precede the generated observation, never a default."""
    def invalid():
        raise QuantError('INVALID_MODEL_GREEK_INPUT','模型Delta需完整可用输入、确切标准合约和已锁模型/源码')
    try:
        model=item['model_inputs'];clock=utc(item['as_of'])
        available,received=utc(item['available_at']),utc(item['received_at'])
        if not isinstance(model,dict) or set(model)!=MODEL_FIELDS:invalid()
        args=model['pricing'];observations=model['input_observations']
        if (item['data_type']!='model' or item['unit']!='position_total'
                or not isinstance(args,dict) or set(args)!=PRICING_FIELDS
                or not isinstance(observations,dict) or set(observations)!=INPUT_NAMES
                or not isinstance(evidence_files,dict) or 'model-inputs.json' not in evidence_files):invalid()
        contract.require_standard_vanilla()
        quantity=D(item['signed_contracts'])
        if (quantity==0 or quantity!=quantity.to_integral_value()
                or D(args['contracts'])!=quantity or D(args['multiplier'])!=contract.quote_multiplier
                or D(args['strike'])!=contract.strike or args['right']!=contract.right
                or args['style']!=contract.style or args['expiry']!=contract.expiry
                or args['valuation_date']!=str(clock.astimezone(ZoneInfo(contract.market_timezone)).date())
                or not utc(contract.listed_at)<=clock<utc(contract.last_trade_at)
                or args['market_price'] is not None
                or model['pricing_source_hash']!=hashlib.sha256(Path(pricing.__file__).read_bytes()).hexdigest()):invalid()
        for name,observation in observations.items():
            if (not isinstance(observation,dict) or set(observation)!=OBSERVATION_FIELDS
                    or not isinstance(observation['source'],str) or not observation['source'].strip()
                    or observation['data_type'] not in {'real_market','synthetic'}
                    or (evidence_type=='actual' and observation['data_type']!='real_market')
                    or not isinstance(observation['raw_file'],str)
                    or observation['raw_file'] not in evidence_files
                    or observation['raw_file'] in {'observation.json','model-inputs.json'}):invalid()
            if name=='discrete_dividends':
                if observation['value']!=args[name]:invalid()
            elif D(observation['value'])!=D(args[name]):invalid()
            observed=utc(observation['as_of']);published=utc(observation['available_at']);acquired=utc(observation['received_at'])
            max_age=D(observation['max_age_seconds'])
            if (max_age<0 or observed>clock or published<observed or acquired<published
                    or published>available or acquired>received
                    or D(str((clock-observed).total_seconds()))>max_age):invalid()
        result=pricing.price(**args)
        if any(model[name]!=result[name] for name in ('model','engine','model_version')):invalid()
        expected=D(str(result['greeks']['delta']))
        tolerance=D('0.00000001')*max(D(1),abs(expected))
        if abs(D(item['value'])-expected)>tolerance:
            raise QuantError('MODEL_GREEK_MISMATCH','归档Delta不能由确切输入和已锁模型复现')
        return result
    except QuantError:
        raise
    except (KeyError,TypeError,ValueError,OverflowError,OSError) as exc:
        raise QuantError('INVALID_MODEL_GREEK_INPUT','模型输入、时点或源码依据无法校验') from exc
