"""Deterministic quantity previews with post-funding equity and exposure."""
from decimal import ROUND_CEILING,ROUND_FLOOR
from ..common import QuantError,decimal as D,digest

INSTRUMENT_FIELDS={'symbol','execution_price','market_price','beta','trade_unit','product_type','product_evidence'}


def instrument(body):
    if (not isinstance(body,dict) or set(body)!=INSTRUMENT_FIELDS or not isinstance(body['symbol'],str) or not body['symbol']
            or D(body['execution_price'])<=0 or D(body['market_price'])<=0 or D(body['trade_unit'])<=0
            or body['product_type'] not in {'stock','etf','inverse_etf'}
            or not isinstance(body['product_evidence'],str) or not body['product_evidence']):
        raise QuantError('INVALID_HEDGE_INSTRUMENT','候选需明确证券、成交参考/估值价、Beta、交易单位及产品说明')
    D(body['beta']);return body


def stock_candidate(exposure,spec,method,proxy,*,funding_quote=None):
    if not isinstance(method,str):raise QuantError('INVALID_HEDGE_METHOD','候选方法须是明确名称')
    policy=spec.content();proxy=instrument(proxy);state=exposure['account'];risk=exposure['risk'];checks=[]
    result={'method':method,'symbol':proxy['symbol'],'exposure_id':exposure['exposure_id'],'spec_hash':spec.spec_hash,
        'status':'NO_FEASIBLE_HEDGE','checks':checks,'trades':[],'executable':False,
        'data_type':'frozen_reference_research','product_declaration':proxy,
        'meaning':'完整成交后的条件估计；不预支未结算卖款，不产生订单，不假定反向ETF恒定Beta'}
    def blocked(code):checks.append(code);return result
    if method not in policy['tools']:return blocked('TOOL_NOT_ALLOWED')
    if method not in {'reduce_stock','inverse_etf'}:return blocked('OPTION_CANDIDATE_PENDING')
    if policy['mode']!='beta_target':return blocked('BETA_TARGET_REQUIRED')
    if risk['beta_amount'] is None or state['equity'] is None or D(state['equity'])<=0:return blocked('COMPLETE_ACCOUNT_BETA_REQUIRED')
    if exposure['beta_model']['benchmark']!=policy['benchmark']:return blocked('BENCHMARK_MISMATCH')
    if abs(D(proxy['beta']))<D(policy['min_abs_proxy_beta']) or D(proxy['beta'])==0:return blocked('PROXY_BETA_TOO_SMALL')
    for quote in [proxy]+([funding_quote] if funding_quote is not None else []):
        quote=instrument(quote);estimate=exposure['beta_model']['estimates'].get(quote['symbol'])
        price=exposure['valuation']['prices'].get(quote['symbol'])
        if (not estimate or estimate['status']!='CHECKED' or price is None):return blocked('FROZEN_PROXY_MODEL_REQUIRED')
        if abs(D(quote['beta'])-D(estimate['beta']))>D('0.00000001') or D(quote['market_price'])!=D(price):
            return blocked('FROZEN_PROXY_BASIS_MISMATCH')
    if method=='reduce_stock' and proxy['symbol'] not in policy['scope']:return blocked('OUTSIDE_ADJUSTMENT_SCOPE')
    if method=='inverse_etf' and (proxy['product_type']!='inverse_etf' or D(proxy['beta'])>=0):return blocked('INVERSE_PRODUCT_OR_BETA_REQUIRED')
    E,B=D(state['equity']),D(risk['beta_amount']);target=D(policy['target_beta'])
    available=D(state['available_cash']);usable_cash=min(available,D(policy['max_cash']))
    unit=D(proxy['trade_unit']);mark=D(proxy['market_price'])
    ideal=(target*E-B)/(mark*D(proxy['beta']));result['ideal_incremental_quantity']=str(ideal)
    held=D(state['positions'].get(proxy['symbol'],0));reserved=D(state.get('reserved_positions',{}).get(proxy['symbol'],0))
    if method=='reduce_stock' and ideal<0 and -ideal>max(D(0),held-reserved):
        result['unreachable_without_short_quantity']=str(max(D(0),-ideal-max(D(0),held-reserved)))
    if held and D(state['prices'].get(proxy['symbol'],0))!=mark:return blocked('MARK_BASIS_MISMATCH')
    funding=None
    if policy['funding']=='sell_scope':
        if funding_quote is None:return blocked('FUNDING_QUOTE_REQUIRED')
        funding=instrument(funding_quote)
        if funding['symbol']!=policy['funding_symbol'] or funding['symbol']==proxy['symbol']:return blocked('INVALID_FUNDING_SCOPE')
        if D(state['prices'].get(funding['symbol'],0))!=D(funding['market_price']):return blocked('MARK_BASIS_MISMATCH')
    fee=lambda q,p:abs(q)*p*D(policy['commission_bps'])/10000+(D(policy['fixed_trade_fee']) if q else D(0))
    best=None;failed=set()
    for number in range(policy['max_trade_units']+1):
        q=unit*number*(-1 if method=='reduce_stock' else 1)
        if q<0 and -q>max(D(0),held-reserved):failed.add('UNSUPPORTED_SHORT_OR_RESERVED_SHARES');continue
        price=D(proxy['execution_price']);cost=q*price+fee(q,price)
        trades=[];cash_needed=max(D(0),cost);fund_q=D(0)
        if q:trades.append({'symbol':proxy['symbol'],'quantity':str(q),'execution_price':str(price),
            'market_price':str(mark),'fee':str(fee(q,price)),'beta':str(proxy['beta']),'role':'hedge'})
        if cash_needed>usable_cash:
            if funding is None:
                failed.add('INSUFFICIENT_AVAILABLE_CASH' if cash_needed>available else 'CASH_BUDGET_EXCEEDED');continue
            fp,fu=D(funding['execution_price']),D(funding['trade_unit'])
            proceeds_unit=fu*fp*(1-D(policy['commission_bps'])/10000)
            units=((cash_needed-usable_cash+D(policy['fixed_trade_fee']))/proceeds_unit).to_integral_value(rounding=ROUND_CEILING)
            fund_q=-units*fu
            free=D(state['positions'].get(funding['symbol'],0))-D(state.get('reserved_positions',{}).get(funding['symbol'],0))
            if -fund_q>free:failed.add('INSUFFICIENT_FUNDING_SHARES');continue
            if units>policy['max_trade_units']:failed.add('FUNDING_UNIT_LIMIT');continue
            trades.insert(0,{'symbol':funding['symbol'],'quantity':str(fund_q),'execution_price':str(fp),
                'market_price':str(funding['market_price']),'fee':str(fee(fund_q,fp)),'beta':str(funding['beta']),'role':'funding'})
        notional=sum(abs(D(t['quantity']))*D(t['market_price']) for t in trades)
        cash_after=available-sum(D(t['quantity'])*D(t['execution_price'])+D(t['fee']) for t in trades)
        cash_used=max(D(0),available-cash_after)
        if cash_after<0 or cash_used>D(policy['max_cash']):failed.add('CASH_BUDGET_EXCEEDED');continue
        if notional>D(policy['max_notional']):failed.add('NOTIONAL_LIMIT');continue
        E_post=E+sum(D(t['quantity'])*(D(t['market_price'])-D(t['execution_price']))-D(t['fee']) for t in trades)
        B_post=B+sum(D(t['quantity'])*D(t['market_price'])*D(t['beta']) for t in trades)
        if E_post<=0:failed.add('NONPOSITIVE_POST_EQUITY');continue
        beta_post=B_post/E_post;error=abs(beta_post-target)
        if beta_post<target-D(policy['max_overhedge_fraction']):failed.add('OVERHEDGE_LIMIT');continue
        if error>D(policy['residual_beta_tolerance']):failed.add('TARGET_NOT_REACHABLE_WITHIN_TOLERANCE');continue
        total_fee=sum(D(t['fee']) for t in trades)
        ranking=(error,total_fee,notional,number)
        if best is None or ranking<best[0]:
            best=(ranking,{'trades':trades,'B_post':str(B_post),'E_post':str(E_post),'beta_post':str(beta_post),
                'residual_beta_error':str(error),'fees':str(total_fee),'gross_trade_notional':str(notional),
                'available_cash_after_all_settlements':str(cash_after),'incremental_quantity':str(q),
                'target_position':str(held+q),'requires_sell_settlement':fund_q!=0 or q<0})
    if best:
        result.update(best[1],status='KEEP' if not best[1]['trades'] else 'SELECTED_FOR_RESEARCH')
        if result['requires_sell_settlement']:result['dependencies']=['SELL_FILL_CONFIRMED','SELL_SETTLEMENT_CONFIRMED','REPRICE_AND_RECHECK_BEFORE_BUY']
    else:
        checks.extend(sorted(failed))
        if method=='reduce_stock' and result.get('unreachable_without_short_quantity'):checks.append('UNSUPPORTED_SHORT')
    result['candidate_id']=digest(result);return result
