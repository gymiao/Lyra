"""Frozen A8 contract selection using only quotes received by the decision."""
from datetime import date
from pathlib import Path
import hashlib
from zoneinfo import ZoneInfo
from ..common import QuantError, decimal, digest, utc
from .catalog import MONTHLY_RESEARCH, FOUR_LEG
from .data import quality

FIELDS={'target_dte','minimum_dte','maximum_dte','put_moneyness','call_moneyness',
        'exit_days_before_expiry','max_age_seconds','max_underlying_skew_seconds',
        'max_spread_fraction','max_leg_skew_seconds','max_underlying_price_fraction'}
RULE_VERSION='monthly-selection/2.0.0'


def rule_identity():
    """Record the exact local rule implementation without including market rows."""
    root=Path(__file__).parent
    files={name:hashlib.sha256((root/name).read_bytes()).hexdigest()
           for name in ('selection.py','contracts.py','data.py','catalog.py')}
    return {'strategy_version':RULE_VERSION,'rule_source_hash':digest(files),'rule_source_files':files}


def select(store, snapshot_id, request):
    if set(request)!={'template_id','underlying','decision_at','parameters'} or request['template_id'] not in MONTHLY_RESEARCH:
        raise QuantError('INVALID_OPTION_RULE','选约请求需已实现研究模板、标的、决策时间和明确参数')
    params=request['parameters']
    four=request['template_id'] in FOUR_LEG
    credit=request['template_id'].endswith('credit_spread') or four
    if set(params)!=(FIELDS|{'minimum_spread_width'} if credit else FIELDS):raise QuantError('INVALID_OPTION_RULE','选约参数缺失或未知，不继承真实风险默认值')
    p={k:decimal(v) for k,v in params.items()}
    if any(v<0 for v in p.values()) or not 0<p['put_moneyness']<1<p['call_moneyness']:
        raise QuantError('INVALID_OPTION_RULE','期限/报价阈值/价内外比例无效')
    if credit and p['minimum_spread_width']<=0:raise QuantError('INVALID_OPTION_RULE','信用价差最小宽度须显式为正')
    integer={'target_dte','minimum_dte','maximum_dte','exit_days_before_expiry'}
    if any(p[k]!=p[k].to_integral_value() for k in integer) or not p['minimum_dte']<=p['target_dte']<=p['maximum_dte']:
        raise QuantError('INVALID_OPTION_RULE','DTE需为整数并处于最小/最大期限之间')
    if p['exit_days_before_expiry']>=p['minimum_dte'] or p['max_spread_fraction']>1 or p['max_underlying_price_fraction']>1:
        raise QuantError('INVALID_OPTION_RULE','退出日和报价差距阈值无效')
    clock=utc(request['decision_at']);today=clock.astimezone(ZoneInfo('America/New_York')).date()
    contracts,records,metadata,_=store.load(snapshot_id)
    latest={}
    for row in records:
        c=contracts[row['contract_id']]
        if c.underlying!=request['underlying'] or any(utc(row[k])>clock for k in ('exchange_timestamp','available_at','received_at')):
            continue
        if c.contract_id not in latest or utc(row['exchange_timestamp'])>utc(latest[c.contract_id]['exchange_timestamp']):
            latest[c.contract_id]=row
    eligible=[];rejected=[]
    for identity,row in sorted(latest.items()):
        c=contracts[identity];dte=(date.fromisoformat(c.expiry)-today).days
        try:
            issues=quality(row,c,clock,max_age_seconds=float(p['max_age_seconds']),
                max_underlying_skew_seconds=float(p['max_underlying_skew_seconds']),max_spread_fraction=p['max_spread_fraction'])
        except QuantError as exc:issues=[exc.code]
        if not p['minimum_dte']<=dte<=p['maximum_dte']:issues.append('DTE_OUTSIDE_WINDOW')
        if c.settlement!='PHYSICAL':issues.append('UNSUPPORTED_A8_SETTLEMENT')
        if issues:rejected.append({'contract_id':identity,'issues':issues})
        else:eligible.append((c,row,dte))
    template=request['template_id'];chosen=None
    expiries=sorted({c.expiry for c,_,_ in eligible},key=lambda e:(abs((date.fromisoformat(e)-today).days-int(p['target_dte'])),e))
    for expiry in expiries:
        pool=[(c,r) for c,r,_ in eligible if c.expiry==expiry]
        # A straddle must share a strike: two independent ATM selections can
        # otherwise produce a different structure on an asymmetric chain.
        common_strike=None
        if template in {'long_straddle','iron_butterfly'}:
            strikes={c.strike for c,_ in pool if c.right=='CALL'} & {c.strike for c,_ in pool if c.right=='PUT'}
            if not strikes:continue
            def distance(strike):
                values=[abs(strike-decimal(r['underlying_price'])) for c,r in pool if c.strike==strike]
                return sum(values)/len(values)
            common_strike=min(strikes,key=lambda strike:(distance(strike),strike))
        short_leg=None
        def pick(right,rule):
            candidates=[]
            for c,r in pool:
                spot=decimal(r['underlying_price'])
                if c.right!=right:continue
                if rule=='straddle' and c.strike!=common_strike:continue
                if rule=='put_otm' and c.strike>spot*p['put_moneyness']:continue
                if rule=='call_otm' and c.strike<spot*p['call_moneyness']:continue
                if rule=='put_protection' and (short_leg is None or c.strike>short_leg.strike-p['minimum_spread_width']):continue
                if rule=='call_protection' and (short_leg is None or c.strike<short_leg.strike+p['minimum_spread_width']):continue
                distance=abs(c.strike-spot) if rule in {'atm','straddle'} else spot*p['put_moneyness']-c.strike if rule=='put_otm' else c.strike-spot*p['call_moneyness']
                if rule in {'put_protection','call_protection'}:distance=abs(c.strike-short_leg.strike)
                candidates.append((distance,c.strike,c.contract_id,c,r))
            return min(candidates,key=lambda x:x[:3])[3:] if candidates else None
        if credit and not four:
            right='PUT' if template=='bull_put_credit_spread' else 'CALL'
            selected_short=pick(right,'put_otm' if right=='PUT' else 'call_otm')
            if selected_short is None:continue
            short_leg=selected_short[0]
        fixed={}
        if four:
            short_put=pick('PUT','straddle' if template=='iron_butterfly' else 'put_otm')
            short_call=pick('CALL','straddle' if template=='iron_butterfly' else 'call_otm')
            if short_put is None or short_call is None:continue
            if short_put[0].strike>short_call[0].strike or (template=='iron_condor' and short_put[0].strike==short_call[0].strike):continue
            short_leg=short_put[0];long_put=pick('PUT','put_protection')
            short_leg=short_call[0];long_call=pick('CALL','call_protection')
            if template=='iron_butterfly':
                puts={short_put[0].strike-c.strike:(c,r) for c,r in sorted(pool,key=lambda x:x[0].contract_id,reverse=True) if c.right=='PUT' and short_put[0].strike-c.strike>=p['minimum_spread_width']}
                calls={c.strike-short_call[0].strike:(c,r) for c,r in sorted(pool,key=lambda x:x[0].contract_id,reverse=True) if c.right=='CALL' and c.strike-short_call[0].strike>=p['minimum_spread_width']}
                widths=puts.keys() & calls.keys()
                if not widths:continue
                width=min(widths);long_put,long_call=puts[width],calls[width]
            if long_put is None or long_call is None:continue
            fixed={'wing_put':long_put,'wing_call':long_call,'short_put':short_put,'short_call':short_call}
        specs={'iron_condor':[('PUT','wing_put',1),('CALL','wing_call',1),('PUT','short_put',-1),('CALL','short_call',-1)],
               'iron_butterfly':[('PUT','wing_put',1),('CALL','wing_call',1),('PUT','short_put',-1),('CALL','short_call',-1)],
               'long_call':[('CALL','atm',1)],'long_put':[('PUT','atm',1)],
               'protective_put':[('PUT','put_otm',1)],'covered_call':[('CALL','call_otm',-1)],
               'cash_secured_put':[('PUT','put_otm',-1)],'collar':[('PUT','put_otm',1),('CALL','call_otm',-1)],
               'long_straddle':[('CALL','straddle',1),('PUT','straddle',1)],
               'long_strangle':[('PUT','put_otm',1),('CALL','call_otm',1)],
               'bull_put_credit_spread':[('PUT','put_protection',1),('PUT','put_otm',-1)],
               'bear_call_credit_spread':[('CALL','call_protection',1),('CALL','call_otm',-1)],
               'bull_call_debit_spread':[('CALL','atm',1),('CALL','call_otm',-1)],
               'bear_put_debit_spread':[('PUT','atm',1),('PUT','put_otm',-1)]}[template]
        batch=[]
        for right,rule,sign in specs:
            item=fixed.get(rule) if four else pick(right,rule)
            if item is None:break
            c,r=item;r=dict(r)
            # Snapshot rows can contain later published descriptive fields.
            # Freeze only information available at this decision; future OI or
            # last updates must not affect the identity of the chosen signal.
            for value_field,time_field in [('open_interest','open_interest_available_at'),('last','last_timestamp')]:
                if r[time_field] is None or utc(r[time_field])>clock:
                    r[value_field]=None;r[time_field]=None
            batch.append({'contract':c.content(),'contract_version':c.version_hash,
                                  'quantity_per_package':sign,'reference_quote':r,
                                  'reference_price':r['ask'] if sign>0 else r['bid']})
        if len(batch)!=len(specs):continue
        cs=[contracts[b['contract']['contract_id']] for b in batch]
        if len({c.contract_id for c in cs})!=len(cs) or len({c.quote_multiplier for c in cs})!=1:continue
        if len({(c.style,c.settlement,c.currency,c.deliverable_shares) for c in cs})!=1:continue
        if credit:
            net=-sum(decimal(b['reference_price'])*b['quantity_per_package'] for b in batch)
            width=max(cs[2].strike-cs[0].strike,cs[1].strike-cs[3].strike) if four else abs(cs[0].strike-cs[1].strike)
            if not 0<net<width:continue
        if template.endswith('debit_spread'):
            if (template=='bull_call_debit_spread' and cs[0].strike>=cs[1].strike) or (template=='bear_put_debit_spread' and cs[0].strike<=cs[1].strike):continue
            if sum(decimal(b['reference_price'])*b['quantity_per_package'] for b in batch)<=0:continue
        times=[utc(b['reference_quote']['exchange_timestamp']) for b in batch]
        spots=[decimal(b['reference_quote']['underlying_price']) for b in batch]
        if (max(times)-min(times)).total_seconds()>float(p['max_leg_skew_seconds']):continue
        if (max(spots)-min(spots))/min(spots)>p['max_underlying_price_fraction']:continue
        chosen=batch;break
    identity=rule_identity()
    basis={'request':request,'legs':chosen or [],'rule':identity}
    return {'status':'SELECTED_FOR_RESEARCH' if chosen else 'BLOCKED','decision_hash':digest(basis),
            'snapshot_id':snapshot_id,'decision_at':request['decision_at'],'template_id':template,
            'underlying':request['underlying'],'legs':chosen or [],'rejected':rejected,
            'expiry':chosen[0]['contract']['expiry'] if chosen else None,
            'exit_days_before_expiry':int(p['exit_days_before_expiry']),
            'data_type':metadata['data_type'],'executable':False,'source_qualification':'UNVERIFIED',
            **identity,
            'reason':'选约已冻结；不代表来源、担保、资金或账户权限通过' if chosen else '无满足当时期限、行权价和同步报价要求的合约组合'}
