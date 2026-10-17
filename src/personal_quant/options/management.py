"""Point-in-time exit checks; proposals never manufacture fills or broker orders."""
from datetime import timedelta
import hashlib
from pathlib import Path
from zoneinfo import ZoneInfo
from ..common import QuantError,utc,decimal as D,digest
from ..data.calendar import Calendar
from .contracts import OptionContract
from .data import quality
from .lifecycle import review

FIELDS={'plan_id','as_of','snapshot_id','trigger','exit_days','fee_per_contract',
        'max_age_seconds','max_underlying_skew_seconds','max_spread_fraction',
        'max_leg_skew_seconds','max_underlying_price_fraction','reconciliation_max_days'}


def exit_due_at(contract,days):
    """Move a non-session exit date back; respect half days and contract deadline."""
    date=utc(contract.exercise_cutoff_at).astimezone(ZoneInfo(contract.market_timezone)).date()-timedelta(days=days)
    calendar=Calendar.market(str(date-timedelta(days=14)),str(date+timedelta(days=1)))
    sessions=calendar.sessions[calendar.sessions.date<=date]
    if not len(sessions):raise QuantError('CALENDAR_RANGE','退出检查日之前无合格市场交易日')
    return min(calendar.close(sessions[-1]).to_pydatetime(),utc(contract.last_trade_at))-timedelta(minutes=20)


def preview_exit(book,store,request):
    with book.transaction():
        return _preview_exit(book,store,request)


def _preview_exit(book,store,request):
    if not isinstance(request,dict) or set(request)!=FIELDS or request['trigger'] not in {'EXPIRY_WINDOW','RISK_REDUCTION'}:
        raise QuantError('INVALID_OPTION_EXIT','需明确计划、时点、报价、到期窗口/风险减仓及完整检查参数')
    for key in FIELDS-{'plan_id','as_of','snapshot_id','trigger'}:
        if D(request[key])<0:raise QuantError('INVALID_OPTION_EXIT','退出检查参数必须非负')
    days=D(request['exit_days']);recon=D(request['reconciliation_max_days'])
    if days!=days.to_integral_value() or recon!=recon.to_integral_value():
        raise QuantError('INVALID_OPTION_EXIT','退出与对账天数必须为整数')
    clock=utc(request['as_of']);body=review(book,request['plan_id'],clock)
    selected={leg['contract']['contract_id']:OptionContract.from_dict(leg['contract']) for leg in body['selection']['legs']}
    positions={s:D(q) for s,q in body['lifecycle']['open_contracts'].items() if D(q)!=0}
    due=min(exit_due_at(selected[s],int(days)) for s in positions) if positions else None
    result={'plan_id':body['plan_id'],'account_id':body['account_id'],'as_of':clock.isoformat(),
        'environment':book.environment,'data_type':'account_event_state',
        'ledger_seq':book.sequence(body['account_id']),'request':request,'request_hash':digest(request),
        'due_at':due.isoformat() if due else None,'current_contracts':{s:str(q) for s,q in positions.items()},
        'status':'NO_POSITION' if not positions else 'NOT_DUE' if request['trigger']=='EXPIRY_WINDOW' and clock<due else 'CHECKED',
        'lines':[],'checks':[],'executable':False,'execution_status':'DRAFT','no_account_writes':True,
        'rule_version':'option-exit/1.0.0','rule_hash':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'meaning':'只读退出建议；不增加风险、滚仓、记成交、释放担保或提交券商订单'}
    result['management_id']='option-exit:'+digest({'request':request,'rule_hash':result['rule_hash'],
        'ledger_seq':result['ledger_seq'],'positions':result['current_contracts']})
    if result['status'] in {'NO_POSITION','NOT_DUE'}:return result
    checks=list(body['progress']['fact_anomalies']);marks={};quotes_used=[]
    if body.get('manual_execution',{}).get('pending'):checks.append('PENDING_MANUAL_ORDER')
    contracts,quotes,metadata,_=store.load(request['snapshot_id']);latest={}
    for quote in quotes:
        if all(utc(quote[field])<=clock for field in ('exchange_timestamp','available_at','received_at')):
            s=quote['contract_id']
            if s not in latest or utc(quote['exchange_timestamp'])>utc(latest[s]['exchange_timestamp']):latest[s]=quote
    sides={line['contract_id']:line['side'] for line in body['sizing']['lines']}
    # Short obligations must be closed before selling their protective long legs.
    short_ids=sorted(s for s in positions if sides[s]=='SELL')
    for s in sorted(positions,key=lambda s:(s not in short_ids,s)):
        c=selected[s];q=positions[s];quote=latest.get(s)
        if q<=0:checks.append('INVALID_PLAN_POSITION:'+s);continue
        if quote is None or s not in contracts or contracts[s].version_hash!=c.version_hash:
            checks.append('MISSING_EXIT_QUOTE:'+s);continue
        issues=quality(quote,c,clock,max_age_seconds=float(request['max_age_seconds']),
            max_underlying_skew_seconds=float(request['max_underlying_skew_seconds']),max_spread_fraction=request['max_spread_fraction'])
        checks.extend(issue+':'+s for issue in issues)
        side='BUY' if sides[s]=='SELL' else 'SELL';price=D(quote['ask'] if side=='BUY' else quote['bid'])
        if q>D(quote['ask_size'] if side=='BUY' else quote['bid_size']):checks.append('INSUFFICIENT_EXIT_QUOTE_SIZE:'+s)
        fee=q*D(request['fee_per_contract']);quotes_used.append(quote)
        marks[s]=(D(quote['bid'])+D(quote['ask']))/2;marks[c.underlying]=quote['underlying_price']
        result['lines'].append({'contract_id':s,'contract_version':c.version_hash,'action':'CLOSE','side':side,
            'contracts':str(q),'reference_price':str(price),'reference_at':quote['exchange_timestamp'],
            'estimated_fee':str(fee),'gross_amount':str(q*price*c.quote_multiplier),
            'depends_on':short_ids if side=='SELL' else [],'reason':request['trigger']})
    if len(quotes_used)>1:
        times=[utc(q['exchange_timestamp']) for q in quotes_used];spots=[D(q['underlying_price']) for q in quotes_used]
        if (max(times)-min(times)).total_seconds()>float(request['max_leg_skew_seconds']):checks.append('EXIT_LEG_TIME_MISMATCH')
        if min(spots)<=0 or max(spots)/min(spots)-1>D(request['max_underlying_price_fraction']):checks.append('EXIT_UNDERLYING_PRICE_MISMATCH')
    account=book.snapshot(body['account_id'],clock,marks);checks.extend(account['anomalies'])
    if account['missing_prices']:checks.append('INCOMPLETE_ACCOUNT_VALUATION')
    try:book.check_reconciliation(body['account_id'],clock,int(recon))
    except QuantError as exc:checks.append(exc.code)
    # Buying back a short can use its own collateral only as a condition of
    # that close. Do not release it in the ledger or borrow other obligations'
    # collateral, and do not fund buys with expected protective-leg sales.
    from .ledger import collateral
    remaining={s:D(q) for s,q in account['option_positions'].items()}
    terms={}
    for e in book.active_events(body['account_id'],clock):
        if e['kind'].startswith('OPTION_'):terms[e['symbol']]=OptionContract.from_dict(e['contract'])
    for line in result['lines']:
        if line['side']=='BUY':remaining[line['contract_id']]=remaining.get(line['contract_id'],D(0))+D(line['contracts'])
    future_collateral,_,_=collateral({s:D(q) for s,q in account['positions'].items()},remaining,terms)
    release=max(D(0),D(account['option_cash_collateral'])-future_collateral)
    need=sum((D(line['gross_amount'])+D(line['estimated_fee']) for line in result['lines'] if line['side']=='BUY'),D(0))
    need+=sum((max(D(0),D(line['estimated_fee'])-D(line['gross_amount'])) for line in result['lines'] if line['side']=='SELL'),D(0))
    if need>D(account['available_cash'])+release:checks.append('INSUFFICIENT_EXIT_CASH')
    if book.environment!='demo':checks.extend(['OPTION_SOURCE_QUALIFICATION_REQUIRED','ACCOUNT_OPTION_PERMISSIONS_REQUIRED'])
    elif metadata['data_type']!='synthetic':checks.append('DEMO_SYNTHETIC_REQUIRED')
    result.update(status='BLOCKED' if checks else 'CHECKED',checks=sorted(set(checks)),account_basis=account,
        required_buy_cash=str(need),conditional_cash_release=str(release),
        available_after_short_close=str(D(account['available_cash'])+release),
        data_type=metadata['data_type'],quote_snapshot_id=request['snapshot_id'])
    return result
