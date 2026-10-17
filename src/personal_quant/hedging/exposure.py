"""Common-date OLS and explicitly normalized Greeks; no trade decisions."""
import numpy as np
import pandas as pd
from ..common import QuantError,decimal as D,digest,utc


def estimate_betas(frame,calendar,symbols,benchmark,as_of,knowledge_cutoff,*,window,min_r2,max_standard_error,execution_replay=False):
    if type(window) is not int or window<3 or not 0<=D(min_r2)<=1 or D(max_standard_error)<0:
        raise QuantError('INVALID_EXPOSURE_PARAMETERS','Beta需至少3个收益、明确R²/标准误质量阈值')
    clock,known=utc(as_of),utc(knowledge_cutoff)
    if type(execution_replay) is not bool or (known>clock and not execution_replay):raise QuantError('INVALID_EXPOSURE_TIME','普通风险知识截止不能晚于风险时点')
    required=sorted(set(symbols)|{benchmark});completed=[d for d in calendar.sessions if calendar.close(d).to_pydatetime()<=min(clock,known)]
    dates=pd.DatetimeIndex(completed[-(window+1):]);checks=[]
    result={'status':'INCOMPLETE','method':'simple_total_return_OLS_with_intercept/1.0.0',
            'benchmark':benchmark,'window':window,'required_prices':window+1,'observations':0,
            'dates':[str(d.date()) for d in dates],'estimates':{},'checks':checks,
            'meaning':'当前持仓的历史风险估计，不是历史实际账户收益；标准误采用样本内同方差OLS假设'}
    if len(dates)<window+1:checks.append('INSUFFICIENT_COMMON_PRICES');return result
    available=frame.loc[(frame.available_at<=pd.Timestamp(known)) & frame.session_date.isin(dates) & frame.symbol.isin(required)]
    if available.duplicated(['symbol','session_date']).any():
        checks.append('DUPLICATE_RISK_PRICE');return result
    prices=available.pivot(index='session_date',columns='symbol',values='adj_close').reindex(index=dates,columns=required)
    if prices.isna().any().any() or not np.isfinite(prices.to_numpy()).all() or (prices<=0).any().any():
        checks.append('INCOMPLETE_COMMON_PRICES');return result
    if (available.volume<=0).any():checks.append('NONTRADABLE_RISK_PRICE');return result
    returns=prices.pct_change(fill_method=None).iloc[1:];x=returns[benchmark].to_numpy();center=x-x.mean();sxx=float(center@center)
    result['observations']=len(x);result['input_hash']=digest(available.sort_values(['session_date','symbol']).to_json(orient='records',date_format='iso'))
    result['return_dates']=[str(d.date()) for d in returns.index]
    if sxx<=np.finfo(float).eps*max(1,float(x@x)):
        checks.append('ZERO_BENCHMARK_VARIANCE');return result
    for symbol in sorted(set(symbols)):
        y=returns[symbol].to_numpy();beta=float(center@(y-y.mean())/sxx);intercept=float(y.mean()-beta*x.mean())
        residual=y-intercept-beta*x;sse=float(residual@residual);syy=float((y-y.mean())@(y-y.mean()))
        se=float(np.sqrt(max(0,sse)/(len(x)-2)/sxx));r2=float(np.clip(1-sse/syy,0,1)) if syy>0 else None
        corr=float(np.corrcoef(x,y)[0,1]) if syy>0 else None
        issues=[]
        if r2 is None or r2<float(min_r2):issues.append('BETA_R2_BELOW_LIMIT')
        if se>float(max_standard_error):issues.append('BETA_STANDARD_ERROR_ABOVE_LIMIT')
        result['estimates'][symbol]={'beta':beta,'intercept':intercept,'r_squared':r2,
            'correlation':corr,'standard_error':se,'observations':len(x),
            'status':'BLOCKED' if issues else 'CHECKED','checks':issues}
        checks.extend(code+':'+symbol for code in issues)
    result['status']='INCOMPLETE' if checks else 'COMPLETE';return result


def normalize_delta(item,contract,quantity,as_of,knowledge_cutoff,max_skew_seconds):
    fields={'contract_version','unit','value','signed_contracts','source','data_type','as_of','available_at','received_at','model_inputs'}
    if (not isinstance(item,dict) or set(item) not in (fields,fields|{'qualification_id'}) or item['contract_version']!=contract.version_hash
            or item['unit'] not in {'per_share','per_contract','position_total'}
            or D(item['signed_contracts'])!=D(quantity) or not isinstance(item['source'],str) or not item['source']
            or item['data_type'] not in {'provider','model','synthetic'}):
        raise QuantError('INVALID_HEDGE_GREEK','Greek需确切合约/有符号张数、单位、来源及时点')
    clock,known=utc(as_of),utc(knowledge_cutoff);mark=utc(item['as_of'])
    if (mark>min(clock,known) or utc(item['available_at'])>known or utc(item['received_at'])>known
            or utc(item['available_at'])<mark or utc(item['received_at'])<utc(item['available_at'])
            or (clock-mark).total_seconds()>float(max_skew_seconds)):
        raise QuantError('HEDGE_GREEK_TIME_MISMATCH','Greek未来、尚未收到或与组合估值时间偏差过大')
    if item['data_type']=='model' and (not isinstance(item['model_inputs'],dict) or not item['model_inputs']):
        raise QuantError('MODEL_INPUT_REQUIRED','理论Greek必须保留显式模型输入；不填入默认IV或股息')
    value=D(item['value']);q=D(quantity)
    if item['unit']=='per_share':total=value*contract.quote_multiplier*q
    elif item['unit']=='per_contract':total=value*q
    else:total=value
    long_delta=total/q if q else D(0)
    if (contract.right=='PUT' and long_delta>0) or (contract.right=='CALL' and long_delta<0):
        raise QuantError('INVALID_HEDGE_GREEK','香草每多头合约Delta符号与Call/Put类型不符')
    # Normalization must not multiply an already aggregated QuantLib result again.
    if abs(total)>abs(q)*contract.quote_multiplier:
        raise QuantError('INVALID_HEDGE_GREEK','香草Delta超过整份持仓的单位范围')
    return {'delta_shares':str(total),'unit':'position_total','input':item,
            'meaning':'有符号Delta股数；不等同于到期可交割/已保护股数'}


def aggregate_exposure(state,betas,option_deltas,underlying_prices):
    stock=[];options=[];checks=[];gross=D(0);known_gross=D(0);net=D(0);B=D(0);marked=0
    for symbol,quantity in state['positions'].items():
        price=state.get('prices',{}).get(symbol);estimate=betas.get(symbol)
        if price is None:checks.append('MISSING_STOCK_MARK:'+symbol);continue
        marked+=1;value=D(quantity)*D(price);gross+=abs(value);net+=value
        if not estimate or estimate['status']!='CHECKED':checks.append('STOCK_BETA_REQUIRED:'+symbol);continue
        amount=value*D(estimate['beta']);B+=amount;known_gross+=abs(value)
        stock.append({'symbol':symbol,'shares':quantity,'market_value':str(value),'beta':estimate['beta'],'beta_amount':str(amount)})
    for symbol,quantity in state.get('option_positions',{}).items():
        item=option_deltas.get(symbol)
        if not item:checks.append('OPTION_DELTA_REQUIRED:'+symbol);continue
        underlying=item['underlying'];estimate=betas.get(underlying);spot=underlying_prices.get(underlying)
        if not estimate or estimate['status']!='CHECKED' or spot is None:
            checks.append('OPTION_UNDERLYING_RISK_REQUIRED:'+symbol);continue
        amount=D(item['delta_shares'])*D(spot)*D(estimate['beta']);B+=amount
        options.append({'contract_id':symbol,'contracts':quantity,'underlying':underlying,
            'delta_shares':item['delta_shares'],'beta_amount':str(amount),'greek':item})
    equity=state.get('equity');complete=not checks and equity is not None
    if equity is None:checks.append('INCOMPLETE_ACCOUNT_EQUITY')
    if equity is not None and D(equity)<=0:checks.append('NONPOSITIVE_ACCOUNT_EQUITY')
    return {'status':'COMPLETE' if complete and not checks else 'INCOMPLETE','stock_positions':stock,'option_positions':options,
        'known_beta_amount':str(B),'beta_amount':str(B) if complete else None,
        'account_beta':str(B/D(equity)) if complete and D(equity)>0 else None,
        'stock_gross_market_value':str(gross),'stock_net_market_value':str(net),
        'stock_model_coverage':str(known_gross/gross) if gross else None,
        'stock_valuation_count_coverage':{'marked':marked,'total':len(state['positions']),
            'meaning':'按持仓证券数统计；缺价时无法声称完整市值覆盖率'},
        'checks':checks,'cash_beta_assumption':0,
        'meaning':'市场Beta金额与权益比例；缺项不作零，局部Delta不保证到期保护或最大损失'}
