from .catalog import FUNDED_CALL_PROTECTION
"""Reviewable option drafts; execution remains gated until lifecycle validation."""
import json
from ..common import QuantError, decimal as D, digest, canonical, now_utc
from ..locks import publication_lock
from .contracts import OptionContract
from .selection import select
from .payoff import analyze

RISK_FIELDS={'premium_budget','maximum_loss_budget','maximum_notional','maximum_contracts',
             'fee_per_contract','adverse_slippage_fraction','cash_buffer','early_assignment_cash_reserve'}


def unfilled_resources(body,filled):
    """Budget the unfilled part; actual collateral is accounted for by the ledger.

    This calculation grants no execution permission. It is shared by forthcoming
    activation checks and partial-fill transitions, rather than spending premium
    from a sale that has not happened.
    """
    selection=body['selection'];lines={line['contract_id']:line for line in body['sizing']['lines']}
    if set(filled)-set(lines) or any(D(value)<0 or D(value)!=D(value).to_integral_value() for value in filled.values()):
        raise QuantError('INVALID_OPTION_PROGRESS','资源转换需要已关联的非负整张成交数量')
    risk=body['request']['risk'];remaining={};cash=D(0);shares={}
    contracts={leg['contract']['contract_id']:OptionContract.from_dict(leg['contract']) for leg in selection['legs']}
    for identity,line in lines.items():
        quantity=max(D(0),D(line['contracts'])-D(filled.get(identity,0)))
        remaining[identity]=str(quantity)
        if not quantity:continue
        contract=contracts[identity]
        cash+=quantity*D(risk['fee_per_contract'])
        if line['side']=='BUY':cash+=quantity*D(line['estimated_unit_price'])*contract.quote_multiplier
        elif contract.right=='PUT':cash+=quantity*contract.exercise_cash
        elif selection['template_id'] in FUNDED_CALL_PROTECTION:
            protection=next(c for key,c in contracts.items() if lines[key]['side']=='BUY' and c.right=='CALL')
            cash+=quantity*protection.exercise_cash
        else:shares[contract.underlying]=shares.get(contract.underlying,D(0))+quantity*contract.deliverable_shares
    if selection['template_id'] in {'protective_put','collar'}:
        put=next(c for key,c in contracts.items() if c.right=='PUT' and lines[key]['side']=='BUY')
        # Shares already covering a filled short call must not be reserved a second time.
        covered=sum(min(D(lines[key]['contracts']),max(D(0),D(filled.get(key,0))))*c.deliverable_shares
                    for key,c in contracts.items() if c.right=='CALL' and lines[key]['side']=='SELL')
        needed=max(D(0),D(remaining[put.contract_id])*put.deliverable_shares-covered)
        shares[put.underlying]=max(shares.get(put.underlying,D(0)),needed)
    if any(D(value)>0 for value in remaining.values()):
        cash+=D(risk['cash_buffer'])+D(risk['early_assignment_cash_reserve'])
    return {'reserved_cash':str(cash),'reserved_positions':{key:str(q) for key,q in shares.items() if q},
            'remaining_contracts':remaining}


def sizing(selection,snapshot,packages,risk):
    if set(risk)!=RISK_FIELDS:raise QuantError('INVALID_OPTION_RISK','须明确所有期权资金、费用和风险参数')
    p={key:D(value) for key,value in risk.items()};q=D(packages)
    if q<=0 or q!=q.to_integral_value() or any(value<0 for value in p.values()):
        raise QuantError('INVALID_OPTION_RISK','张数须为正整数，资金/费用/风险参数不能为负')
    if p['maximum_contracts']!=p['maximum_contracts'].to_integral_value() or p['adverse_slippage_fraction']>=1:
        raise QuantError('INVALID_OPTION_RISK','张数上限须为整数，滑点比例须小于1')
    issues=[];lines=[];legs=[];cash=D(0);premium=D(0);fees=D(0);collateral=D(0);call_exercise_cash=D(0);shares={}
    if selection['status']!='SELECTED_FOR_RESEARCH':issues.append('NO_ELIGIBLE_CONTRACT')
    for selected in selection['legs']:
        c=OptionContract.from_dict(selected['contract']);sign=selected['quantity_per_package'];quantity=q*sign
        quote=selected['reference_quote'];raw=D(quote['ask'] if sign>0 else quote['bid'])
        execution_price=raw*(1+p['adverse_slippage_fraction'] if sign>0 else 1-p['adverse_slippage_fraction'])
        if execution_price<=0:issues.append('NONPOSITIVE_EXECUTION_PRICE')
        if q>D(quote['ask_size'] if sign>0 else quote['bid_size']):issues.append('INSUFFICIENT_QUOTED_SIZE:'+c.contract_id)
        fee=q*p['fee_per_contract'];fees+=fee
        net=quantity*execution_price*c.quote_multiplier;premium+=net
        if sign>0:cash+=net
        elif c.right=='PUT':collateral+=q*c.exercise_cash
        elif selection['template_id'] not in FUNDED_CALL_PROTECTION:
            shares[c.underlying]=shares.get(c.underlying,D(0))+q*c.deliverable_shares
        lines.append({'contract_id':c.contract_id,'contract_version':c.version_hash,'side':'BUY' if sign>0 else 'SELL',
                      'contracts':str(q),'reference_bid':quote['bid'],'reference_ask':quote['ask'],
                      'reference_at':quote['exchange_timestamp'],'estimated_unit_price':str(execution_price),
                      'multiplier':str(c.quote_multiplier),'estimated_fee':str(fee)})
        legs.append({'kind':c.right,'quantity':str(quantity),'entry_price':str(execution_price),'strike':str(c.strike),
                     'multiplier':str(c.quote_multiplier),'expiry':c.expiry,'fee':str(fee)})
    if legs:
        c=OptionContract.from_dict(selection['legs'][0]['contract']);spot=D(selection['legs'][0]['reference_quote']['underlying_price'])
        if selection['template_id'] in {'protective_put','collar'}:
            shares[c.underlying]=max(shares.get(c.underlying,D(0)),q*c.deliverable_shares)
        if selection['template_id'] in {'protective_put','collar','covered_call'}:
            legs.append({'kind':'STOCK','quantity':str(q*c.deliverable_shares),'entry_price':str(spot)})
        notional=q*c.quote_multiplier*spot
        if selection['template_id'] in FUNDED_CALL_PROTECTION:
            protection=next(leg for leg in selection['legs'] if leg['quantity_per_package']>0 and leg['contract']['right']=='CALL')
            call_exercise_cash=q*OptionContract.from_dict(protection['contract']).exercise_cash
        payoff=analyze(legs)
        if payoff['loss_unbounded']:issues.append('UNBOUNDED_LOSS')
        elif D(payoff['maximum_loss'])>p['maximum_loss_budget']:issues.append('LOSS_BUDGET_EXCEEDED')
        if notional>p['maximum_notional']:issues.append('NOTIONAL_LIMIT_EXCEEDED')
    else:notional=D(0);payoff=None
    if q>p['maximum_contracts']:issues.append('CONTRACT_LIMIT_EXCEEDED')
    if cash+fees>p['premium_budget']:issues.append('PREMIUM_BUDGET_EXCEEDED')
    # Short-leg premium is not assumed available before every leg has settled.
    needed=cash+fees+collateral+call_exercise_cash+p['cash_buffer']+p['early_assignment_cash_reserve']
    if needed>D(snapshot['available_cash']):issues.append('INSUFFICIENT_SETTLED_CASH')
    for symbol,required in shares.items():
        available=D(snapshot['positions'].get(symbol,0))-D(snapshot['reserved_positions'].get(symbol,0))
        if available<required:issues.append('UNDERLYING_ALREADY_RESERVED_OR_INSUFFICIENT:'+symbol)
    if snapshot['equity'] is None:issues.append('INCOMPLETE_ACCOUNT_VALUATION')
    if snapshot['anomalies']:issues.append('ACCOUNT_RECONCILIATION_REQUIRED')
    if snapshot.get('pending_option_exits'):issues.append('PENDING_OPTION_EXIT')
    return {'lines':lines,'net_premium_debit':str(premium),'gross_buy_premium':str(cash),'estimated_fees':str(fees),
            'required_cash':str(needed),'put_cash_collateral':str(collateral),
            'call_exercise_cash_reserve':str(call_exercise_cash),
            'covered_or_protected_shares':{key:str(value) for key,value in shares.items()},
            'notional':str(notional),'notional_basis':'package_underlying_equivalent','gross_option_notional':str(notional*len(selection['legs'])),
            'contract_limit_basis':'per_leg_contracts','gross_contracts':str(q*len(selection['legs'])),'expiry_payoff':payoff,'checks':sorted(set(issues)),
            'sizing_status':'PASSED' if not issues else 'BLOCKED'}


def draft(ledger,store,snapshot_id,account_id,request):
    if set(request)!={'selection','packages','risk','revision'} or type(request['revision']) is not int or request['revision']<1:
        raise QuantError('INVALID_OPTION_PLAN','草案需选约、整张数、完整风险参数和正整数修订号')
    if ledger.connection.execute('SELECT version FROM schema_version').fetchone()[0]<5:raise QuantError('V19_NOT_ENABLED','期权草案需要v5')
    selection=select(store,snapshot_id,request['selection'])
    intent=digest({'account_id':account_id,'decision_hash':selection['decision_hash'],'risk':request['risk'],'packages':request['packages']})
    identity=digest({'intent_id':intent,'revision':request['revision']})
    with publication_lock(ledger.path.parent),ledger.transaction():
        old=ledger.connection.execute('SELECT payload,status FROM option_plans WHERE plan_id=?',(identity,)).fetchone()
        if old:return {**json.loads(old['payload']),'status':old['status']}
        prices={}
        for leg in selection['legs']:
            c=OptionContract.from_dict(leg['contract']);r=leg['reference_quote']
            prices[c.underlying]=r['underlying_price'];prices[c.contract_id]=str((D(r['bid'])+D(r['ask']))/2)
        snapshot=ledger.snapshot(account_id,selection['decision_at'],prices)
        result=sizing(selection,snapshot,request['packages'],request['risk'])
        blocks=result['checks']+['LYRAX_ENGINE_LIFECYCLE_NOT_VALIDATED']
        if ledger.environment!='demo':blocks+=['OPTION_SOURCE_QUALIFICATION_REQUIRED','ACCOUNT_OPTION_PERMISSIONS_REQUIRED']
        body={'plan_id':identity,'intent_id':intent,'revision':request['revision'],'account_id':account_id,
              'environment':ledger.environment,'data_type':selection['data_type'],'snapshot_id':snapshot_id,
              'status':'DRAFT','check_status':'BLOCKED','executable':False,'created_at':now_utc(),
              'decision_at':selection['decision_at'],'selection':selection,'sizing':result,'account_basis':snapshot,
              'checks':sorted(set(blocks)),'request':request,
              'limitations':['草案仅供研究审阅，不预留资源、不代表已下单；当前尚未通过LyraX完整成熟引擎生命周期验证',
                             '单腿分别成交、提前指派与价差保护路径必须另行验证，不能只凭终值损失证明可执行']}
        for previous in ledger.connection.execute("SELECT plan_id,payload FROM option_plans WHERE account_id=? AND status='DRAFT'",(account_id,)).fetchall():
            payload=json.loads(previous['payload'])
            if payload['intent_id']==intent:
                if payload.get('manual_execution',{}).get('pending'):
                    raise QuantError('PENDING_MANUAL_ORDER','已有在途人工订单，不能替代其占用')
                if payload['revision']>=request['revision']:raise QuantError('OPTION_REVISION_CONFLICT','修订号必须递增')
                ledger.connection.execute("UPDATE option_plans SET status='SUPERSEDED' WHERE plan_id=?",(previous['plan_id'],))
        ledger.connection.execute('INSERT INTO option_plans VALUES(?,?,?,?,?,?,?)',
            (identity,account_id,'DRAFT',canonical(body),'0','{}',body['created_at']))
    return body
