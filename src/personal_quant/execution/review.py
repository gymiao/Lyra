"""Read-only execution differences; every amount is derived from effective facts."""
import csv
from io import StringIO
from ..common import decimal as D, QuantError, utc
from .plans import PlanService
from .context import intent_context


def execution_review(ledger, config, plan_id, as_of):
    plan=PlanService(ledger,config).get(plan_id)
    if utc(as_of)<utc(plan['payload']['as_of']):
        raise QuantError('REVIEW_BEFORE_PLAN','查看时点早于计划')
    events=ledger.active_events(plan['account_id'],as_of)
    lines=[]
    for line in (plan['payload'].get('sizing') or {}).get('lines',[]):
        symbol,side=line['symbol'],line['side']
        reference=D(line['price']);basis_time=utc(plan['payload']['as_of'])
        # Reference price and suggested quantity must be expressed in current units.
        ratio=D(1)
        for event in events:
            if event['kind']=='SPLIT' and event['symbol']==symbol and utc(event['effective_at'])>basis_time:
                ratio*=D(event['ratio'])
        quantity=D(line['quantity'])*ratio;price=reference/ratio
        fills=[]
        for event in events:
            if event['plan_id']!=plan_id or event['kind']!=side or event['symbol']!=symbol:continue
            fill_ratio=D(1)
            for action in events:
                if action['kind']=='SPLIT' and action['symbol']==symbol and utc(action['effective_at'])>utc(event['effective_at']):fill_ratio*=D(action['ratio'])
            fills.append((event,D(event['quantity'])*fill_ratio,D(event['price'])/fill_ratio))
        actual=sum((q for _,q,_ in fills),D(0));fees=sum((D(e['fee']) for e,_,_ in fills),D(0))
        difference=sum((q*(p-price)*(1 if side=='BUY' else -1) for _,q,p in fills),D(0))
        lines.append({'symbol':symbol,'side':side,'suggested_quantity_current_units':str(quantity),
            'actual_quantity_current_units':str(actual),'remaining_quantity':str(max(D(0),quantity-actual)),
            'remaining_executable':plan['execution_status'] not in {'SUPERSEDED','CANCELLED','EXPIRED','FILLED'},
            'estimated_fees':str(line.get('estimated_cost',line.get('fee',line.get('estimated_fee','0')))),
            'reference_price_current_units':str(price),'relative_reference_cost':str(difference),'actual_fill_fees':str(fees),
            'event_ids':[e['event_id'] for e,_,_ in fills],'overfilled':actual>quantity})
    return {'plan_id':plan_id,'intent_id':plan['intent_id'],'revision':plan['revision'],'account_id':plan['account_id'],
        'environment':ledger.environment,'as_of':str(as_of),'reference_as_of':plan['payload']['as_of'],'reference_session':plan['payload']['reference_session'],
        'valid_through_session':intent_context(plan['payload'])['valid_through_session'],'created_at':plan['payload']['created_at'],
        'target_weights':intent_context(plan['payload']).get('target_weights',{}),
        'sizing_explanation':{k:v for k,v in (plan['payload'].get('sizing') or {}).items() if k!='lines'},
        'reconciliation':ledger.connection.execute('SELECT status FROM reconciliations WHERE account_id=? AND as_of<=? ORDER BY id DESC LIMIT 1',(plan['account_id'],str(as_of))).fetchone()[0] if ledger.connection.execute('SELECT 1 FROM reconciliations WHERE account_id=? AND as_of<=?',(plan['account_id'],str(as_of))).fetchone() else 'UNVERIFIED',
        'actual_positions':ledger.snapshot(plan['account_id'],as_of)['positions'],
        'intent_revisions':[dict(r) for r in ledger.connection.execute('SELECT plan_id,revision,execution_status FROM plans WHERE intent_id=? ORDER BY revision',(plan['intent_id'],))],
        'execution_status':plan['execution_status'],'check_status':plan['check_status'],'manual_pending':plan['manual_pending'],
        'unexpected_linked_trade_ids':[e['event_id'] for e in events if e['kind'] in {'BUY','SELL'} and e['plan_id']==plan_id and (e['symbol'],e['kind']) not in {(l['symbol'],l['side']) for l in lines}],
        'lines':lines,'unassociated_trade_ids':[e['event_id'] for e in events if e['kind'] in {'BUY','SELL'} and not e['plan_id']],
        'unallocated_fee_ids':[e['event_id'] for e in events if e['kind']=='FEE'],
        'description':'日线参考价差额；正值为相对成本增加，不等于精确券商滑点。费用另列；仅本修订明确关联成交。'}


def review_csv(result):
    stream=StringIO();fields=['plan_id','revision','environment','reference_as_of','as_of','created_at','reference_session','valid_through_session','execution_status','check_status',
        'symbol','side','suggested_quantity_current_units','actual_quantity_current_units','remaining_quantity',
        'reference_price_current_units','relative_reference_cost','estimated_fees','actual_fill_fees','remaining_executable','overfilled']
    writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
    for line in result['lines']:writer.writerow({k:line.get(k,result.get(k,'')) for k in fields})
    return stream.getvalue()
