"""Finite-scenario checks of every partial-fill quantity vertex; no financial writes."""
from itertools import product
from copy import deepcopy
from ..common import QuantError, decimal as D, digest
from ..options.contracts import OptionContract
from .stress import evaluate as scenario_stress

LIMITS={'stock_cost_bps','option_fee_per_contract','adverse_slippage_fraction',
        'cash_buffer','minimum_sample_equity','maximum_sample_loss'}


def evaluate(risk,stage,remaining,contracts,quotes,request):
    if (not isinstance(request,dict) or set(request)!={'scenarios','models','limits'}
            or not isinstance(request['limits'],dict) or set(request['limits'])!=LIMITS
            or any(D(v)<0 for v in request['limits'].values())
            or D(request['limits']['adverse_slippage_fraction'])>=1):
        raise QuantError('INVALID_STAGE_STRESS','需完整显式成本/现金缓冲/有限情景阈值及模型')
    limits={k:D(v) for k,v in request['limits'].items()}
    lines=[]
    for line in stage['lines']:
        key=str((line['symbol'],line['contract_version'],line['side']))
        q=D(remaining[key])
        if not 0<=q<=D(line['quantity']):raise QuantError('INVALID_STAGE_QUANTITY','剩余数量须在原计划范围')
        if q:lines.append((line,q))
    if len(lines)>8:raise QuantError('STAGE_GRID_TOO_LARGE','最多8腿、256个数量端点，不截断未检查路径')
    account=risk['account'];baseline=D(account['equity'])
    if baseline<=0 or account.get('missing_prices') or account.get('anomalies'):
        raise QuantError('COMPLETE_ACCOUNT_EQUITY_REQUIRED','阶段压力需完整权益及无账务异常')
    terms={s:OptionContract.from_dict(c) for s,c in contracts.items()}
    current={s:D(q) for s,q in account.get('option_positions',{}).items()}
    if set(current)-set(terms):raise QuantError('MODEL_INPUT_REQUIRED','实际期权条款不完整')
    candidate_terms={}
    for line,_ in lines:
        if stage['plan_kind']=='option':
            c=terms.get(line['symbol'])
            if c is None or c.version_hash!=line['contract_version']:
                raise QuantError('OPTION_UNIT_CONFLICT','阶段合约单位/版本不匹配')
            c.require_standard_vanilla();candidate_terms[c.contract_id]=c
            quote=quotes.get(c.contract_id)
            if not quote or D(quote['bid'])<0 or D(quote['ask'])<=0 or D(quote['bid'])>D(quote['ask']):
                raise QuantError('MISSING_CURRENT_QUOTE','每腿需明确当前bid/ask')
    used=set(current)|set(candidate_terms)
    versions={terms[s].version_hash for s in used}
    if set(request['models'])!=versions:raise QuantError('MODEL_INPUT_REQUIRED','需实际和拟交易全部确切合约模型')
    if (2**len(lines))*len(request['scenarios'])*max(1,len(versions))>1500:
        raise QuantError('STAGE_GRID_TOO_LARGE','所有数量端点合计最多1500个合约情景，不抽样或省略中间状态')
    universe=set(account['positions'])|{terms[s].underlying for s in used}
    state_risk=deepcopy(risk)
    # Explicit zero positions keep the same scenario symbol universe at every vertex.
    for s in universe:state_risk['account']['positions'].setdefault(s,'0')
    held_contracts={s:contracts[s] for s in current}
    points=[]
    for bits in product((0,1),repeat=len(lines)):
        stocks={s:D(q) for s,q in state_risk['account']['positions'].items()}
        options=dict(current);trades=[];legs=[];friction=D(0);buy_cash=D(0);sell_receivable=D(0)
        quantities={};problems=[]
        for bit,(line,maximum) in zip(bits,lines):
            q=maximum*bit;symbol=line['symbol'];quantities[symbol]=str(q)
            if not q:continue
            sign=1 if line['side']=='BUY' else -1
            if stage['plan_kind']=='stock':
                raw=D(risk['valuation']['prices'][symbol]);fee=q*raw*limits['stock_cost_bps']/D(10000)
                fee+=q*raw*limits['adverse_slippage_fraction']
                stocks[symbol]=stocks.get(symbol,D(0))+sign*q
                trades.append(dict(kind='stock',symbol=symbol,side=line['side'],quantity=str(q)))
                debit=q*raw+fee if sign>0 else max(D(0),fee-q*raw)
                if sign<0:sell_receivable+=max(D(0),q*raw-fee)
                friction+=fee
            else:
                c=terms[symbol];quote=quotes[symbol];mid=(D(quote['bid'])+D(quote['ask']))/2
                size=quote.get('ask_size' if sign>0 else 'bid_size')
                if size is None or q>D(size):problems.append('INSUFFICIENT_QUOTED_SIZE:'+symbol)
                raw=D(quote['ask'] if sign>0 else quote['bid'])
                price=raw*(1+sign*limits['adverse_slippage_fraction'])
                fee=q*limits['option_fee_per_contract'];gross=q*price*c.quote_multiplier
                debit=gross+fee if sign>0 else max(D(0),fee-gross)
                if sign<0:sell_receivable+=max(D(0),gross-fee)
                friction+=q*c.quote_multiplier*sign*(price-mid)+fee
                options[symbol]=options.get(symbol,D(0))+sign*q
                legs.append(dict(contract=c.content(),quantity_per_package=str(sign*q)))
            buy_cash+=debit
        if any(q<0 for q in stocks.values()):problems.append('PROJECTED_SHORT_STOCK')
        # Gross short-put exercise obligation: never borrow unreceived short-leg premium.
        initial_put=sum((max(D(0),-q)*terms[s].exercise_cash for s,q in current.items() if terms[s].right=='PUT'),D(0))
        projected_put=sum((max(D(0),-q)*terms[s].exercise_cash for s,q in options.items() if terms[s].right=='PUT'),D(0))
        needed=buy_cash+max(D(0),projected_put-initial_put)+limits['cash_buffer']
        if needed>D(account['available_cash']):problems.append('INSUFFICIENT_SETTLED_CASH_AT_VERTEX')
        short_calls={}
        for symbol,q in options.items():
            c=terms[symbol]
            if c.right=='CALL' and q<0:short_calls[c.underlying]=short_calls.get(c.underlying,D(0))-q*c.deliverable_shares
        for symbol,q in short_calls.items():
            existing=sum((max(D(0),-n)*terms[s].deliverable_shares for s,n in current.items()
                if terms[s].right=='CALL' and terms[s].underlying==symbol),D(0))
            other_reserved=max(D(0),D(account.get('reserved_positions',{}).get(symbol,0))-existing)
            if stocks.get(symbol,D(0))-other_reserved<q:problems.append('UNCOVERED_CALL_AT_VERTEX:'+symbol)
        # A CLOSE must not cross through zero and become a new reverse position.
        if stage['plan_kind']=='option' and stage['action']=='CLOSE':
            for symbol,q in options.items():
                if symbol in quantities and (current.get(symbol,D(0))==0 and q!=0 or current.get(symbol,D(0))*q<0):
                    problems.append('CLOSE_EXCEEDS_ACTUAL_POSITION:'+symbol)
        active_terms=set(current)|{leg['contract']['contract_id'] for leg in legs}
        candidate=dict(status='SELECTED_FOR_RESEARCH',preview_hash=digest(quantities),trades=trades,
                       E_post=str(baseline-friction),selection=dict(legs=legs),incremental_packages=1)
        stress=scenario_stress(state_risk,candidate,held_contracts,dict(scenarios=request['scenarios'],
            models={terms[s].version_hash:request['models'][terms[s].version_hash] for s in active_terms}))
        minimum=min(D(p['candidate_equity']) for p in stress['points'])
        loss=D(stress['worst_sample_candidate_loss'])
        if minimum<limits['minimum_sample_equity']:problems.append('MINIMUM_SAMPLE_EQUITY_BREACHED')
        if loss>limits['maximum_sample_loss']:problems.append('MAXIMUM_SAMPLE_LOSS_BREACHED')
        points.append(dict(quantities=quantities,status='BLOCKED' if problems else 'CHECKED',checks=sorted(set(problems)),
            required_settled_cash=str(needed),sale_proceeds_not_available=str(sell_receivable),friction=str(friction),
            stock_positions={s:str(q) for s,q in stocks.items()},option_positions={s:str(q) for s,q in options.items()},
            minimum_sample_equity=str(minimum),worst_sample_loss=str(loss),scenarios=stress['points']))
    result=dict(schema_version=1,artifact_type='hedge_stage_stress',group_stage_id=stage['stage_id'],
        exposure_id=risk['exposure_id'],as_of=risk['as_of'],ledger_seq=risk['ledger_seq'],data_type='scenario_only',
        status='BLOCKED' if any(p['status']=='BLOCKED' for p in points) else 'CHECKED',vertices=points,
        checks=sorted({c for p in points for c in p['checks']}),request=request,executable=False,creates_reservations=False,
        limits_of_evidence=['有限情景不能保证最大损失；不模拟提前指派、交割或期间现金流',
            '逐腿数量端点覆盖固定报价下的线性部分成交组合；报价变化须重新检查',
            '未计未到账卖出款或释放原预留；不是来源/权限/逐阶段激活证明'])
    result['assessment_id']=digest(result);return result
