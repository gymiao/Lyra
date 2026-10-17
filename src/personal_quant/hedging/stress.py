"""Account-wide finite scenarios using existing QuantLib valuation only."""
from datetime import date
from zoneinfo import ZoneInfo
from ..common import QuantError,decimal as D,digest,utc
from ..options.contracts import OptionContract
from ..options.pricing import price
from ..strategies.archive import source_fingerprint
from .archive import load
from .preview import preview

SCENARIO={'name','horizon_date','benchmark_return','beta_multiplier','residual_returns','volatility_multiplier'}
MODEL={'volatility','rate','dividend_yield'}


def evaluate(risk,candidate,contracts,request):
    if (not isinstance(request,dict) or set(request)!={'scenarios','models'}
            or not isinstance(request['scenarios'],list) or not 1<=len(request['scenarios'])<=300
            or not isinstance(request['models'],dict)):
        raise QuantError('INVALID_HEDGE_STRESS','压力分析需显式情景网格和逐合约模型')
    if candidate['status'] not in {'SELECTED_FOR_RESEARCH','KEEP'}:
        raise QuantError('HEDGE_CANDIDATE_REQUIRED','不可行或在途待核对候选不能假装已经完成')
    state=risk['account'];E=D(state['equity'])
    if E<=0 or state.get('missing_prices') or state.get('anomalies'):
        raise QuantError('COMPLETE_ACCOUNT_EQUITY_REQUIRED','压力分析需完整冻结权益及无未解决账务差异')
    start=utc(risk['as_of']).astimezone(ZoneInfo('America/New_York')).date()
    before={s:D(q) for s,q in state['positions'].items()};after=dict(before)
    option_before={};terms={}
    for symbol,q in state.get('option_positions',{}).items():
        c=OptionContract.from_dict(contracts[symbol]);c.require_standard_vanilla()
        terms[c.version_hash]=c;option_before[c.version_hash]=D(q)
    option_after=dict(option_before)
    for trade in candidate['trades']:
        if trade.get('kind')=='option':continue
        q=D(trade['quantity'])
        if trade.get('kind')=='stock' and trade['side']=='SELL':q=-q
        after[trade['symbol']]=after.get(trade['symbol'],D(0))+q
    for leg in candidate.get('selection',{}).get('legs',[]):
        c=OptionContract.from_dict(leg['contract']);c.require_standard_vanilla()
        q=D(candidate.get('incremental_packages',0))*D(leg['quantity_per_package'])
        if not q:continue
        terms[c.version_hash]=c;option_after[c.version_hash]=option_after.get(c.version_hash,D(0))+q
    if any(q<0 for q in after.values()):raise QuantError('UNSUPPORTED_SHORT','股票压力候选不能新增空头')
    symbols=set(before)|set(after)|{c.underlying for c in terms.values()}
    prices=risk['valuation']['prices'];estimates=risk['beta_model']['estimates']
    if (any(s not in prices or D(prices[s])<=0 for s in symbols)
            or set(request['models'])!=set(terms)):
        raise QuantError('MODEL_INPUT_REQUIRED','需要全部股票/期权标的冻结原价及Beta和确切合约模型')
    if len(request['scenarios'])*max(1,len(terms))>1500:
        raise QuantError('INVALID_HEDGE_STRESS','有限网格最多1500个合约情景')
    for version,c in terms.items():
        model=request['models'][version]
        if not isinstance(model,dict) or set(model)!=MODEL:
            raise QuantError('MODEL_INPUT_REQUIRED','每个合约需明确IV、利率及连续股息率')
        if not 0<D(model['volatility'])<=4 or not -1<D(model['rate'])<1 or not 0<=D(model['dividend_yield'])<1:
            raise QuantError('INVALID_HEDGE_STRESS','显式模型参数超出可验证范围')
        if date.fromisoformat(c.expiry)<=start:
            raise QuantError('UNOBSERVED_EXPIRY_PATH','已到期头寸须先以实际生命周期事实解决')
    def value(c,spot,day,scale):
        if day==date.fromisoformat(c.expiry):
            return max(spot-c.strike,D(0)) if c.right=='CALL' else max(c.strike-spot,D(0))
        m=request['models'][c.version_hash]
        return D(price(right=c.right,style=c.style,spot=spot,strike=c.strike,
            valuation_date=day.isoformat(),expiry=c.expiry,volatility=D(m['volatility'])*scale,
            rate=m['rate'],dividend_yield=m['dividend_yield'],multiplier=1,contracts=1)['unit_price'])
    initial={v:value(c,D(prices[c.underlying]),start,D(1)) for v,c in terms.items()}
    rows=[];names=set();Epost=D(candidate.get('E_post',E))
    for scenario in request['scenarios']:
        if (not isinstance(scenario,dict) or set(scenario)!=SCENARIO or not isinstance(scenario['name'],str)
                or not scenario['name'] or scenario['name'] in names or not isinstance(scenario['residual_returns'],dict)
                or set(scenario['residual_returns'])!=symbols):
            raise QuantError('INVALID_HEDGE_STRESS','情景名称唯一且每个标的需显式残余收益')
        names.add(scenario['name']);horizon=date.fromisoformat(scenario['horizon_date'])
        if horizon<start or any(horizon>date.fromisoformat(c.expiry) for c in terms.values()):
            raise QuantError('UNOBSERVED_EXPIRY_PATH','情景不跨越未经观测的合约到期/交割路径')
        scale=D(scenario['volatility_multiplier'])
        if scale<=0 or any(D(m['volatility'])*scale>4 for m in request['models'].values()):
            raise QuantError('INVALID_HEDGE_STRESS','IV倍率须为正且模型IV不能超过4')
        benchmark_move=D(scenario['benchmark_return'])*D(scenario['beta_multiplier'])
        if benchmark_move and any(estimates.get(s,{}).get('status')!='CHECKED' for s in symbols):
            raise QuantError('MODEL_INPUT_REQUIRED','非零基准情景须有每个标的合格Beta；不得把缺失Beta当作零')
        # A direct per-security scenario does not require a benchmark model.
        # No replacement Beta is fabricated when the benchmark contribution is explicitly zero.
        marks={s:D(prices[s])*(1+(D(estimates[s]['beta'])*benchmark_move if benchmark_move else D(0))
            +D(scenario['residual_returns'][s])) for s in symbols}
        if any(p<=0 for p in marks.values()):raise QuantError('INVALID_HEDGE_STRESS','情景原价必须为正')
        changes={v:(value(c,marks[c.underlying],horizon,scale)-initial[v])*c.quote_multiplier for v,c in terms.items()}
        def pnl(stocks,options):
            stock=sum((q*(marks[s]-D(prices[s])) for s,q in stocks.items()),D(0))
            option=sum((q*changes[v] for v,q in options.items()),D(0))
            return stock,option
        bs,bo=pnl(before,option_before);hs,ho=pnl(after,option_after)
        pre=E+bs+bo;post=Epost+hs+ho
        rows.append(dict(name=scenario['name'],horizon_date=horizon.isoformat(),prices={s:str(p) for s,p in marks.items()},
            unhedged_equity=str(pre),candidate_equity=str(post),unhedged_pnl=str(pre-E),candidate_pnl=str(post-E),
            unhedged_stock_change=str(bs),unhedged_option_change=str(bo),candidate_stock_change=str(hs),
            candidate_option_change=str(ho),initial_friction=str(E-Epost),protection_difference=str(post-pre)))
    body=dict(schema_version=1,artifact_type='hedge_stress',data_type='scenario_only',executable=False,
        exposure_id=risk['exposure_id'],candidate_hash=candidate['preview_hash'],request=request,as_of=risk['as_of'],
        ledger_seq=risk['ledger_seq'],account_id=risk['account_id'],environment=risk['environment'],
        source_fingerprint=source_fingerprint(),points=rows,
        worst_sample_unhedged_loss=str(max(D(0),-min(D(r['unhedged_pnl']) for r in rows))),
        worst_sample_candidate_loss=str(max(D(0),-min(D(r['candidate_pnl']) for r in rows))),
        maximum_loss='NOT_INFERRED_FROM_FINITE_GRID',
        valuation_basis='冻结权益及成交摩擦为锚；QuantLib理论价值变化，不把理论初始价替换原报价',
        limitations=['所有候选阶段假设已按条件完成，筹资尚未到账；不产生账户事实',
            'beta_multiplier和残余收益是相关性失效敏感度假设，不是估计相关系数或保证代理底线',
            '现金/应收应付保持冻结；不模拟利息、期间分红到账、提前指派或交割',
            '连续股息率只用于显式期权模型；反向ETF终点为条件价格情景，不证明日复利实际路径',
            '到期内在价值仅情景估值；必须另以官方引擎和生命周期事实验证账户'])
    body['stress_id']=digest(body);return body


def analyze(book,account_id,request):
    if not isinstance(request,dict) or set(request)!={'preview_request','scenarios','models'}:
        raise QuantError('INVALID_HEDGE_STRESS','压力入口需候选请求、情景和模型')
    with book.transaction():
        candidate=preview(book,account_id,request['preview_request'])
        risk=load(book.path.parent/'hedging/exposures',candidate['exposure_id'])
        basis=digest([dict(r) for r in book.connection.execute(
            'SELECT seq,event_id,content_hash,effective_at,recorded_at,payload FROM events WHERE account_id=? AND seq<=? ORDER BY seq',
            (account_id,risk['ledger_seq']))])
        if basis!=risk['ledger_basis_hash']:raise QuantError('CORRUPT_EXPOSURE_ARCHIVE','原账户前缀已改变')
        contracts={e['symbol']:e['contract'] for e in book.active_events(account_id,risk['as_of'],ledger_seq=risk['ledger_seq'])
                   if e['kind'].startswith('OPTION_')}
    return evaluate(risk,candidate,contracts,{k:request[k] for k in ('scenarios','models')})

