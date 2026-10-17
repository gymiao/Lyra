"""Archived LEAN experiment contracts, financial facts and cost explanations."""
import hashlib
import json
from pathlib import Path
from ..common import QuantError,decimal as D,digest,utc
from ..portfolio import Ledger
from ..options.monthly_report import metrics_for
from .portable_tools import archived as archived_tools
from .source_archive import require as require_source


def within(root,relative):
    path=Path(relative)
    if path.is_absolute() or '..' in path.parts or '\\' in str(path):
        raise QuantError('CORRUPT_EXPERIMENT','实验引用不能跨出归档目录')
    target=root/path
    if target.is_symlink() or not target.resolve().is_relative_to(root.resolve()):
        raise QuantError('CORRUPT_EXPERIMENT','实验引用不能通过链接跨出归档目录')
    return target


def verify_raw(events,expected):
    def fee_currency(event):
        # LEAN OrderFee.Zero uses its internal QCC account-currency marker.
        # It conveys no FX conversion when the amount is exactly zero.
        return event['fee_currency']=='USD' or (event['order_type']=='OptionExercise'
            and D(event['fee'])==0 and event['fee_currency']=='QCC')
    # Physical delivery creates a second underlying event. Its cash/units are
    # already represented by the normalized option lifecycle fact.
    rows=[e for e in events if not (e['order_type']=='OptionExercise' and e['symbol']!=e['order_symbol'])]
    mapping={str(e['order_id'])+':'+str(e['event_id']):e for e in rows}
    if len(mapping)!=len(rows) or set(mapping)!={e['event_id'] for e in expected}:
        raise QuantError('CORRUPT_EXPERIMENT','原生费用凭据与桥接事实缺失或重复')
    for row in expected:
        e=mapping[row['event_id']]
        if (utc(e['utc_time'])!=utc(row['effective_at']) or abs(D(e['quantity']))!=D(row['quantity'])
                or D(e['price'])!=D(row['price']) or D(e['fee'])!=D(row['fee']) or not fee_currency(e)):
            raise QuantError('CORRUPT_EXPERIMENT','原生费用凭据的单位/金额/时点与桥接事实不同')
        if row['kind'] in {'BUY','SELL'}:
            valid=e['right'] is None and e['symbol']==row['symbol'] and row['kind']==('BUY' if D(e['quantity'])>0 else 'SELL')
        else:
            c=row['contract']
            valid=(e['right']==c['right'] and e['expiry']==c['expiry'] and e['underlying']==c['underlying'] and D(e['strike'])==D(c['strike']))
            if row['kind']=='OPTION_TRADE':
                action=e['tag'].split('|')[-1]
                valid=valid and row['trade_side']==('BUY' if D(e['quantity'])>0 else 'SELL') and row['action']==('CLOSE' if action=='CLOSE_DELIVERY_RISK' else action)
            else:
                kind='OPTION_EXPIRY' if not e['in_the_money'] else 'OPTION_ASSIGNMENT' if e['assignment'] else 'OPTION_EXERCISE'
                valid=valid and e['order_type']=='OptionExercise' and row['kind']==kind
                valid=valid and (D(e['quantity'])<0)==(row['position_side']=='LONG')
                deliveries=[child for child in events if child['order_type']=='OptionExercise'
                    and child['order_id']==e['order_id'] and child['symbol']!=child['order_symbol']]
                quantity=(D(0) if kind=='OPTION_EXPIRY' else D(row['quantity'])*D(c['deliverable_shares'])
                    *(1 if c['right']=='CALL' else -1)*(1 if row['position_side']=='LONG' else -1))
                if quantity==0:valid=valid and not deliveries
                elif len(deliveries)!=1:valid=False
                else:
                    child=deliveries[0]
                    valid=valid and (child['symbol']==c['underlying'] and child['order_symbol']==e['symbol']
                        and utc(child['utc_time'])==utc(e['utc_time']) and D(child['quantity'])==quantity
                        and D(child['price'])==D(c['strike']) and D(child['fee'])==0 and fee_currency(child))
        if not valid:raise QuantError('CORRUPT_EXPERIMENT','原生费用凭据的证券/方向/生命周期与桥接事实不同')
    parents={e['order_id'] for e in rows if e['order_type']=='OptionExercise'}
    if any(e['order_id'] not in parents for e in events if e['order_type']=='OptionExercise' and e['symbol']!=e['order_symbol']):
        raise QuantError('CORRUPT_EXPERIMENT','实物交割缺少对应期权生命周期事实')


def describe(book,runtime,identity,config,run,rows,curve):
    directory=runtime/'simulation/options'/run['run_id']
    settings=json.loads((directory/'settings.json').read_text());request=json.loads((directory/'request.json').read_text())
    if (digest(request)!=settings['request_hash'] or settings['source_hash']!=run['source_hash']
            or digest({'workspace':identity['workspace_id'],'settings':settings})!=run['run_id']):
        raise QuantError('CORRUPT_EXPERIMENT','冻结期权请求/设置与原运行不同')
    if not settings.get('tool_identity_hash'):
        raise QuantError('UNVERIFIED_EXPERIMENT','旧期权运行缺少外部引擎内容绑定，可查看原报告但不能用于此严格比较')
    _,tools=archived_tools(book,directory,run['run_id'])
    if tools['content_hash']!=settings['tool_identity_hash']:
        raise QuantError('CORRUPT_EXPERIMENT','工具清单与原运行不同')
    require_source(book,runtime,run['run_id'],run['source_hash'],check_environment=False)
    if 'plan_policy' in request:
        policy=json.loads((directory/'plan-policy.json').read_text())
        if digest(policy)!=settings.get('plan_policy_hash') or policy['request_hash']!=digest(request['plan_policy']):
            raise QuantError('CORRUPT_EXPERIMENT','冻结计划政策改变')
    details=[json.loads(row['details']) for row in rows]
    reference=next((d['native_proof'] for d in reversed(details) if d.get('native_proof')),None)
    if reference is None:raise QuantError('UNVERIFIED_EXPERIMENT','缺少实际原生归档依据')
    native=within(runtime,reference)
    if native.parent!=directory:raise QuantError('CORRUPT_EXPERIMENT','原生前缀不属于该运行')
    proof=json.loads((native/'verification.json').read_text())
    if (proof.get('status')!='PASSED' or proof.get('engine_commit')!=tools['lean_commit']
            or abs(D(proof['actual_equity'])-D(str(curve.iloc[-1])))>D('.01')
            or abs(D(proof['ledger_bridge']['equity'])-D(str(curve.iloc[-1])))>D('.01')):
        raise QuantError('CORRUPT_EXPERIMENT','原生终值与账户曲线或固定引擎不一致')
    for name,expected in proof['adapter_source'].items():
        source=within(native/'source',name)
        if hashlib.sha256(source.read_bytes()).hexdigest()!=expected:
            raise QuantError('CORRUPT_EXPERIMENT','原生适配源码改变')
    if hashlib.sha256((native/'bin/LyraX.Options.dll').read_bytes()).hexdigest()!=proof['adapter_dll_sha256']:
        raise QuantError('CORRUPT_EXPERIMENT','原生适配程序集改变')
    actual=[e for e in book.active_events(identity['account_id'],details[-1]['as_of']) if e['kind']!='DEPOSIT']
    bridge=Ledger.read_only(native/'bridge.sqlite','demo')
    try:
        expected=[e for e in bridge.active_events('monthly-bridge',details[-1]['as_of']) if e['kind']!='DEPOSIT']
    finally:bridge.close()
    ignored={'seq','account_id','plan_id'}
    comparable=lambda events:[{k:v for k,v in event.items() if k not in ignored} for event in events]
    if comparable(actual)!=comparable(expected):
        raise QuantError('CORRUPT_EXPERIMENT','实际账户事实与已验证原生桥不同，不能解释为该策略表现')
    events=json.loads((native/'engine-events.json').read_text())
    verify_raw(events,expected)
    summary=metrics_for(curve,events,request['signals'],annual_factor=config.volatility_annual_factor,execution_path=request['execution_path'])
    if (abs(D(str(summary['net_trading_pnl']))-D(str(curve.iloc[-1]-curve.iloc[0])))>D('.01')
            or abs(D(str(summary['commission']))-sum((D(e['fee']) for e in actual),D(0)))>D('.01')):
        raise QuantError('CORRUPT_EXPERIMENT','原生成交费用/盈亏分解与账户资金不一致')
    frozen=book.connection.execute('SELECT details FROM tasks WHERE task_id=?',('simulation-source:'+run['run_id'],)).fetchone()
    policy={'engine':'LEAN','engine_commit':tools['lean_commit'],'tool_identity_hash':tools['content_hash'],
        'adapter_source':proof['adapter_source'],'environment':json.loads(frozen[0])['environment'],
        'initial_cash':identity['initial_cash'],'currency':config.currency,'market':config.market,'cash_interest':0,
        'source_hash':run['source_hash'],'data_type':'synthetic','execution_path_hash':digest(request['execution_path']),
        'snapshots':sorted({s['input']['snapshot_id'] for s in request['signals']}),
        'decision_times':[s['decision_at'] for s in request['signals']],
        'option_fee_per_contract':settings['fee_per_contract'],'stock_commission_bps':config.commission_bps,
        'stock_slippage_bps':0,'settlement_assumption':'next_market_session_close','stock_unit':1,
        'final_lifecycle':request.get('final_lifecycle'),'retain_stock':request.get('retain_stock',False),
        'prepare_stock':request.get('prepare_stock',False),'wheel':request.get('wheel',False),
        'as_of':[d['as_of'] for d in details],'dates':[str(day.date()) for day in curve.index],
        'volatility_annual_factor':config.volatility_annual_factor}
    summary['meaning']='价差已包含在原生成交及净值中；bid_ask_cost仅解释，不再次扣除。现金利息0，物理交割单列。'
    return policy,summary
