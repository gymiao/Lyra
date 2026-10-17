"""QuantLib scenario prices only. Model outputs never substitute market quotes."""
from datetime import date
import math
from threading import RLock
from ..common import QuantError, finite_float

_LOCK = RLock()


def price(*, right, style, spot, strike, valuation_date, expiry, volatility, rate=0, dividend_yield=0,
          multiplier=100, contracts=1, market_price=None, discrete_dividends=None, include_greeks=True):
    if type(include_greeks) is not bool:raise QuantError('INVALID_PRICING_INPUT','include_greeks需布尔值')
    try:
        import QuantLib as q
    except ImportError as exc:
        raise QuantError('MISSING_OPTION_DEPENDENCY','理论分析需要安装已锁定的 options 依赖 QuantLib') from exc
    if right not in {'CALL','PUT'} or style not in {'EUROPEAN','AMERICAN'}:
        raise QuantError('INVALID_PRICING_INPUT','期权类型和行权方式无效')
    values = {k: finite_float(v) for k,v in {'spot':spot,'strike':strike,'volatility':volatility,'rate':rate,
              'dividend_yield':dividend_yield,'multiplier':multiplier,'contracts':contracts}.items()}
    if any(values[n] <= 0 for n in ('spot','strike','volatility','multiplier')) or values['contracts'] != int(values['contracts']):
        raise QuantError('INVALID_PRICING_INPUT','价格/波动率/乘数必须为正；张数需为整数')
    if not 0 < values['volatility'] <= 4 or not -1 < values['rate'] < 1 or not 0 <= values['dividend_yield'] < 1:
        raise QuantError('INVALID_PRICING_INPUT','模型波动率/利率/连续分红率超出允许范围')
    start,stop = date.fromisoformat(valuation_date),date.fromisoformat(expiry)
    if stop <= start:raise QuantError('INVALID_PRICING_INPUT','理论分析要求尚未到期；到期收益使用 payoff')
    dividends=[]
    if discrete_dividends is not None:
        if not isinstance(discrete_dividends,list):raise QuantError('INVALID_PRICING_INPUT','离散分红应为日期/每股金额列表')
        for item in discrete_dividends:
            if not isinstance(item,dict) or set(item)!={'ex_date','amount_per_share'}:
                raise QuantError('INVALID_PRICING_INPUT','分红需明确ex_date及amount_per_share')
            when=date.fromisoformat(item['ex_date']);amount=finite_float(item['amount_per_share'])
            if not start<when<=stop or amount<=0 or amount>=values['spot']:
                raise QuantError('INVALID_PRICING_INPUT','离散分红必须在估值后到期前、金额为合理正每股现金')
            dividends.append((when,amount))
        if dividends and values['dividend_yield']!=0:
            raise QuantError('DIVIDEND_DOUBLE_COUNT','同一模型不能同时计连续分红率与离散分红，避免重复计算')
        if len({when for when,_ in dividends})!=len(dividends):
            raise QuantError('INVALID_PRICING_INPUT','同日分红需先核对并合并凭据，不重复输入')
    def day(value):return q.Date(value.day,value.month,value.year)
    with _LOCK:
        settings=q.Settings.instance();previous=settings.evaluationDate
        try:
            settings.evaluationDate=day(start)
            dc=q.Actual365Fixed();calendar=q.NullCalendar()
            s=q.SimpleQuote(values['spot']);vol=q.SimpleQuote(values['volatility']);r=q.SimpleQuote(values['rate'])
            process=q.BlackScholesMertonProcess(q.QuoteHandle(s),
                q.YieldTermStructureHandle(q.FlatForward(day(start),values['dividend_yield'],dc)),
                q.YieldTermStructureHandle(q.FlatForward(day(start),q.QuoteHandle(r),dc)),
                q.BlackVolTermStructureHandle(q.BlackConstantVol(day(start),calendar,q.QuoteHandle(vol),dc)))
            exercise=q.AmericanExercise(day(start),day(stop)) if style=='AMERICAN' else q.EuropeanExercise(day(stop))
            option=q.VanillaOption(q.PlainVanillaPayoff(q.Option.Call if right=='CALL' else q.Option.Put,values['strike']),exercise)
            if dividends:
                schedule=q.DividendSchedule([q.FixedDividend(amount,day(when)) for when,amount in sorted(dividends)])
                engine=q.FdBlackScholesVanillaEngine(process,schedule,300,300)
            else:engine=q.FdBlackScholesVanillaEngine(process,300,300) if style=='AMERICAN' else q.AnalyticEuropeanEngine(process)
            option.setPricingEngine(engine)
            value=float(option.NPV());units=values['multiplier']*values['contracts']
            greeks={'delta':float(option.delta())*units,'gamma':float(option.gamma())*units,
                    'theta_per_calendar_day':float(option.theta())/365*units} if include_greeks else {}
            # QuantLib FD engines do not expose every analytic Greek. Sensitivities
            # reprice with the same mature engine and keep the bump explicit.
            for name,quote,bump in ([('vega_per_vol_point',vol,0.0001),('rho_per_rate_point',r,0.0001)] if include_greeks else []):
                original=quote.value()
                if quote is vol:bump=min(bump,original/2)
                try:
                    quote.setValue(original+bump);upper=option.NPV()
                    quote.setValue(original-bump);lower=option.NPV()
                    greeks[name]=float((upper-lower)/(2*bump)*.01*units)
                finally:quote.setValue(original)
            iv=None;iv_reason='未提供独立市场价格'
            if market_price is not None and dividends:
                target=finite_float(market_price)
                if target<0:raise QuantError('INVALID_PRICING_INPUT','市场价格不能为负')
                iv_reason='离散分红同模型IV求解尚未验证，不调用忽略现金分红的求解器'
            elif market_price is not None:
                target=finite_float(market_price)
                if target<0:raise QuantError('INVALID_PRICING_INPUT','市场价格不能为负')
                try:
                    iv=float(option.impliedVolatility(target,process,1e-7,200,1e-4,4))
                    iv_reason=None
                except RuntimeError as exc:iv_reason='隐含波动率无有效解：'+str(exc)
            if not math.isfinite(value) or any(not math.isfinite(v) for v in greeks.values()):
                raise QuantError('INVALID_MODEL_RESULT','模型结果非有限，不能发布')
            return {'data_type':'scenario_only','model':'QuantLib BSM discrete cash dividends' if dividends else 'QuantLib BSM continuous dividend yield',
                    'engine':'FdBlackScholesVanillaEngine' if style=='AMERICAN' or dividends else 'AnalyticEuropeanEngine',
                    'model_version':q.__version__,'unit_price':value,'position_value':value*units,'greeks':greeks,
                    'implied_volatility':iv,'iv_missing_reason':iv_reason,'inputs':{**values,'right':right,'style':style,
                        'valuation_date':valuation_date,'expiry':expiry,'market_price':market_price,'discrete_dividends':discrete_dividends},
                    'limitations':['日历日模型，分红为明确输入的模型假设；理论提前行权价值不能证明实际指派路径',
                        '理论价格不是可成交报价；Greeks为指定张数和乘数的金额敏感度，vega/rho对应1个百分点']}
        except RuntimeError as exc:
            raise QuantError('PRICING_FAILED','QuantLib计算失败：'+str(exc)) from exc
        finally:settings.evaluationDate=previous
