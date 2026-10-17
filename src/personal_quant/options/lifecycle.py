from .catalog import FUNDED_CALL_PROTECTION
"""Derive option plan progress from explicit facts; never submit broker orders."""
import json
from ..common import QuantError, canonical, digest, now_utc, utc, decimal as D


def position_progress(events,expected,as_of):
    """Attribute exits to this plan's own opened contracts, independently of fills."""
    opened={};closed={};issues=[];pending=[];management=[]
    for event in events:
        symbol=event['symbol'];line=expected.get(symbol)
        if line is None or event.get('contract_version')!=line['contract_version']:
            issues.append('成交方向、开平仓或合约与建议不符：'+event['event_id']);continue
        quantity=D(event['quantity']);kind=event['kind']
        is_open=kind=='OPTION_TRADE' and event.get('action')=='OPEN'
        if is_open:
            if event.get('trade_side')!=line['side']:
                issues.append('成交方向、开平仓或合约与建议不符：'+event['event_id']);continue
            opened[symbol]=opened.get(symbol,D(0))+quantity
            if opened[symbol]>D(line['contracts']):issues.append('实际成交超过建议张数：'+symbol)
        else:
            side='LONG' if line['side']=='BUY' else 'SHORT'
            correct=(kind=='OPTION_TRADE' and event.get('action')=='CLOSE'
                     and event.get('trade_side')==('SELL' if line['side']=='BUY' else 'BUY')) or (
                kind in {'OPTION_EXERCISE','OPTION_ASSIGNMENT','OPTION_EXPIRY','OPTION_CASH_SETTLEMENT'}
                and event.get('position_side')==side)
            if not correct:
                issues.append('成交方向、开平仓或合约与建议不符：'+event['event_id']);continue
            if quantity>opened.get(symbol,D(0))-closed.get(symbol,D(0)):
                issues.append('生命周期退出超过本计划持仓：'+event['event_id'])
            closed[symbol]=closed.get(symbol,D(0))+quantity
            management.append(event['event_id'])
        if event.get('settlement_at') is None or utc(event['settlement_at'])>utc(as_of):
            pending.append({'event_id':event['event_id'],'kind':kind,'settlement_at':event.get('settlement_at')})
    positions={symbol:str(opened.get(symbol,D(0))-closed.get(symbol,D(0))) for symbol in expected}
    phase=('CLOSED' if opened and all(D(q)==0 for q in positions.values()) else
           'PARTIAL_CLOSE' if closed else 'OPEN' if opened else 'NOT_OPENED')
    state=phase
    if issues or any(p['settlement_at'] is None for p in pending):state='RECONCILIATION_REQUIRED'
    elif pending:
        kinds={p['kind'] for p in pending}
        state=('ASSIGNMENT_PENDING' if 'OPTION_ASSIGNMENT' in kinds else
               'EXERCISE_PENDING' if 'OPTION_EXERCISE' in kinds else 'SETTLEMENT_PENDING')
    return opened,issues,{'status':state,'position_status':phase,'open_contracts':positions,
        'closed_contracts':{s:str(q) for s,q in closed.items()},'management_events':management,
        'pending_settlements':pending,'as_of':utc(as_of).isoformat()}


def pending_resources(body,quantities):
    """Convert only recorded, still outstanding manual orders into commitments."""
    state=body.get('manual_execution',{});cash=D(0);shares={};remaining={}
    if not state.get('pending'):return cash,shares,remaining
    from .contracts import OptionContract
    contracts={leg['contract']['contract_id']:OptionContract.from_dict(leg['contract']) for leg in body['selection']['legs']}
    for order in state['orders']:
        symbol=order['contract_id'];c=contracts[symbol]
        filled=max(D(0),quantities.get(symbol,D(0))-D(state['filled_basis'].get(symbol,0)))
        q=max(D(0),D(order['contracts'])-filled);remaining[symbol]=str(q)
        if not q:continue
        cash+=q*D(order['fee_per_contract'])
        if order['side']=='BUY':cash+=q*D(order['limit_price'])*c.quote_multiplier
        elif c.right=='PUT':cash+=q*c.exercise_cash
        elif body['selection']['template_id'] in FUNDED_CALL_PROTECTION:
            protection=next(contract for identity,contract in contracts.items()
                            if contract.right=='CALL' and next(leg['quantity_per_package'] for leg in body['selection']['legs'] if leg['contract']['contract_id']==identity)>0)
            cash+=q*protection.exercise_cash
        else:shares[c.underlying]=shares.get(c.underlying,D(0))+q*c.deliverable_shares
    return cash,shares,remaining


def refresh(book,account_id,as_of,*,persist=True,ledger_seq=None):
    events=book.active_events(account_id,as_of,ledger_seq)
    results=[]
    for row in book.connection.execute('SELECT * FROM option_plans WHERE account_id=?',(account_id,)).fetchall():
        body=json.loads(row['payload']);quantities={};issues=[];linked=[]
        activations=[]
        for activation_row in book.connection.execute("SELECT details FROM tasks WHERE task_id LIKE 'option-activation:%'"):
            audit=json.loads(activation_row[0])
            if (audit['status']=='ACTIVATED' and audit['request']['plan_id']==row['plan_id']
                and utc(audit['request']['as_of'])<=utc(as_of)
                and (ledger_seq is None or audit['request']['expected_sequence']<=ledger_seq)):
                activations.append(audit)
        if activations:body=json.loads(canonical(max(activations,key=lambda a:utc(a['request']['as_of']))['result']))
        elif body.get('activation'):body=body['activation']['before']
        audits=[]
        for audit_row in book.connection.execute("SELECT details FROM tasks WHERE task_id LIKE 'option-manual:%'"):
            audit=json.loads(audit_row[0])
            if (audit['request']['plan_id']==row['plan_id'] and utc(audit['request']['as_of'])<=utc(as_of)
                and (ledger_seq is None or audit['request']['expected_sequence']<=ledger_seq)):
                audits.append(audit)
        if audits:
            latest=max(audits,key=lambda a:(utc(a['request']['as_of']),utc(a['recorded_at'])))
            body['manual_execution']=latest['result']['manual_execution']
            body['status']=latest['result']['status']
        elif body.get('manual_execution',{}).get('observed_at') and (ledger_seq is not None or utc(body['manual_execution']['observed_at'])>utc(as_of)):
            body.pop('manual_execution')
            body['status']='DRAFT'
        expected={line['contract_id']:line for line in body['sizing']['lines']}
        plan_events=[event for event in events if event['plan_id']==row['plan_id']]
        linked=[event['event_id'] for event in plan_events]
        quantities,issues,position=position_progress(plan_events,expected,as_of)
        remaining={symbol:str(max(D(0),D(line['contracts'])-quantities.get(symbol,D(0)))) for symbol,line in expected.items()}
        closed=body['status'] in {'CANCELLED','EXPIRED','SUPERSEDED'}
        status=body['status'] if closed else ('FILLED' if expected and all(D(q)==0 for q in remaining.values()) and not issues
                else 'PARTIAL' if linked else 'READY' if body.get('activation') else 'DRAFT')
        # An imported fact does not grant missing permissions or lifecycle qualification.
        body.update(status=status,execution_status=status,executable=False,lifecycle=position,
                    progress={'as_of':utc(as_of).isoformat(),'linked_events':linked,
                              'filled_contracts':{s:str(q) for s,q in quantities.items()},
                              'remaining_contracts':remaining,'fact_anomalies':issues})
        if issues:body['check_status']='BLOCKED'
        if body.get('manual_execution'):
            issues.extend(body['manual_execution'].get('anomalies',[]) if body['manual_execution'].get('pending') else [])
            cash,shares,pending=pending_resources(body,quantities)
            body['manual_execution']['remaining_orders']=pending
            body['manual_execution']['reserved_cash']=str(cash)
            body['manual_execution']['reserved_positions']={s:str(q) for s,q in shares.items()}
            if issues:body['check_status']='BLOCKED'
        if body.get('activation'):
            from .plans import unfilled_resources
            resources=unfilled_resources(body,quantities)
            changes=[e for e in events if e['seq']>body['activation']['basis_sequence'] and e['plan_id']!=row['plan_id']]
            if position['status']=='CLOSED' and not body.get('manual_execution',{}).get('pending'):
                # A settled, retired intent cannot treat every later monthly
                # fill as an unexplained change to its old opening authority.
                # Retain changes while it still had exposure or settlement risk.
                last_fact=max(plan_events,key=lambda e:(utc(e['effective_at']),e['seq']))
                closed_at=max(max(utc(e['effective_at']),utc(e['settlement_at'])) for e in plan_events)
                changes=[e for e in changes if utc(e['effective_at'])<closed_at or
                         (utc(e['effective_at'])==closed_at==utc(last_fact['effective_at']) and e['seq']<last_fact['seq'])]
            if changes:
                body['check_status']='BLOCKED'
                issues.append('激活后账户发生未关联变化，需重新核对')
            expired=utc(as_of)>utc(body['activation']['valid_until'])
            if expired:body['check_status']='BLOCKED'
            pending_manual=body.get('manual_execution',{}).get('pending')
            # Keep evidence of a capital change even if a later correction reverses
            # its accounting effect. A correction must not reopen an old intent.
            capital_rows=book.connection.execute('SELECT payload FROM events WHERE account_id=? AND effective_at<=? AND seq>? AND seq<=? ORDER BY effective_at,seq',
                (account_id,utc(as_of).isoformat(),body['activation']['basis_sequence'],
                 book.sequence(account_id) if ledger_seq is None else ledger_seq)).fetchall()
            capital=[json.loads(r[0]) for r in capital_rows]
            capital=[e for e in capital if e['kind'] in {'DEPOSIT','WITHDRAWAL'}]
            if capital:
                body['check_status']='BLOCKED'
                body['intent_closure']={'reason':'EXTERNAL_CAPITAL_CHANGED',
                    'triggered_at':capital[0]['effective_at'],'event_ids':[e['event_id'] for e in capital],
                    'status':'WAITING_MANUAL_CONFIRMATION' if pending_manual else 'CLOSED',
                    'message':'关闭未提交部分；保留成交及在途订单，等待下一个月末新信号'}
                if not pending_manual and status!='FILLED' and not closed:
                    status=body['status']=body['execution_status']='CANCELLED';closed=True
                elif pending_manual:
                    # Only actual outstanding manual orders survive this intent.
                    # The unsubmitted remainder cannot use newly arrived capital.
                    resources={'reserved_cash':body['manual_execution']['reserved_cash'],
                        'reserved_positions':dict(body['manual_execution']['reserved_positions']),
                        'remaining_contracts':remaining}
            if expired and status!='FILLED' and not closed and not pending_manual:
                status=body['status']=body['execution_status']='EXPIRED'
            baseline=book.connection.execute("SELECT status FROM reconciliations WHERE account_id=? AND as_of<=? ORDER BY id DESC LIMIT 1",
                (account_id,utc(as_of).isoformat())).fetchone()
            if not baseline or baseline['status']!='PASSED':
                body['check_status']='BLOCKED';issues.append('账户对账未通过')
            for pending_row in book.connection.execute('SELECT payload FROM pending_option_events WHERE account_id=?',(account_id,)):
                pending_event=json.loads(pending_row[0])
                if not pending_event.get('effective_at') or utc(pending_event['effective_at'])<=utc(as_of):
                    body['check_status']='BLOCKED';issues.append('存在未核实期权凭据');break
            if (closed or status=='FILLED' or expired) and not body.get('manual_execution',{}).get('pending'):
                resources={'reserved_cash':'0','reserved_positions':{},'remaining_contracts':remaining}
            if body.get('manual_execution',{}).get('pending'):
                resources['reserved_cash']=str(max(D(resources['reserved_cash']),D(body['manual_execution']['reserved_cash'])))
                for symbol,q in body['manual_execution']['reserved_positions'].items():
                    resources['reserved_positions'][symbol]=str(max(D(resources['reserved_positions'].get(symbol,0)),D(q)))
            body['active_reservation']=resources
            body['executable']=status in {'READY','PARTIAL'} and body['check_status']=='PASSED' and not expired and not issues and not body.get('manual_execution',{}).get('pending')
        results.append(body)
        if persist:
            if body.get('active_reservation'):
                resource=body['active_reservation']
                book.connection.execute('UPDATE option_plans SET status=?,payload=?,reserved_cash=?,reserved_positions=? WHERE plan_id=?',
                    (status,canonical(body),resource['reserved_cash'],canonical(resource['reserved_positions']),row['plan_id']))
            elif body.get('manual_execution'):
                book.connection.execute('UPDATE option_plans SET status=?,payload=?,reserved_cash=?,reserved_positions=? WHERE plan_id=?',
                    (status,canonical(body),str(cash),canonical({s:str(q) for s,q in shares.items()}),row['plan_id']))
            else:
                book.connection.execute('UPDATE option_plans SET status=?,payload=? WHERE plan_id=?',
                                        (status,canonical(body),row['plan_id']))
    return results


def review(book,plan_id,as_of):
    row=book.connection.execute('SELECT account_id FROM option_plans WHERE plan_id=?',(plan_id,)).fetchone()
    if not row:raise QuantError('UNKNOWN_OPTION_PLAN','期权计划不存在')
    with book.transaction():
        body=next(body for body in refresh(book,row[0],as_of,persist=False) if body['plan_id']==plan_id)
        if body.get('request',{}).get('risk'):
            from .plans import unfilled_resources
            body['reservation_preview']={**unfilled_resources(body,body['progress']['filled_contracts']),
                'applied':False,'reason':'未成交预算预览；不授予READY，不改变实际预留或担保'}
        return body


def resolve_pending(book,account_id,event_id,*,expected_sequence,expected_hash):
    """Retry the original receipt after missing terms/relationship are supplied.

    Preserve the original receipt and resolution in a durable audit record.
    Corrections to unsupported facts require a separate future correction workflow.
    """
    identity=digest({'account_id':account_id,'event_id':event_id,'receipt_hash':expected_hash})
    task_id='option-resolution:'+identity
    from ..locks import publication_lock
    with publication_lock(book.path.parent),book.transaction():
        previous=book.connection.execute('SELECT details FROM tasks WHERE task_id=?',(task_id,)).fetchone()
        if previous:
            audit=json.loads(previous[0])
            if 'risk_history' in audit:
                from .receipt_risk import validate
                validate(book,account_id,audit['risk_history'])
            return audit
        row=book.connection.execute('SELECT * FROM pending_option_events WHERE account_id=? AND event_id=?',(account_id,event_id)).fetchone()
        if not row:raise QuantError('UNKNOWN_OPTION_RECEIPT','待核实凭据不存在')
        raw=json.loads(row['payload'])
        if digest(raw)!=expected_hash:raise QuantError('STALE_PREVIEW','待核实凭据发生变化')
        before=book.sequence(account_id)
        result=book.import_events(account_id,[raw],expected_sequence)
        book.connection.execute('DELETE FROM pending_option_events WHERE account_id=? AND event_id=?',(account_id,event_id))
        from .receipt_risk import capture
        audit={'status':'RESOLVED','account_id':account_id,'event_id':event_id,'receipt':raw,
               'audit_task_id':task_id,'risk_history':capture(book,account_id,before,now_utc()),
               'original_reason':row['reason'],'receipt_hash':expected_hash,'resolved_at':now_utc(),'import':result}
        book.record_task(task_id,'SUCCESS',audit)
        for other in book.connection.execute("SELECT plan_id,payload FROM plans WHERE account_id=? AND (execution_status IN ('READY','PARTIAL') OR manual_pending=1)",(row['account_id'],)).fetchall():
            payload=json.loads(other['payload'])
            payload.setdefault('checks',[]).append({'code':'OPTION_MANUAL_RESOURCE_CHANGED','message':'人工期权订单占用变化，须重新检查ETF计划；保留在途资源'})
            book.connection.execute("UPDATE plans SET check_status='BLOCKED',payload=? WHERE plan_id=?",(canonical(payload),other['plan_id']))
        return audit


def manual_action(book,request):
    """Record an existing manual order or its confirmed end; grant no trading permission."""
    required={'request_id','plan_id','action','as_of','expected_sequence','reason','orders'}
    if book.connection.execute('SELECT version FROM schema_version').fetchone()[0]<5:
        raise QuantError('V19_NOT_ENABLED','人工期权事实需要显式启用v1.9')
    if set(request)!=required or request['action'] not in {'record-submitted','confirm-ended','cancel'}:
        raise QuantError('INVALID_MANUAL_FACT','须明确请求ID、计划、动作、时点、账户序号、理由和订单')
    if not request['request_id'] or not isinstance(request['reason'],str) or not request['reason'].strip():
        raise QuantError('INVALID_MANUAL_FACT','人工执行事实必须提供稳定请求ID和核实理由')
    clock=utc(request['as_of'])
    if book.environment!='demo' and clock>utc(now_utc()):raise QuantError('FUTURE_ACCOUNT_EVENT','不能记录尚未发生的人工执行事实')
    task_id='option-manual:'+digest({'plan_id':request['plan_id'],'request_id':request['request_id']})
    with book.transaction():
        previous=book.connection.execute('SELECT details FROM tasks WHERE task_id=?',(task_id,)).fetchone()
        if previous:
            audit=json.loads(previous[0])
            if audit['request_hash']!=digest(request):raise QuantError('EVENT_CONFLICT','同一人工执行请求ID内容冲突')
            return audit
        row=book.connection.execute('SELECT * FROM option_plans WHERE plan_id=?',(request['plan_id'],)).fetchone()
        if not row:raise QuantError('UNKNOWN_OPTION_PLAN','期权计划不存在')
        if book.sequence(row['account_id'])!=request['expected_sequence']:raise QuantError('STALE_PREVIEW','账户已变化，须核实人工订单')
        body=review(book,request['plan_id'],clock)
        existing=body.get('manual_execution',{})
        if existing.get('observed_at') and clock<utc(existing['observed_at']):raise QuantError('INVALID_MANUAL_FACT','迟到人工通知需要更正流程，不能倒写当前状态')
        if request['action']=='record-submitted':
            if existing.get('pending'):raise QuantError('PENDING_MANUAL_ORDER','已有人工订单未确认结束，不能覆盖其占用')
            if not isinstance(request['orders'],list) or not request['orders']:raise QuantError('INVALID_MANUAL_FACT','需逐腿记录已提交订单')
            lines={line['contract_id']:line for line in body['sizing']['lines']};orders=[];seen=set()
            for order in request['orders']:
                if set(order)!={'contract_id','side','contracts','limit_price','fee_per_contract'}:
                    raise QuantError('INVALID_MANUAL_FACT','订单需明确合约、方向、正整张数、参考限价及费用预留')
                symbol=order['contract_id'];q=D(order['contracts']);price=D(order['limit_price']);fee=D(order['fee_per_contract'])
                if symbol not in lines or symbol in seen or order['side']!=lines[symbol]['side'] or q<=0 or q!=q.to_integral_value() or price<=0 or fee<0:
                    raise QuantError('INVALID_MANUAL_FACT','订单身份、单位、方向或费用无效；计划外订单需独立核实')
                seen.add(symbol);orders.append({**order,'contracts':str(q),'limit_price':str(price),'fee_per_contract':str(fee)})
            body['manual_execution']={'pending':True,'observed_at':clock.isoformat(),'orders':orders,
                'filled_basis':body['progress']['filled_contracts'],'reason':request['reason'],
                'anomalies':['人工在途订单超过建议剩余张数：'+order['contract_id'] for order in orders
                    if D(order['contracts'])>D(body['progress']['remaining_contracts'][order['contract_id']])]}
        else:
            if request['orders']:raise QuantError('INVALID_MANUAL_FACT','结束或取消动作不应带新订单')
            if request['action']=='cancel' and existing.get('pending'):
                raise QuantError('PENDING_MANUAL_ORDER','先确认人工订单结束；本地取消不代表券商撤单')
            if request['action']=='cancel' and body['status']=='FILLED':
                raise QuantError('PLAN_ALREADY_FILLED','全部已成交的计划不能取消其事实')
            if request['action']=='cancel':body['status']=body['execution_status']='CANCELLED'
            body['manual_execution']={**existing,'pending':False,'observed_at':clock.isoformat(),'reason':request['reason']}
        cash,shares,pending=pending_resources(body,{s:D(q) for s,q in body['progress']['filled_contracts'].items()})
        body['manual_execution'].update(reserved_cash=str(cash),reserved_positions={s:str(q) for s,q in shares.items()},remaining_orders=pending)
        body['executable']=False
        book.connection.execute('UPDATE option_plans SET status=?,payload=?,reserved_cash=?,reserved_positions=? WHERE plan_id=?',
            (body['status'],canonical(body),str(cash),canonical({s:str(q) for s,q in shares.items()}),request['plan_id']))
        audit={'status':'RECORDED','request':request,'request_hash':digest(request),'result':body,'recorded_at':now_utc(),
               'meaning':'记录已发生的人工订单事实，不授予执行资格或向券商提交/撤销订单'}
        book.record_task(task_id,'SUCCESS',audit)
        for other in book.connection.execute("SELECT plan_id,payload FROM plans WHERE account_id=? AND (execution_status IN ('READY','PARTIAL') OR manual_pending=1)",(row['account_id'],)).fetchall():
            payload=json.loads(other['payload'])
            payload.setdefault('checks',[]).append({'code':'OPTION_MANUAL_RESOURCE_CHANGED','message':'人工期权订单占用变化，须重新检查ETF计划；保留在途资源'})
            book.connection.execute("UPDATE plans SET check_status='BLOCKED',payload=? WHERE plan_id=?",(canonical(payload),other['plan_id']))
        return audit
