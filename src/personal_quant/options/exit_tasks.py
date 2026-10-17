"""Frozen demo exits and atomic imports of archived LEAN closing facts."""
import hashlib
import json
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from ..common import QuantError, canonical, decimal as D, digest, now_utc, utc
from ..data.calendar import Calendar
from ..locks import publication_lock
from .contracts import OptionContract
from .data import quality
from .engine import LEAN_COMMIT
from .lifecycle import review
from .management import preview_exit
from .monthly_report import load_monthly_report
from .qualification import assess_engine

FREEZE_FIELDS = {'request_id', 'review', 'execution_at', 'purpose', 'expected_sequence'}
EXECUTE_FIELDS = {'exit_id', 'report_id', 'execution_snapshot_id', 'as_of', 'expected_sequence'}
PURPOSES = {'EXPIRY_MANAGEMENT', 'PROTECTION_WITHDRAWAL', 'OBLIGATION_CLOSE'}


def _freeze_request(request):
    if (not isinstance(request, dict) or set(request) not in (FREEZE_FIELDS,FREEZE_FIELDS|{'hedge_stage_check'})
            or not isinstance(request['request_id'], str) or not request['request_id'].strip()
            or not isinstance(request['review'], dict)
            or not isinstance(request['review'].get('plan_id'), str) or not request['review']['plan_id'].strip()
            or not isinstance(request['purpose'], str) or request['purpose'] not in PURPOSES
            or type(request['expected_sequence']) is not int or request['expected_sequence'] < 0):
        raise QuantError('INVALID_OPTION_EXIT_TASK', '退出冻结需请求ID、完整review、执行时点、明确用途和账户序号')


def resource_basis(book, account_id):
    """Reservations and manual facts can change without a new ledger event."""
    rows = {}
    for table in ('plans', 'option_plans'):
        rows[table] = [dict(row) for row in book.connection.execute(
            f'SELECT * FROM {table} WHERE account_id=? ORDER BY plan_id', (account_id,))]
    return digest(rows)


def _task(book, identity):
    row = book.connection.execute('SELECT details FROM tasks WHERE task_id=?', (identity,)).fetchone()
    return json.loads(row[0]) if row else None


def pending_exits(book, account_id, as_of, ledger_seq=None):
    """Historical commitments; an exit does not duplicate collateral reservations."""
    sequence = book.sequence(account_id) if ledger_seq is None else ledger_seq
    result = []
    for row in book.connection.execute("SELECT details FROM tasks WHERE task_id LIKE 'option-exit-freeze:%'"):
        audit = json.loads(row[0]); proposal = audit['proposal']
        if (proposal['account_id'] != account_id or utc(proposal['as_of']) > utc(as_of)
                or proposal['ledger_seq'] > sequence):
            continue
        ended = False
        for prefix in ('option-exit-simulation:', 'option-exit-cancel:'):
            terminal = _task(book, prefix + proposal['exit_id'])
            if terminal and utc(terminal['effective_at']) <= utc(as_of) and terminal['ledger_seq'] <= sequence:
                ended = True
        if not ended:
            result.append(proposal['exit_id'])
    return sorted(result)


def preview_freeze(book, store, request):
    _freeze_request(request)
    with publication_lock(book.path.parent),book.transaction():
        checked = preview_exit(book, store, request['review'])
        clock = utc(checked['as_of']); execution = utc(request['execution_at'])
        body = review(book, checked['plan_id'], clock)
        if clock > utc(now_utc()):
            raise QuantError('FUTURE_ACCOUNT_EVENT', '不能事前冻结未来尚未产生的退出建议')
        checks = list(checked['checks'])
        from ..hedging.stage_gate import require_for_plan
        stage_check=require_for_plan(book,checked['account_id'],'option',checked['plan_id'],'CLOSE',checked['as_of'],request.get('hedge_stage_check'))
        if checked['status'] != 'CHECKED': checks.append('EXIT_NOT_READY')
        if book.environment != 'demo': checks.append('DEMO_ONLY_EXIT_TASK')
        if book.sequence(checked['account_id']) != request['expected_sequence']: checks.append('STALE_PREVIEW')
        # A new write must honor existing commitments even when a demo request
        # proposes an earlier effective clock. Historical reads remain PIT.
        if pending_exits(book, checked['account_id'], now_utc()): checks.append('PENDING_OPTION_EXIT')
        if request['purpose'] == 'EXPIRY_MANAGEMENT' and request['review']['trigger'] != 'EXPIRY_WINDOW':
            checks.append('EXIT_PURPOSE_MISMATCH')
        if request['purpose'] == 'OBLIGATION_CLOSE' and any(line['side'] != 'BUY' for line in checked['lines']):
            checks.append('PROTECTION_WITHDRAWAL_REQUIRED')
        # Legacy RISK_REDUCTION is a quote-review trigger, not a risk proof.
        contracts = {leg['contract']['contract_id']: OptionContract.from_dict(leg['contract'])
                     for leg in body['selection']['legs']}
        calendar = Calendar.market(str(clock.date()-timedelta(days=7)), str(clock.date()+timedelta(days=10)))
        session = clock.astimezone(ZoneInfo('America/New_York')).date()
        valid_sessions = [day for day in calendar.sessions if day.date() >= session][:2]
        valid_closes = [calendar.close(day).to_pydatetime() for day in valid_sessions]
        if execution not in valid_closes or not clock <= execution-timedelta(minutes=20):
            checks.append('INVALID_EXIT_EXECUTION_WINDOW')
        if any(execution > utc(c.last_trade_at) for c in contracts.values()): checks.append('EXIT_AFTER_LAST_TRADE')
        if not body.get('activation'): checks.append('ACTIVATED_ENGINE_PLAN_REQUIRED')
        proposal = {
            'exit_id': digest({'plan_id': checked['plan_id'], 'request_id': request['request_id']}),
            'plan_id': checked['plan_id'], 'account_id': checked['account_id'], 'environment': book.environment,
            'as_of': checked['as_of'], 'execution_at': execution.isoformat(), 'purpose': request['purpose'],
            'request': request, 'request_hash': digest(request), 'ledger_seq': book.sequence(checked['account_id']),
            'resource_basis': resource_basis(book, checked['account_id']), 'review': checked, 'hedge_stage_check':stage_check,
            'status': 'BLOCKED' if checks else 'CHECKED', 'checks': sorted(set(checks)),
            'executable': False, 'data_type': 'synthetic_historical_demonstration',
            'meaning': '冻结退出建议；不产生券商订单，不提前释放担保；用途不等同于整体风险已下降'}
        proposal['preview_hash'] = digest(proposal)
        return proposal


def freeze_exit(book, store, request, *, expected_hash):
    _freeze_request(request)
    with publication_lock(book.path.parent), book.transaction():
        identity = 'option-exit-freeze:' + digest({'plan_id': request['review']['plan_id'], 'request_id': request['request_id']})
        old = _task(book, identity)
        if old:
            if old['request_hash'] != digest(request): raise QuantError('EVENT_CONFLICT', '同退出请求ID内容冲突')
            from ..hedging.stage_gate import validate_cached
            validate_cached(book,old,'CLOSE',proposal=True)
            return old
        proposal = preview_freeze(book, store, request)
        if proposal['preview_hash'] != expected_hash: raise QuantError('STALE_PREVIEW', '退出预检或资源已变化')
        if proposal['status'] != 'CHECKED': raise QuantError('OPTION_EXIT_BLOCKED', '退出冻结未通过：'+','.join(proposal['checks']))
        audit = {'status': 'FROZEN', 'request': request, 'request_hash': digest(request),
                 'proposal': proposal, 'recorded_at': now_utc()}
        book.record_task(identity, 'SUCCESS', audit)
        return audit


def cancel_exit(book, request):
    fields = {'exit_id', 'as_of', 'expected_sequence', 'reason'}
    if (not isinstance(request, dict) or set(request) != fields or type(request['expected_sequence']) is not int
            or request['expected_sequence'] < 0 or not isinstance(request['exit_id'], str) or not request['exit_id'].strip()
            or not isinstance(request['reason'], str) or not request['reason'].strip()):
        raise QuantError('INVALID_OPTION_EXIT_TASK', '取消需退出ID、实际时点、账户序号及原因')
    clock = utc(request['as_of'])
    with publication_lock(book.path.parent), book.transaction():
        old = _task(book, 'option-exit-cancel:'+request['exit_id'])
        if old:
            if old['request_hash'] != digest(request): raise QuantError('EVENT_CONFLICT', '同取消内容冲突')
            return old
        frozen = _task(book, 'option-exit-freeze:'+request['exit_id'])
        if not frozen: raise QuantError('UNKNOWN_OPTION_EXIT', '退出意图不存在')
        p = frozen['proposal']
        if clock < utc(p['as_of']) or clock > utc(now_utc()): raise QuantError('INVALID_OPTION_EXIT_TASK', '取消时点无效')
        if _task(book, 'option-exit-simulation:'+request['exit_id']): raise QuantError('EXIT_ALREADY_EXECUTED', '已实际模拟平仓的事实不能取消')
        if book.sequence(p['account_id']) != request['expected_sequence']: raise QuantError('STALE_PREVIEW', '账户序号已变化')
        audit = {'status': 'CANCELLED', 'request': request, 'request_hash': digest(request),
                 'effective_at': clock.isoformat(), 'ledger_seq': request['expected_sequence'],
                 'account_id': p['account_id'], 'recorded_at': now_utc(),
                 'meaning': '仅取消未执行demo退出意图，不取消成交事实或释放实际持仓担保'}
        book.record_task('option-exit-cancel:'+request['exit_id'], 'SUCCESS', audit)
        return audit


def execute_exit(book, store, request):
    if (not isinstance(request, dict) or set(request) not in (EXECUTE_FIELDS,EXECUTE_FIELDS|{'hedge_stage_check'},EXECUTE_FIELDS|{'state_as_of'},EXECUTE_FIELDS|{'hedge_stage_check','state_as_of'})
            or type(request['expected_sequence']) is not int or request['expected_sequence'] < 0
            or not isinstance(request['exit_id'], str) or not request['exit_id'].strip()
            or not isinstance(request['execution_snapshot_id'], str) or not request['execution_snapshot_id'].strip()):
        raise QuantError('INVALID_OPTION_EXIT_TASK', '退出模拟需exit_id、报告/报价、处理时点和账户序号')
    name = request['report_id']
    if not isinstance(name, str) or name in {'', '.', '..'} or Path(name).name != name or '/' in name or '\\' in name:
        raise QuantError('INVALID_OPTION_EXIT_TASK', '报告ID必须为工作区内单一目录名')
    clock = utc(request['as_of'])
    if clock > utc(now_utc()): raise QuantError('FUTURE_ACCOUNT_EVENT', '不能处理未来模拟成交')
    identity = 'option-exit-simulation:'+request['exit_id']
    with publication_lock(book.path.parent), book.transaction():
        old = _task(book, identity)
        if old:
            if old['request_hash'] != digest(request): raise QuantError('EVENT_CONFLICT', '同退出意图不能换输入重复成交')
            from ..hedging.stage_gate import validate_cached
            validate_cached(book,old,'CLOSE')
            return old
        frozen = _task(book, 'option-exit-freeze:'+request['exit_id'])
        if not frozen: raise QuantError('UNKNOWN_OPTION_EXIT', '先预检并显式冻结退出')
        p = frozen['proposal']; close = utc(p['execution_at']); account_id = p['account_id']
        if book.environment != 'demo': raise QuantError('FIXTURE_ONLY', '只处理隔离demo成熟引擎退出')
        if _task(book, 'option-exit-cancel:'+request['exit_id']): raise QuantError('OPTION_EXIT_CANCELLED', '退出意图已取消')
        if clock < close: raise QuantError('EXECUTION_NOT_AVAILABLE', '尚未到达冻结退出成交时点')
        state_as_of=request.get('state_as_of')
        if state_as_of is not None and utc(state_as_of)!=close:
            raise QuantError('INVALID_SIMULATION_STATE_TIME','退出重放状态时点必须等于原冻结收盘')
        if clock>close+timedelta(days=1) and request.get('hedge_stage_check') and state_as_of is None:
            raise QuantError('HEDGE_REPLAY_STATE_REQUIRED','迟到组内退出须显式提供原冻结状态时点')
        if book.sequence(account_id) != request['expected_sequence'] or request['expected_sequence'] != p['ledger_seq']:
            raise QuantError('STALE_PREVIEW', '冻结后账户已变化，需取消并重新预检退出')
        if resource_basis(book, account_id) != p['resource_basis']: raise QuantError('STALE_PREVIEW', '冻结后资源或人工状态变化')
        body = review(book, p['plan_id'], clock)
        if body.get('manual_execution', {}).get('pending') or body['progress']['fact_anomalies']:
            raise QuantError('OPTION_EXIT_BLOCKED', '存在在途或未解决实际凭据')
        book.check_reconciliation(account_id, clock, int(D(p['request']['review']['reconciliation_max_days'])))
        from ..hedging.stage_gate import require_for_plan
        stage_check=require_for_plan(book,account_id,'option',p['plan_id'],'CLOSE',request['as_of'],request.get('hedge_stage_check'),state_as_of=state_as_of)
        if state_as_of is not None:
            if stage_check.get('status')!='CHECKED':raise QuantError('UNBOUND_HEDGE_EXECUTION','显式退出重放时钟须已绑定原执行组')
            from ..hedging.archive import load
            risk=load(book.path.parent/'hedging/exposures',stage_check['exposure_id'])
            if risk['request'].get('execution_replay',{}).get('exit_id')!=request['exit_id']:
                raise QuantError('HEDGE_REPLAY_EXIT_MISMATCH','本次阶段风险必须引用确切冻结退出ID')
        if clock>close+timedelta(days=1) and stage_check.get('status')=='CHECKED' and state_as_of is None:
            raise QuantError('HEDGE_REPLAY_STATE_REQUIRED','迟到组内退出须显式提供原冻结状态时点')
        activation = body['activation']
        qualification = assess_engine(book.path.parent/'options/engine-evidence'/activation['engine_evidence_id']/'verification.json', body['selection']['template_id'])
        if qualification['status'] != 'PASSED': raise QuantError('ENGINE_LIFECYCLE_UNQUALIFIED', '退出前引擎资格已变化')
        opening = _task(book, 'option-simulation:'+digest({'plan_id': p['plan_id']}))
        if not opening or opening['request']['report_id'] != name:
            raise QuantError('EXIT_ENGINE_BASIS_REQUIRED', '退出须使用已模拟开仓的同一冻结引擎路径')
        directory = book.path.parent/'options/monthly-research'/name
        report = load_monthly_report(directory)
        if report['data_type'] != 'synthetic_monthly_mechanical' or digest(report) != opening['report_hash']:
            raise QuantError('EXIT_ENGINE_BASIS_REQUIRED', '退出归档与开仓路径不一致')
        engine = directory/body['selection']['template_id']; proof = json.loads((engine/'verification.json').read_text())
        from .adapter_resources import source_hashes
        sources=source_hashes()
        if (sources != proof['adapter_source'] or proof['engine_commit'] != LEAN_COMMIT
                or hashlib.sha256((engine/'bin/LyraX.Options.dll').read_bytes()).hexdigest() != proof['adapter_dll_sha256']):
            raise QuantError('ENGINE_SOURCE_CHANGED', '退出引擎源码/程序集与已验证路径不一致')
        selected = {leg['contract']['contract_id']: OptionContract.from_dict(leg['contract']) for leg in body['selection']['legs']}
        lines = {line['contract_id']: line for line in p['review']['lines']}
        events = [e for e in json.loads((engine/'engine-events.json').read_text())
                  if e['tag'] == activation['monthly_signal_id']+'|CLOSE']
        stock_events = [e for e in events if e['right'] is None]
        events = [e for e in events if e['right'] is not None]
        contracts, quotes, metadata, _ = store.load(request['execution_snapshot_id'])
        if metadata['data_type'] != 'synthetic': raise QuantError('FIXTURE_ONLY', '退出模拟只接受明确合成的执行报价')
        calendar = Calendar.market(str(close.date()), str(close.date()+timedelta(days=40)))
        params = p['request']['review']; rows = []; marks = {}; quantities = {}; completed = set()
        adverse = D(body['request']['risk']['adverse_slippage_fraction'])
        for e in events:
            matches = [c for c in selected.values() if c.right == e['right'] and c.expiry == e['expiry'] and c.strike == D(e['strike'])]
            if len(matches) != 1 or utc(e['utc_time']) != close or e['order_type'] != 'MarketOnClose' or e['fee_currency'] != 'USD':
                raise QuantError('INVALID_ENGINE_FILL', '退出归档成交时点、类型或合约不符')
            c = matches[0]; line = lines.get(c.contract_id); q = abs(D(e['quantity'])); fee = D(e['fee'])
            side = 'BUY' if D(e['quantity']) > 0 else 'SELL'
            if not line or q <= 0 or q != q.to_integral_value() or side != line['side'] or not set(line['depends_on']) <= completed:
                raise QuantError('INVALID_ENGINE_FILL', '退出方向、整张单位或短腿依赖不符')
            quantities[c.contract_id] = quantities.get(c.contract_id, D(0))+q
            if quantities[c.contract_id] > D(line['contracts']) or quantities[c.contract_id] > D(body['lifecycle']['open_contracts'][c.contract_id]):
                raise QuantError('INVALID_ENGINE_FILL', '退出不能超过冻结数量或本计划实际持仓')
            current = [r for r in quotes if r['contract_id'] == c.contract_id and utc(r['exchange_timestamp']) == close
                       and utc(r['available_at']) <= clock and utc(r['received_at']) <= clock]
            if len(current) != 1 or c.contract_id not in contracts or contracts[c.contract_id].version_hash != c.version_hash:
                raise QuantError('MISSING_EXIT_QUOTE', '缺少已到达、单位一致的退出成交报价')
            quote = current[0]; price = D(quote['ask'] if side == 'BUY' else quote['bid']); reference = D(line['reference_price'])
            problems = quality(quote, c, close, knowledge_cutoff=clock, max_age_seconds=float(params['max_age_seconds']),
                               max_underlying_skew_seconds=float(params['max_underlying_skew_seconds']), max_spread_fraction=params['max_spread_fraction'])
            if (problems or price != D(e['price']) or q > D(quote['ask_size'] if side == 'BUY' else quote['bid_size'])
                    or D(quote['underlying_price']) != 100 or fee < 0 or fee > q*D(params['fee_per_contract'])
                    or abs(price/reference-1) > adverse):
                raise QuantError('INVALID_EXIT_QUOTE', '退出报价、费用或偏离冻结价格不合格')
            marks[c.contract_id] = (D(quote['bid'])+D(quote['ask']))/2; marks[c.underlying] = quote['underlying_price']
            rows.append({'event_id': identity+':'+str(e['order_id'])+':'+str(e['event_id']),
                         'kind': 'OPTION_TRADE', 'contract_version': c.version_hash, 'quantity': str(q),
                         'price': str(price), 'fee': str(fee), 'action': 'CLOSE', 'trade_side': side,
                         'effective_at': close.isoformat(), 'settlement_at': calendar.close(calendar.next(close.date())).isoformat(),
                         'plan_id': p['plan_id'], 'source': 'synthetic_monthly_lean', 'evidence_type': 'test'})
            if quantities[c.contract_id] == D(line['contracts']): completed.add(c.contract_id)
        if not rows or set(quantities) != set(lines): raise QuantError('INVALID_ENGINE_FILL', '缺少冻结退出各腿的引擎成交')
        # Each intermediate state is checked, short obligations close first. All
        # writes remain under the outer transaction and roll back as one batch.
        for row in rows:
            book.import_events(account_id, [row])
            intermediate = book.snapshot(account_id, close, marks)
            issues = intermediate['anomalies']
            if issues or intermediate['equity'] is None or D(intermediate['available_cash']) < 0:
                raise QuantError('EXIT_RESOURCE_FAILED', '退出中间状态资源或估值异常，整批回滚')
        result = review(book, p['plan_id'], clock)
        audit = {'status': 'SIMULATED', 'request': request, 'request_hash': digest(request),
                 'effective_at': close.isoformat(), 'ledger_seq': book.sequence(account_id), 'account_id': account_id,
                 'proposal_hash': digest(p), 'hedge_stage_check':stage_check,'report_hash': digest(report), 'engine_events_hash': digest(events),
                 'rows': rows, 'result': result, 'recorded_at': now_utc(), 'delayed_processing': clock > close,
                 'research_underlying_events_not_imported': stock_events,
                 'meaning': '只导入实际期权平仓；研究中的股票平仓不重复导入，个人基础股票继续持有'}
        book.record_task(identity, 'SUCCESS', audit)
        audit['account'] = book.snapshot(account_id, clock, marks)
        book.record_task(identity, 'SUCCESS', audit)
        return audit
