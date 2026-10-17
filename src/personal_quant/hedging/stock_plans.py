"""Native stock drafts from frozen hedge quantities, without strategy signals."""
import json
from ..common import QuantError, canonical, digest, decimal as D, now_utc, utc
from ..data.store import DataStore
from ..data.calendar import Calendar
from ..data.quality import price_quality, require_quality
from ..locks import publication_lock
from .allocation_store import resources
from .archive import load
from .intents import records
from .intent_actions import history as closures

PREFIX = 'hedge-stock-draft:'
FIELDS = {'schema_version', 'request_id', 'hedge_id', 'parent_version',
          'expected_resource_hash', 'as_of', 'snapshot_id', 'reason'}
FROZEN = ('purpose', 'hedge_context', 'execution_config', 'execution_config_hash',
          'as_of', 'reference_session', 'reference_snapshot_id', 'execution_session',
          'execution_deadline', 'execution_calendar_hash', 'snapshot', 'sizing')


def prepare(book, config, account_id, request):
    if (not isinstance(request, dict) or set(request) not in (FIELDS,FIELDS|{'exit'})
            or type(request['schema_version']) is not int or request['schema_version'] != 1
            or any(not isinstance(request[k], str) or not request[k].strip()
                   for k in FIELDS - {'schema_version'})):
        raise QuantError('INVALID_HEDGE_STOCK_DRAFT', '需明确父版本、资源、原价快照、生成时点及原因')
    config.validate(); config.require_execution()
    exit=request.get('exit');opening=None
    if exit is not None:
        if (not isinstance(exit,dict) or set(exit)!={'opening_plan_id','execution_session'}
                or any(not isinstance(v,str) or not v for v in exit.values())):
            raise QuantError('INVALID_HEDGE_STOCK_EXIT','退出须原股票计划及明确交易日')
        validate_references(book)
        row=book.connection.execute('SELECT payload,execution_status FROM plans WHERE plan_id=? AND account_id=?',(exit['opening_plan_id'],account_id)).fetchone()
        if row is None:raise QuantError('UNKNOWN_PLAN','退出原计划不属于该账户')
        opening=json.loads(row['payload'])
        if (opening.get('purpose')!='hedge_stage' or opening['hedge_context'].get('action','OPEN')!='OPEN'
                or opening['hedge_context']['parent_version']!=request['parent_version']
                or row['execution_status']!='DRAFT' or opening.get('hedge_activation_task')):
            raise QuantError('HEDGE_STOCK_EXIT_BASIS','先在原OPEN草案/原父下冻结退出，不能补建已执行的反向计划')
        if any(json.loads(r[0]).get('hedge_context',{}).get('opening_plan_id')==exit['opening_plan_id'] for r in book.connection.execute('SELECT payload FROM plans WHERE account_id=?',(account_id,))):
            raise QuantError('DUPLICATE_HEDGE_STOCK_EXIT','原股票计划已有退出草案')
    if book.environment != config.environment:
        raise QuantError('ENVIRONMENT_MISMATCH', '股票对冲配置与账户环境不同')
    chain = [p for p in records(book, account_id) if p['hedge_id'] == request['hedge_id']]
    parent = max(chain, key=lambda p: p['revision']) if chain else None
    if parent is None:
        raise QuantError('UNKNOWN_HEDGE_INTENT', '父对冲意图不存在于该账户')
    if parent['version_hash'] != request['parent_version']:
        raise QuantError('STALE_HEDGE_INTENT_VERSION', '股票草案须最新父版本')
    clock = utc(request['as_of'])
    if (clock > utc(now_utc()) or not utc(parent['decision_at']) <= clock <= utc(parent['valid_until'])
            or any(c['hedge_id'] == parent['hedge_id'] for c in closures(book, account_id))):
        raise QuantError('HEDGE_INTENT_CLOSED', '须未关闭父意图的有效窗口')
    if resources(book, account_id) != request['expected_resource_hash']:
        raise QuantError('STALE_HEDGE_RESOURCES', '股票草案预检资源已变化')
    if parent['ledger_seq'] != book.sequence(account_id):
        raise QuantError('STALE_LEDGER_SEQUENCE', '父冻结后账务已变化，须明确重新决策')
    if parent['candidate']['status'] != 'SELECTED_FOR_RESEARCH':
        raise QuantError('NO_HEDGE_TRADES', '父没有选定交易')
    risk = load(book.path.parent / 'hedging/exposures', parent['exposure_id'])
    if request['snapshot_id'] != risk['valuation_snapshot_id']:
        raise QuantError('HEDGE_PRICE_BASIS_CHANGED', '须父冻结的实际原价快照，新报价需明确重规划')
    store = DataStore(book.path.parent / 'data')
    frame, metadata, calendar = store.load(request['snapshot_id'])
    if book.environment != 'demo':
        from ..data.qualification import require_qualification
        require_qualification(book.connection, book.path.parent, metadata,
                              store.series_identity(metadata), request['as_of'])
        if metadata['data_type'] != 'real_market' or parent['timing'] != 'forward':
            raise QuantError('FORWARD_HEDGE_REQUIRED', '非演示账户须真实来源及前向父意图')
        if clock < utc(parent['generated_at']):
            raise QuantError('LOOKAHEAD_EXECUTION', '前向草案不能早于实际父生成时间')
    reference = calendar.latest_completed(request['as_of'], config.publication_delay_minutes)
    # Future sessions come from the official exchange calendar, never filled prices.
    execution_calendar = Calendar.market(str(reference.date()), exit['execution_session'] if exit else str(utc(parent['valid_until']).date()))
    if execution_calendar.close(reference) != calendar.close(reference):
        raise QuantError('HEDGE_CALENDAR_MISMATCH', '参考收盘与XNYS执行日历不一致')
    eligible = execution_calendar.next(reference)
    if exit:
        from pandas import Timestamp
        eligible=Timestamp(exit['execution_session'])
        settlement=execution_calendar.next(opening['execution_session'],config.settlement_lag_sessions)
        if execution_calendar.close(eligible)<=execution_calendar.close(settlement):
            raise QuantError('HEDGE_STOCK_EXIT_TIME','退出交易日须晚于原OPEN假设结算日')
    elif execution_calendar.close(eligible).to_pydatetime() > utc(parent['valid_until']):
        raise QuantError('HEDGE_INTENT_EXPIRED', '下一交易日已超出原父窗口')
    trades = [t for t in parent['candidate']['trades'] if t.get('kind', 'stock') == 'stock']
    if exit:trades=[dict(symbol=l['symbol'],side='SELL' if l['side']=='BUY' else 'BUY',quantity=l['quantity']) for l in opening['sizing']['lines']]
    if not trades:
        raise QuantError('NO_HEDGE_STOCK_TRADES', '父没有股票建议')
    symbols = {t['symbol'] for t in trades}
    if symbols - set(config.symbols):
        raise QuantError('UNCONFIGURED_HEDGE_SYMBOL', '对冲证券须显式加入执行配置')
    require_quality(price_quality(frame, calendar, config, symbols, reference,
                                  request['as_of'], require_previous=True))
    rows = frame.loc[(frame.session_date == reference) & frame.symbol.isin(symbols)]
    if set(rows.price_basis) != {'unadjusted'} or (rows.split_ratio != 1).any():
        raise QuantError('UNQUALIFIED_EXECUTION_PRICE', '股票草案须原价，单位行动需明确重规划')
    prices = dict(zip(rows.symbol, rows.close))
    positions = {s: D(q) for s, q in risk['account']['positions'].items()}
    lines = []; seen = set(); reserve = D(0); fees = D(0)
    rate = (D(config.commission_bps) + D(config.slippage_bps)) / 10000
    for trade in trades:
        symbol = trade['symbol']; q = D(trade['quantity'])
        side = trade.get('side', 'BUY' if q > 0 else 'SELL'); q = abs(q)
        if symbol in seen or side not in {'BUY', 'SELL'} or q <= 0 or q % D(config.lot_size):
            raise QuantError('INVALID_HEDGE_STOCK_QUANTITY', '每证券一条明确方向/正交易单位数量')
        seen.add(symbol); price = D(prices[symbol])
        if price != D(risk['valuation']['prices'][symbol]):
            raise QuantError('HEDGE_PRICE_BASIS_CHANGED', '当前参考价与父冻结估值不同，须明确重规划')
        fee = q * price * rate + D(config.fixed_fee); fees += fee
        positions[symbol] = positions.get(symbol, D(0)) + q * (1 if side == 'BUY' else -1)
        if positions[symbol] < 0 and not exit:
            raise QuantError('INSUFFICIENT_POSITION', '对冲草案不能生成股票空头')
        if side == 'BUY': reserve += q * price + fee
        lines.append(dict(symbol=symbol, side=side, quantity=str(q), price=str(price), estimated_fee=str(fee)))
    context = dict(schema_version=1, hedge_id=parent['hedge_id'], parent_version=parent['version_hash'],
                   parent_record_hash=parent['record_hash'], eligible_session=str(eligible.date()),
                   valid_through_session=str(utc(parent['valid_until']).date()), reason=request['reason'])
    if exit:context.update(action='CLOSE',opening_plan_id=exit['opening_plan_id'],valid_through_session=str(eligible.date()))
    body = dict(purpose='hedge_stage', hedge_context=context, environment=book.environment,
                as_of=clock.isoformat(), execution_config=config.content(), execution_config_hash=config.hash,
                reference_session=str(reference.date()), reference_snapshot_id=metadata['snapshot_id'],
                execution_session=str(eligible.date()), execution_deadline=execution_calendar.close(eligible).isoformat(),
                execution_calendar_hash=execution_calendar.hash,
                snapshot=risk['account'], sizing=dict(lines=lines, reserve=str(reserve), estimated_fee=str(fees),
                    projected_weights={}, unallocated_buy_targets={}),
                checks=[dict(code='HEDGE_STAGE_ACTIVATION_REQUIRED', message='须绑定执行组并以当前阶段检查激活')],
                intent_status='BLOCKED', no_action=False, creates_reservations=False)
    body['draft_basis_hash'] = digest({k: body[k] for k in FROZEN})
    return body


def save(book, config, account_id, request, *, commit=False):
    with publication_lock(book.path.parent), book.transaction():
        key = PREFIX + digest(dict(account_id=account_id, request_id=request.get('request_id')))
        row = book.connection.execute('SELECT details FROM tasks WHERE task_id=?', (key,)).fetchone()
        if row:
            original = json.loads(row[0])
            if original['request_hash'] != digest(request):
                raise QuantError('HEDGE_STOCK_REQUEST_CONFLICT', '同草案请求ID不能更改条件')
            validate_references(book)
            return original
        body = prepare(book, config, account_id, request)
        plan_id = digest(dict(account_id=account_id, draft_basis_hash=body['draft_basis_hash']))
        if not commit:
            return dict(status='PREVIEW', plan_id=plan_id, payload=body, executable=False, creates_reservations=False)
        if book.connection.execute('SELECT 1 FROM plans WHERE plan_id=?', (plan_id,)).fetchone():
            raise QuantError('HEDGE_STOCK_PLAN_ALREADY_EXISTS', '相同草案已有原请求，不新增归属')
        intent_id='hedge-stock:' + request['parent_version']
        if body['hedge_context'].get('action')=='CLOSE':intent_id+=':CLOSE:'+body['hedge_context']['opening_plan_id']
        body.update(plan_id=plan_id, intent_id=intent_id, revision=1, created_at=now_utc())
        book.connection.execute('INSERT INTO plans VALUES(?,?,?,?,?,?,?,?,?,?)',
            (plan_id, body['intent_id'], 1, account_id, 'DRAFT', 'BLOCKED', canonical(body), '0', '{}', 0))
        result = dict(schema_version=1, status='DRAFT', account_id=account_id, plan_id=plan_id,
                      request=request, request_hash=digest(request), draft_basis_hash=body['draft_basis_hash'],created_at=body['created_at'],
                      executable=False, creates_reservations=False)
        result['record_hash'] = digest(result); book.record_task(key, 'DRAFT', result)
        return result


def validate_references(book):
    for row in book.connection.execute('SELECT task_id,details FROM tasks WHERE task_id LIKE ?', (PREFIX+'%',)):
        try:
            audit = json.loads(row['details']); request = audit['request']
            if (audit['record_hash'] != digest({k:v for k,v in audit.items() if k != 'record_hash'})
                    or audit['request_hash'] != digest(request)
                    or row['task_id'] != PREFIX+digest(dict(account_id=audit['account_id'], request_id=request['request_id']))):
                raise ValueError('audit')
            plan = book.connection.execute('SELECT payload,account_id FROM plans WHERE plan_id=?', (audit['plan_id'],)).fetchone()
            if plan is None or plan['account_id'] != audit['account_id']: raise ValueError('owner')
            body = json.loads(plan['payload'])
            if (body['plan_id']!=audit['plan_id'] or body['created_at']!=audit['created_at']
                    or body['environment']!=book.environment or audit['status']!='DRAFT'
                    or digest(dict(account_id=audit['account_id'],draft_basis_hash=audit['draft_basis_hash']))!=audit['plan_id']):
                raise ValueError('native identity')
            from ..execution.context import intent_context
            context = intent_context(body)
            parent = next(p for p in records(book, audit['account_id']) if p['version_hash'] == context['parent_version'])
            if (parent['record_hash'] != context['parent_record_hash'] or request['parent_version'] != parent['version_hash']
                    or context['hedge_id'] != parent['hedge_id']
                    or digest({k:body[k] for k in FROZEN}) != audit['draft_basis_hash']): raise ValueError('basis')
            expected = {}
            for trade in parent['candidate']['trades']:
                if trade.get('kind','stock') != 'stock': continue
                q = D(trade['quantity']); side = trade.get('side','BUY' if q>0 else 'SELL')
                expected[(trade['symbol'],side)] = abs(q)
            actual = {(line['symbol'],line['side']):D(line['quantity']) for line in body['sizing']['lines']}
            if context.get('action')=='CLOSE':
                exit=request['exit'];opening=book.connection.execute('SELECT payload,account_id FROM plans WHERE plan_id=?',(context['opening_plan_id'],)).fetchone()
                if opening is None or opening['account_id']!=audit['account_id']:raise ValueError('exit owner')
                original=json.loads(opening['payload'])
                if (original.get('purpose')!='hedge_stage' or original['hedge_context'].get('action','OPEN')!='OPEN'
                        or original['hedge_context']['parent_version']!=context['parent_version']
                        or exit!=dict(opening_plan_id=context['opening_plan_id'],execution_session=body['execution_session'])):raise ValueError('exit basis')
                if {(l['symbol'],l['side']):D(l['quantity']) for l in original['sizing']['lines']}!=expected:raise ValueError('opening quantities')
                expected={(symbol,'SELL' if side=='BUY' else 'BUY'):q for (symbol,side),q in expected.items()}
            if len(actual) != len(body['sizing']['lines']) or actual != expected: raise ValueError('quantities')
            risk=load(book.path.parent/'hedging/exposures',parent['exposure_id'])
            from ..config import Config
            config=Config.from_dict(body['execution_config']);config.validate();config.require_execution()
            if config.hash!=body['execution_config_hash'] or body['reference_snapshot_id']!=risk['valuation_snapshot_id']:
                raise ValueError('execution assumptions')
            rate=(D(config.commission_bps)+D(config.slippage_bps))/10000
            for line in body['sizing']['lines']:
                if (D(line['price'])!=D(risk['valuation']['prices'][line['symbol']])
                        or D(line['estimated_fee'])!=D(line['quantity'])*D(line['price'])*rate+D(config.fixed_fee)):
                    raise ValueError('independent price/fee')
            _,_,reference_calendar=DataStore(book.path.parent/'data').load(body['reference_snapshot_id'])
            end=body['execution_session'] if context.get('action')=='CLOSE' else str(utc(parent['valid_until']).date())
            execution_calendar=Calendar.market(body['reference_session'],end)
            if (execution_calendar.hash!=body['execution_calendar_hash']
                    or execution_calendar.close(body['reference_session'])!=reference_calendar.close(body['reference_session'])
                    or execution_calendar.close(body['execution_session']).isoformat()!=body['execution_deadline']):raise ValueError('frozen calendar')
            if context.get('action')=='CLOSE' and execution_calendar.close(body['execution_session'])<=execution_calendar.close(execution_calendar.next(original['execution_session'],config.settlement_lag_sessions)):
                raise ValueError('exit settlement window')
        except (KeyError, ValueError, TypeError, StopIteration) as exc:
            raise QuantError('CORRUPT_HEDGE_STOCK_PLAN', '对冲股票草案或父数量/来源引用改变') from exc
    from .stock_repricing import validate_references as validate_repricing
    validate_repricing(book)
