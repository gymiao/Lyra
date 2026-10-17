"""Integer research candidates using frozen A8 legs and existing account risk."""
from decimal import ROUND_FLOOR,ROUND_CEILING

from ..common import QuantError,decimal as D,digest,utc
from ..options.contracts import OptionContract
from .exposure import normalize_delta
from .sizing import instrument

LIMITS={'adverse_slippage_fraction','early_assignment_cash_reserve','max_greek_age_seconds',
        'max_mark_skew_seconds','proxy_exit_policy','failed_exit_policy'}
GROUP_FIELDS={'parent_id','actual_put_shares','actual_call_shares','pending_put_shares','pending_call_shares','valid_until'}


def option_candidate(exposure,spec,method,selection,groups,greeks,limits,*,funding_quote=None):
    policy=spec.content();state=exposure['account'];risk=exposure['risk']
    if (not isinstance(limits,dict) or set(limits)!=LIMITS or not isinstance(groups,list)
            or not isinstance(greeks,list) or any(D(limits[k])<0 for k in
                ('adverse_slippage_fraction','early_assignment_cash_reserve','max_greek_age_seconds','max_mark_skew_seconds'))
            or D(limits['adverse_slippage_fraction'])>=1):
        raise QuantError('INVALID_HEDGE_OPTION_LIMITS','期权候选需完整显式成交/时效/退出参数')
    result={'method':method,'exposure_id':exposure['exposure_id'],'spec_hash':spec.spec_hash,
        'selection':selection,'status':'NO_FEASIBLE_HEDGE','checks':[],'trades':[],
        'candidate_inputs':{'greeks':greeks,'limits':limits,'protection_groups':groups,'funding_quote':funding_quote},
        'executable':False,'data_type':'frozen_reference_research',
        'meaning':'条件数量研究；到期股数保护与局部Delta分开，不保证代理到期底线或成交'}
    def blocked(code):result['checks'].append(code);return result
    if method not in policy['tools']:return blocked('TOOL_NOT_ALLOWED')
    if method not in {'protective_put','collar','proxy_put'}:return blocked('UNSUPPORTED_HEDGE_OPTION')
    if selection['status']!='SELECTED_FOR_RESEARCH':return blocked('NO_ELIGIBLE_CONTRACT')
    template='collar' if method=='collar' else 'protective_put'
    if selection['template_id']!=template:return blocked('HEDGE_TEMPLATE_MISMATCH')
    if state['equity'] is None or D(state['equity'])<=0:return blocked('COMPLETE_ACCOUNT_EQUITY_REQUIRED')
    if state.get('anomalies'):return blocked('ACCOUNT_RECONCILIATION_REQUIRED')
    if method=='proxy_put' and (limits['proxy_exit_policy']!='sell_before_expiry'
            or limits['failed_exit_policy']!='block_and_require_verified_resolution'):
        return blocked('PROXY_EXIT_FAILURE_POLICY_REQUIRED')
    contracts=[];buy=D(0);net=D(0);marks=D(0);notional=D(0);spot=None
    for leg in selection['legs']:
        c=OptionContract.from_dict(leg['contract']);c.require_standard_vanilla();contracts.append(c)
        quote=leg['reference_quote'];sign=D(leg['quantity_per_package']);price=D(leg['reference_price'])
        execution=price*(1+D(limits['adverse_slippage_fraction'])*sign)
        if execution<=0:return blocked('NONPOSITIVE_EXECUTION_PRICE')
        current_spot=D(quote['underlying_price'])
        if spot is None:spot=current_spot
        if current_spot!=spot:return blocked('OPTION_UNDERLYING_PRICE_MISMATCH')
        net+=sign*execution*c.quote_multiplier
        if sign>0:buy+=execution*c.quote_multiplier
        marks+=sign*(D(quote['bid'])+D(quote['ask']))/2*c.quote_multiplier
        notional+=current_spot*c.quote_multiplier
    underlying=selection['underlying'];unit=contracts[0].deliverable_shares
    if (any(c.underlying!=underlying or c.deliverable_shares!=unit for c in contracts)
            or len(contracts)!=(2 if method=='collar' else 1) or len({c.expiry for c in contracts})!=1
            or [(c.right,D(leg['quantity_per_package'])) for leg,c in zip(selection['legs'],contracts)]!=
                ([('PUT',D(1)),('CALL',D(-1))] if method=='collar' else [('PUT',D(1))])):
        return blocked('OPTION_UNIT_CONFLICT')
    horizon=min(utc(c.exercise_cutoff_at) for c in contracts)
    # Existing protection must span the requested window, rather than adding
    # protections with different expiry dates as if they were continuous.
    from datetime import timedelta
    horizon-=timedelta(days=policy['exit_days_before_expiry'])
    actual=D(0);pending=D(0);used_shares=D(0);seen=set()
    for group in groups:
        if (not isinstance(group,dict) or set(group)!=GROUP_FIELDS or not isinstance(group['parent_id'],str)
                or not group['parent_id'] or group['parent_id'] in seen):
            raise QuantError('INVALID_PROTECTION_GROUP','保护分配分组身份或字段无效')
        seen.add(group['parent_id']);ap,ac,pp,pc=(D(group[k]) for k in
            ('actual_put_shares','actual_call_shares','pending_put_shares','pending_call_shares'))
        if min(ap,ac,pp,pc)<0:raise QuantError('INVALID_PROTECTION_GROUP','保护股数不能为负')
        if max(ap,ac,pp,pc)>0 and utc(group['valid_until'])<horizon:return blocked('PROTECTION_HORIZON_REVIEW_REQUIRED')
        used_shares+=max(ap+pp,ac+pc)
        if method=='collar':
            if ap+pp!=ac+pc:return blocked('UNPAIRED_COLLAR_LEGS_REQUIRE_RECOVERY')
            actual+=min(ap,ac)/unit;pending+=(min(ap+pp,ac+pc)-min(ap,ac))/unit
        else:actual+=ap/unit;pending+=pp/unit
    if actual!=actual.to_integral_value() or pending!=pending.to_integral_value():
        return blocked('PROTECTION_UNIT_REVIEW_REQUIRED')
    held=D(state['positions'].get(underlying,0));fees_per_package=D(policy['option_fee_per_contract'])*len(contracts)
    if method!='proxy_put' and underlying not in policy['scope']:return blocked('DIRECT_PROTECTION_SCOPE_REQUIRED')
    if method!='proxy_put' and used_shares>held:return blocked('PROTECTION_EXCEEDS_ACTUAL_SHARES')
    result.update(actual_existing_packages=str(actual),pending_existing_packages=str(pending),
                  protection_horizon=horizon.isoformat(),estimated_fee_per_package=str(fees_per_package))
    B=D(risk['beta_amount']) if risk['beta_amount'] is not None else None;E=D(state['equity'])
    delta_amount=None
    if policy['mode']=='share_protection':
        if method=='proxy_put' or underlying not in policy['scope']:return blocked('DIRECT_PROTECTION_SCOPE_REQUIRED')
        target=(held*D(policy['protection_fraction'])/unit).to_integral_value(rounding=ROUND_FLOOR)
        desired=max(D(0),target-actual-pending)
        result.update(target_total_packages=str(target),uncovered_fractional_shares=str(held*D(policy['protection_fraction'])-target*unit))
        if desired==0:
            result.update(status='WAITING_FOR_FILL' if pending else 'KEEP',incremental_packages='0',trades=[])
            return result
    else:
        if B is None or exposure['beta_model']['benchmark']!=policy['benchmark']:return blocked('COMPLETE_ACCOUNT_BETA_REQUIRED')
        estimate=exposure['beta_model']['estimates'].get(underlying)
        if not estimate or estimate['status']!='CHECKED' or abs(D(estimate['beta']))<D(policy['min_abs_proxy_beta']):
            return blocked('PROXY_BETA_REQUIRED')
        raw=exposure['valuation']['prices'].get(underlying)
        if raw is None or D(raw)!=spot:return blocked('FROZEN_PROXY_PRICE_MISMATCH')
        by_version={g.get('contract_version'):g for g in greeks if isinstance(g,dict)}
        if len(by_version)!=len(greeks):raise QuantError('INVALID_HEDGE_GREEK','重复或畸形候选Greek')
        total=D(0)
        for leg,c in zip(selection['legs'],contracts):
            item=by_version.get(c.version_hash)
            if item is None:return blocked('MODEL_INPUT_REQUIRED')
            try:
                normalized=normalize_delta(item,c,leg['quantity_per_package'],exposure['as_of'],
                    exposure['knowledge_cutoff'],limits['max_greek_age_seconds'])
                if item.get('data_type')=='model':
                    from .model_greek import require_mark
                    require_mark(item,spot)
                if abs((utc(item['as_of'])-utc(leg['reference_quote']['exchange_timestamp'])).total_seconds())>float(limits['max_mark_skew_seconds']):
                    return blocked('HEDGE_GREEK_TIME_MISMATCH')
            except QuantError as exc:return blocked(exc.code)
            total+=D(normalized['delta_shares'])
        delta_amount=total*spot*D(estimate['beta'])
        if delta_amount>=0:return blocked('OPTION_DOES_NOT_REDUCE_BETA')
        if pending:
            result.update(status='WAITING_FOR_FILL',incremental_packages='0',checks=['INFLIGHT_HEDGE_REVIEW_REQUIRED'])
            return result
        desired=None
    funding=None
    if funding_quote is not None:
        funding=instrument(funding_quote)
        if policy['funding']!='sell_scope' or funding['symbol']!=policy['funding_symbol']:
            return blocked('FUNDING_SCOPE_MISMATCH')
        estimate=exposure['beta_model']['estimates'].get(funding['symbol']);mark=exposure['valuation']['prices'].get(funding['symbol'])
        if mark is None or D(mark)!=D(funding['market_price']):return blocked('FROZEN_FUNDING_PRICE_MISMATCH')
        if policy['mode']=='beta_target' and (not estimate or estimate['status']!='CHECKED' or abs(D(estimate['beta'])-D(funding['beta']))>D('0.00000001')):
            return blocked('FROZEN_FUNDING_BETA_MISMATCH')
        if method!='proxy_put' and funding['symbol']==underlying:return blocked('CANNOT_SELL_PROTECTED_SHARES_TO_FUND')
    choices=[];reasons=set();available=D(state['available_cash']);usable=min(available,D(policy['max_cash']))
    for q in range(max(0,policy['max_contracts']-int(actual+pending))+1):
        quantity=D(q)
        if desired is not None and quantity>desired:continue
        if method!='proxy_put' and quantity*unit>max(D(0),held-max(used_shares,D(state['reserved_positions'].get(underlying,0)))):
            reasons.add('INSUFFICIENT_UNALLOCATED_SHARES');continue
        if any(quantity>D(leg['reference_quote']['ask_size'] if leg['quantity_per_package']>0 else leg['reference_quote']['bid_size']) for leg in selection['legs']):
            reasons.add('INSUFFICIENT_QUOTED_SIZE');continue
        fee=quantity*fees_per_package;need=quantity*buy+fee+(D(limits['early_assignment_cash_reserve']) if q else D(0))
        sold=D(0);sell_fee=D(0);proceeds=D(0);sell_value=D(0)
        if need>usable:
            if funding is None:reasons.add('INSUFFICIENT_SETTLED_CASH');continue
            sale_price=D(funding['execution_price']);rate=D(policy['commission_bps'])/10000;fixed=D(policy['fixed_trade_fee'])
            sold=((need-usable+fixed)/(sale_price*(1-rate)*D(funding['trade_unit']))).to_integral_value(rounding=ROUND_CEILING)*D(funding['trade_unit'])
            if sold/D(funding['trade_unit'])>policy['max_trade_units']:
                reasons.add('FUNDING_TRADE_UNIT_LIMIT');continue
            if sold>D(state['positions'].get(funding['symbol'],0))-D(state['reserved_positions'].get(funding['symbol'],0)):
                reasons.add('INSUFFICIENT_FUNDING_SHARES');continue
            sell_value=sold*sale_price;sell_fee=sell_value*rate+fixed;proceeds=sell_value-sell_fee
        if quantity*buy+fee>D(policy['max_premium']):reasons.add('PREMIUM_LIMIT');continue
        if quantity*notional+sell_value>D(policy['max_notional']):reasons.add('NOTIONAL_LIMIT');continue
        after=available+proceeds-quantity*net-fee
        Epost=E+quantity*(marks-net)-fee-sell_fee+(sold*(D(funding['execution_price'])-D(funding['market_price'])) if sold else D(0))
        if after<0 or Epost<=0:reasons.add('INSUFFICIENT_SETTLED_CASH');continue
        Bpost=None if delta_amount is None else B+quantity*delta_amount-(sold*D(funding['market_price'])*D(funding['beta']) if sold else D(0))
        beta=None if Bpost is None else Bpost/Epost
        error=abs(desired-quantity) if desired is not None else abs(beta-D(policy['target_beta']))
        if desired is None and (error>D(policy['residual_beta_tolerance']) or beta<D(policy['target_beta'])-D(policy['max_overhedge_fraction'])):
            reasons.add('BETA_TOLERANCE');continue
        choices.append((error,fee+sell_fee,quantity*notional+sell_value,q,sold,after,Epost,Bpost,beta))
    if not choices:return blocked(','.join(sorted(reasons)) or 'NO_FEASIBLE_INTEGER_QUANTITY')
    _,cost,_,q,sold,after,Epost,Bpost,beta=min(choices,key=lambda x:x[:4])
    if desired is not None and q==0:return blocked(','.join(sorted(reasons)) or 'NO_AFFORDABLE_PROTECTION')
    trades=[]
    if sold:trades.append({'kind':'stock','symbol':funding['symbol'],'side':'SELL','quantity':str(sold)})
    for leg,c in zip(selection['legs'],contracts):
        if q:trades.append({'kind':'option','contract_id':c.contract_id,'contract_version':c.version_hash,
            'side':'BUY' if leg['quantity_per_package']>0 else 'SELL','contracts':q})
    result.update(status='SELECTED_FOR_RESEARCH' if q else 'KEEP',incremental_packages=str(q),
        planned_total_packages=str(actual+pending+q),trades=trades,estimated_fees=str(cost),estimated_cost=str(E-Epost),
        E_post=str(Epost),B_post=str(Bpost) if Bpost is not None else None,beta_post=str(beta) if beta is not None else None,
        available_cash_after_all_settlements=str(after),funding_requires_settlement=bool(sold),
        dependencies=['SELL_FILL_CONFIRMED','SELL_SETTLEMENT_CONFIRMED','REPRICE_AND_RECHECK_BEFORE_BUY'] if sold else [],
        remaining_target_packages=str(max(D(0),desired-D(q))) if desired is not None else None)
    result['candidate_id']=digest(result);return result
