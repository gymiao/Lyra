"""Local daily workflow using the existing data, ledger, plan and report services."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta
import fcntl
import json
import os
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from ..common import QuantError, canonical, digest, now_utc, utc
from ..locks import publication_lock
from ..data.quotes import quote_set
from ..data.quality import price_quality
from ..data.update import update_online
from ..portfolio.reconciliation import ReconciliationRules
from ..portfolio.report import report_from_store
from ..strategies import Signal, decode_signal
from ..strategies.archive import SignalArchive, source_fingerprint
from .corporate import apply_actions, normalize_actions
from .plans import PlanService
from .simulator import simulate


@contextmanager
def daily_lock(path):
    """Keep the inode; the OS releases the advisory lock when the process exits."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise QuantError("DAILY_ALREADY_RUNNING", "已有日常任务运行，稍后查询结果；不会按超时强行释放锁") from exc
        try:
            handle.seek(0)
            handle.truncate()
            handle.write(canonical({"pid": os.getpid(), "started_at": now_utc()}))
            handle.flush()
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class DailyRunner:
    def __init__(self, ledger, config, store, *, after_step=None):
        self.ledger, self.config, self.store = ledger, config, store
        self.base_config = config
        self.after_step = after_step  # Test fault injection at a committed boundary.

    def _step(self, name, inputs, function, *, transactional=False, reuse=True):
        if not reuse:
            inputs = {"inputs": inputs, "attempt_id": self.attempt_id}
        input_hash = digest(inputs)
        step_id = digest({"run": self.run_id, "name": name, "input": input_hash})
        existing = self.ledger.connection.execute("SELECT output FROM daily_steps WHERE step_id=?", (step_id,)).fetchone()
        if existing is not None:
            self.trace.append({"name": name, "step_id": step_id, "input_hash": input_hash, "reused": True})
            return json.loads(existing[0])
        def commit(result):
            result = json.loads(canonical(result))
            self.ledger.connection.execute("INSERT INTO daily_steps VALUES(?,?,?,?,?,?,?)",
                (step_id, self.run_id, name, input_hash, "COMMITTED", canonical(result), now_utc()))
            return result
        if transactional:
            with publication_lock(self.ledger.path.parent),self.ledger.transaction():
                result = commit(function())
        else:
            result = function()  # No database transaction around downloads or report files.
            with self.ledger.transaction():
                result = commit(result)
        self.trace.append({"name": name, "step_id": step_id, "input_hash": input_hash, "reused": False})
        if self.after_step:
            self.after_step(name, result)
        return result

    def run(self, account_id, *, as_of=None, fetch_range=None, events=None, expected_sequence=None,
            expected_hash=None, coverage_through=None, coverage_source=None, actions=None, reconciliation=None,
            option_valuation=None, option_tasks=None, option_receipts=None, option_resolutions=None,hedge_stage_checks=None,
            simulation_check=False):
        if type(simulation_check) is not bool:
            raise QuantError('INVALID_SIMULATION_CHECK','模拟自检必须是明确布尔值')
        if simulation_check and self.config.environment!='demo':
            raise QuantError('DEMO_SELF_CHECK_ONLY','历史模拟自检只能用于明确demo，不能替代券商凭据')
        self.simulation_check=simulation_check
        if self.config.environment != self.ledger.environment:
            raise QuantError("ENVIRONMENT_MISMATCH", "日常任务配置与账户环境不同")
        if as_of is not None and self.config.environment != "demo":
            raise QuantError("HISTORICAL_TIME_FORBIDDEN", "真实/前向日常任务不能使用手工历史时钟")
        if self.config.environment == "real" and actions:
            raise QuantError("REAL_SIMULATION_FORBIDDEN", "真实日常任务不能接受模拟公司行动")
        self.ledger._require_account(account_id)
        self.account_id = account_id
        if option_valuation is not None and (not isinstance(option_valuation,dict) or set(option_valuation)!={'snapshot_id','limits'}):
            raise QuantError('INVALID_OPTION_VALUATION','日常期权估值需snapshot_id及limits')
        if hedge_stage_checks is not None and (not isinstance(hedge_stage_checks,dict) or any(
                not isinstance(k,str) or not k or not isinstance(v,dict) for k,v in hedge_stage_checks.items())):
            raise QuantError('INVALID_HEDGE_STAGE_CHECKS','日常股票阶段请求须为plan_id到完整请求的映射')
        self.hedge_stage_checks=hedge_stage_checks or {}
        self.option_valuation=option_valuation
        if option_tasks is not None and (not isinstance(option_tasks,list) or any(
                not isinstance(item,dict) or set(item)!={'kind','request'}
                or not isinstance(item['kind'],str) or item['kind'] not in {'OPEN','CLOSE'} or not isinstance(item['request'],dict)
                for item in option_tasks)):
            raise QuantError('INVALID_OPTION_DAILY_TASKS','期权日常任务需明确OPEN/CLOSE及完整冻结请求数组')
        if option_tasks and self.config.environment!='demo':
            raise QuantError('REAL_SIMULATION_FORBIDDEN','成熟引擎历史模拟任务只用于隔离demo')
        self.option_tasks=option_tasks or []
        self.option_receipts=option_receipts
        self.option_resolutions=option_resolutions
        self.fixed_clock = as_of is not None
        self.instant = utc(as_of or now_utc()).isoformat()
        self.config = self.base_config
        # Data/valuation gates use this month's frozen basket and publication policy.
        # Pending bindings are selected by effective session; they are only activated
        # by the monthly transaction. Existing fills still use their own frozen plan.
        if self.ledger.connection.execute("SELECT version FROM schema_version").fetchone()[0] >= 3 and self.ledger.connection.execute(
                "SELECT 1 FROM strategy_bindings WHERE account_id=?", (account_id,)).fetchone() and (self.store.root / "latest.json").exists():
            from ..strategies.bindings import BindingService
            from ..strategies.adapter import resolve
            _, _, binding_calendar = self.store.load_role("signal")
            latest_close = binding_calendar.latest_completed(self.instant, 0)
            bindings = BindingService(self.ledger, self.base_config)
            try:
                selected = bindings.selected(account_id, latest_close)
            except QuantError as exc:
                if exc.code != "NO_ACCOUNT_BINDING":
                    raise
            else:
                spec = bindings.strategies.get(selected["strategy_id"], selected["revision"])
                self.config = resolve(self.base_config, spec).config
        business_date = utc(self.instant).astimezone(ZoneInfo("America/New_York")).date().isoformat()
        fingerprint = source_fingerprint()
        self.run_id = digest({"environment": self.config.environment, "account": account_id,
                              "business_date": business_date, "config": self.config.hash, "source": fingerprint,
                              "simulation_check":self.simulation_check})
        self.attempt_id, self.trace = uuid4().hex, []
        with daily_lock(Path(self.config.runtime_dir) / ".daily.lock"):
            with self.ledger.transaction():
                self.ledger.connection.execute("INSERT OR IGNORE INTO daily_runs VALUES(?,?,?,?,?,?,?,?)",
                    (self.run_id, account_id, self.config.environment, business_date, self.config.hash, fingerprint, "RUNNING", now_utc()))
                self.ledger.connection.execute("INSERT INTO daily_attempts VALUES(?,?,?,?,?,?)",
                    (self.attempt_id, self.run_id, "RUNNING", now_utc(), None, "{}"))
                self.ledger.connection.execute("UPDATE daily_runs SET status='RUNNING' WHERE run_id=?", (self.run_id,))
            try:
                result = self._run(events, expected_sequence, expected_hash, coverage_through, coverage_source,
                                   actions, reconciliation, fetch_range)
                result.update(run_id=self.run_id, attempt_id=self.attempt_id, business_date=business_date,
                              as_of=self.instant, steps=self.trace, environment=self.config.environment)
                self._finish(result["status"], result)
                return result
            except Exception as exc:
                self._finish("FAILED", {"code": getattr(exc, "code", "DAILY_FAILED"), "message": str(exc), "steps": self.trace})
                raise

    def _finish(self, status, details):
        with self.ledger.transaction():
            self.ledger.connection.execute("UPDATE daily_attempts SET status=?,finished_at=?,details=? WHERE attempt_id=?",
                (status, now_utc(), canonical(details), self.attempt_id))
            self.ledger.connection.execute("UPDATE daily_runs SET status=? WHERE run_id=?", (status, self.run_id))
            self.ledger.record_task(self.run_id, status, {"command": "daily", "attempt_id": self.attempt_id, **details})

    def _run(self, events, expected_sequence, expected_hash, coverage_through, coverage_source, actions, reconciliation, fetch_range):
        data_result = self._step("data", {"fetch_range": fetch_range, "as_of": self.instant},
                                 lambda: self._data(fetch_range), reuse=False)
        frame = metadata = calendar = None
        if data_result["status"] == "SUCCESS":
            frame, metadata, calendar = self.store.load(data_result["snapshot_id"])
        imported = None
        if events is not None:
            imported = self._step("import", {"events": events, "expected_sequence": expected_sequence, "expected_hash": expected_hash,
                "coverage_through": coverage_through, "coverage_source": coverage_source},
                lambda: self._import(events, expected_sequence, expected_hash, coverage_through, coverage_source), transactional=True)
        if not self.fixed_clock:
            self.instant = utc(now_utc()).isoformat()
        from ..options.receipts import advance
        option_receipts=self._step('option_receipts',{'batch':self.option_receipts,'resolutions':self.option_resolutions,
            'as_of':self.instant,'sequence':self.ledger.sequence(self.account_id)},
            lambda:advance(self.ledger,self.account_id,self.instant,batch=self.option_receipts,
                           resolutions=self.option_resolutions),reuse=False) if (
                self.option_receipts is not None or self.option_resolutions is not None
                or (self.ledger.connection.execute('SELECT version FROM schema_version').fetchone()[0]>=5 and
                    self.ledger.connection.execute('SELECT 1 FROM pending_option_events WHERE account_id=?',(self.account_id,)).fetchone())) else {
                'status':'NO_ACTION','pending_events':[],'errors':[]}
        from ..hedging.monitor import monitor
        hedge_before=self._step('hedge_before_execution',{'as_of':self.instant,'sequence':self.ledger.sequence(self.account_id)},
            lambda:monitor(self.ledger,self.account_id,self.instant),reuse=False)
        self.hedge_before=hedge_before
        option_execution=self._option_execution() if option_receipts['status']!='BLOCKED' else {
            'status':'BLOCKED','results':[],'errors':option_receipts['errors'] or
                [{'code':'PENDING_OPTION_RECEIPTS','message':'仍有未核实期权凭据'}],
            'not_processed':len(self.option_tasks)}
        facts = self._step("account_facts", {"snapshot": metadata, "actions": actions, "as_of": self.instant,"hedge_stage_checks":self.hedge_stage_checks},
                           lambda: self._facts(frame, calendar, actions) if option_execution['status']!='BLOCKED' else
                               {'status':'BLOCKED','completed':[],'waiting':[],'errors':option_execution['errors']}, transactional=True, reuse=False)
        option_marks=None
        if self.ledger.snapshot(self.account_id,self.instant).get('option_positions'):
            option_marks=self._step('option_valuation', {'request':self.option_valuation,
                'ledger_seq':self.ledger.sequence(self.account_id),'as_of':self.instant},
                lambda:self._option_marks(self.instant),reuse=False)
        checked = None
        if self.simulation_check and frame is not None and facts['status'] not in {'BLOCKED','FAILED'}:
            prices=quote_set(frame,calendar,self.config,self.instant,self.ledger.snapshot(self.account_id,self.instant)['positions'])['prices']
            current=self.ledger.snapshot(self.account_id,self.instant,prices)
            if current['anomalies'] or current['equity'] is None:
                checked={'status':'DIFFERENCES','source':'internal_simulation_check','reason':'模拟账本或估值不完整'}
            else:
                expected={'account_id':self.account_id,'currency':'USD','as_of':self.instant,'cash_basis':'settled',
                          'cash':current['settled_cash'],'positions':current['positions'],'source':'internal_simulation_check'}
                checked=self._step('simulation_self_check',{'expected':expected,'sequence':self.ledger.sequence(self.account_id)},
                    lambda:self.ledger.reconcile(self.account_id,expected,prices,rules=ReconciliationRules.from_config(self.config)),
                    transactional=True,reuse=False)
        if reconciliation is not None:
            checked = self._step("reconciliation", {"expected": reconciliation, "sequence": self.ledger.sequence(self.account_id),
                "rules": ReconciliationRules.from_config(self.config).content(), "snapshot": metadata},
                lambda: self.ledger.reconcile(self.account_id, reconciliation,
                    {**(quote_set(frame, calendar, self.config, reconciliation["as_of"], reconciliation["positions"])["prices"] if frame is not None else {}),
                     **self._option_marks(reconciliation['as_of'])['prices']},
                    rules=ReconciliationRules.from_config(self.config)), transactional=True)
        hedge_after=self._step('hedge_after_facts',{'as_of':self.instant,'sequence':self.ledger.sequence(self.account_id)},
            lambda:monitor(self.ledger,self.account_id,self.instant),reuse=False)
        planning = self._step("planning", {"snapshot": metadata, "sequence": self.ledger.sequence(self.account_id), "as_of": self.instant},
                              lambda: self._planning(frame, metadata, calendar, data_result, facts) if hedge_after['status']!='BLOCKED' else
                                  {'status':'BLOCKED','code':'HEDGE_MONITOR_BLOCKED','checks':hedge_after['checks']}, transactional=True, reuse=False)
        gaps = self._step("tracking_gaps", {"as_of": self.instant, "snapshot": metadata},
                          lambda: self._tracking_gaps(calendar), reuse=False)
        report = self._step("report", {"snapshot": metadata, "sequence": self.ledger.sequence(self.account_id), "as_of": self.instant,
            'option_valuation':self.option_valuation,
            "plans": [tuple(row) for row in self.ledger.connection.execute("SELECT plan_id,execution_status,check_status,reserved_cash,reserved_positions FROM plans")]},
            lambda: report_from_store(self.ledger, self.account_id, self.instant, self.store, self.config,
                                     Path(self.config.runtime_dir) / "reports/account-latest",option_valuation=self.option_valuation), reuse=False)
        statuses = [data_result["status"], facts["status"], planning["status"]]
        if option_execution['status']=='BLOCKED':statuses.append('BLOCKED')
        if hedge_after['status']=='BLOCKED':statuses.append('BLOCKED')
        if checked and checked["status"] == "DIFFERENCES":
            statuses.append("BLOCKED")
        if option_marks and option_marks['status']=='INCOMPLETE':statuses.append('BLOCKED')
        status = "FAILED" if "FAILED" in statuses else "BLOCKED" if "BLOCKED" in statuses else "WAITING" if "WAITING" in statuses else "SUCCESS"
        return {"status": status, "data": data_result, "import": imported, "account_facts": facts,
                "reconciliation": checked, "planning": planning, "tracking_gaps": gaps, "report_id": report["report_id"],
                "ledger_seq": report["ledger_seq"], "equity": report["equity"], "valuation": report["valuation"]["status"],
                'option_valuation':option_marks,'option_execution':option_execution,'option_receipts':option_receipts,
                'hedging':hedge_after,'hedging_before':hedge_before}

    def _option_execution(self):
        from ..options.data import OptionDataStore
        from ..options.simulation import execute as open_position
        from ..options.exit_tasks import execute_exit
        store=OptionDataStore(self.ledger.path.parent/'options/chains');results=[];errors=[]
        for index,item in enumerate(self.option_tasks):
            name='option_execution:'+str(index)+':'+digest(item)
            def perform():
                request=item['request']
                if 'as_of' not in request or utc(request['as_of'])!=utc(self.instant):
                    raise QuantError('OPTION_PROCESSING_TIME_MISMATCH','模拟任务处理时点必须等于日常任务时点')
                if item['kind']=='OPEN':
                    # Native OPEN recomputes its own stage and shared monitor atomically.
                    row=self.ledger.connection.execute('SELECT account_id FROM option_plans WHERE plan_id=?',(request.get('plan_id'),)).fetchone()
                    account=row[0] if row else None
                    identity='option-simulation:'+digest({'plan_id':request.get('plan_id')})
                else:
                    identity='option-exit-simulation:'+str(request.get('exit_id'))
                    row=self.ledger.connection.execute('SELECT details FROM tasks WHERE task_id=?',('option-exit-freeze:'+str(request.get('exit_id')),)).fetchone()
                    account=json.loads(row[0])['proposal']['account_id'] if row else None
                if account!=self.account_id:
                    raise QuantError('OPTION_ACCOUNT_MISMATCH','期权冻结任务不存在或不属于本日常账户')
                result=open_position(self.ledger,store,request) if item['kind']=='OPEN' else execute_exit(self.ledger,store,request)
                return {'artifact_type':'option_simulation_audit','operation':item,'audit_task_id':identity,'audit':result}
            try:
                # The native operation commits its own atomic facts and audit.
                # A crash before daily_steps commits is recovered by that audit.
                results.append(self._step(name,item,perform))
                failure_id='option-daily-failure:'+digest({'run':self.run_id,'item':item})
                failed=self.ledger.connection.execute('SELECT details FROM tasks WHERE task_id=?',(failure_id,)).fetchone()
                if failed:
                    with self.ledger.transaction():
                        self.ledger.record_task(failure_id,'SUCCESS',{**json.loads(failed[0]),'status':'RECOVERED',
                            'recovered_by':results[-1]['audit_task_id'],'resolved_at':now_utc()})
            except QuantError as exc:
                failure={'artifact_type':'option_simulation_failure','operation':item,'index':index,
                         'code':exc.code,'message':str(exc),'as_of':self.instant}
                with self.ledger.transaction():
                    self.ledger.record_task('option-daily-failure:'+digest({'run':self.run_id,'item':item}), 'BLOCKED',failure)
                errors.append(failure);break
        return {'status':'BLOCKED' if errors else 'SUCCESS' if results else 'NO_ACTION',
                'results':results,'errors':errors,'not_processed':len(self.option_tasks)-len(results)-len(errors),
                'meaning':'推进事前冻结的合成成交；失败停止后续任务，已提交事实保留；不生成新的决策或券商订单'}

    def _option_marks(self,as_of):
        if not self.ledger.snapshot(self.account_id,as_of).get('option_positions'):
            return {'status':'NO_OPTION_POSITIONS','prices':{},'checks':[]}
        if self.option_valuation is None:
            return {'status':'INCOMPLETE','prices':{},'checks':['OPTION_VALUATION_REQUEST_REQUIRED']}
        from ..options.data import OptionDataStore
        from ..options.valuation import quote_set as option_quotes
        return option_quotes(self.ledger,self.account_id,OptionDataStore(self.ledger.path.parent/'options/chains'),
                            self.option_valuation['snapshot_id'],as_of,self.option_valuation['limits'])

    def _tracking_gaps(self, calendar):
        """Describe known gaps after tracking began; never reconstruct signals/orders."""
        if calendar is None:
            return {"status": "UNAVAILABLE", "reason": "缺少可用日历，不能确认漏跑月份", "months": []}
        start = self.ledger.connection.execute("SELECT min(business_date) FROM daily_runs WHERE account_id=?",
                                               (self.account_id,)).fetchone()[0]
        if start is None:
            return {"status": "UNAVAILABLE", "reason": "尚无跟踪开始日期", "months": []}
        clock, months = utc(self.instant), []
        mode = "historical_reconstruction" if self.config.environment == "demo" else "forward"
        for day in calendar.month_ends():
            if str(day.date()) < start:
                continue
            eligible = calendar.close(calendar.next(day))
            if eligible.to_pydatetime() > clock:
                continue
            session = str(day.date())
            if self.ledger.connection.execute("SELECT version FROM schema_version").fetchone()[0] >= 3 and self.ledger.connection.execute(
                    "SELECT 1 FROM strategy_bindings WHERE account_id=?", (self.account_id,)).fetchone():
                from ..strategies.bindings import BindingService
                try:
                    binding = BindingService(self.ledger, self.config).selected(self.account_id, session)
                except QuantError:
                    continue
                decision = self.ledger.connection.execute("SELECT outcome,binding_seq FROM monthly_decisions WHERE account_id=? AND decision_session=?",
                    (self.account_id, session)).fetchone()
                if decision and decision["binding_seq"] == binding["binding_seq"] and decision["outcome"] in {"READY", "NO_ACTION"}:
                    continue
                months.append({"session": session, "state": "BOUND_DECISION_BLOCKED" if decision else "NO_BOUND_DECISION",
                               "binding_seq": binding["binding_seq"]})
                continue
            plan = self.ledger.connection.execute(
                "SELECT plan_id,execution_status,check_status FROM plans WHERE account_id=? "
                "AND json_extract(payload,'$.signal.decision_session')=? ORDER BY rowid DESC LIMIT 1",
                (self.account_id, session)).fetchone()
            if plan is not None:
                # Cancelled/expired plans existed; absence of a fill is not a lost task.
                if plan["execution_status"] != "DRAFT" or plan["check_status"] == "PASSED":
                    continue
                state, details = "PLAN_BLOCKED", {"plan_id": plan["plan_id"]}
            else:
                rows = self.ledger.connection.execute(
                    "SELECT archive_id FROM strategy_signals WHERE decision_session=? AND mode=?", (session, mode)).fetchall()
                if not rows:
                    state, details = "NO_ARCHIVED_SIGNAL", {}
                else:
                    try:
                        archived = [SignalArchive(self.ledger).get(row[0]) for row in rows]
                        state = "NO_PLAN" if any(x["signal"]["status"] == "READY" for x in archived) else "SIGNAL_BLOCKED"
                        details = {"archive_ids": [x["archive_id"] for x in archived],
                                   "signal_statuses": [x["signal"]["status"] for x in archived]}
                    except QuantError as exc:
                        state, details = "CORRUPT_SIGNAL", {"code": exc.code}
            months.append({"decision_session": session, "eligible_close": eligible.isoformat(), "state": state, **details})
        coverage = "LIMITED" if clock > calendar.schedule.close_time.iloc[-1].to_pydatetime() else "COVERED"
        return {"status": "WARNING" if months else "COMPLETE", "months": months, "tracking_start": start,
                "calendar_end": str(calendar.sessions[-1].date()), "calendar_coverage": coverage,
                "mode": mode, "not_forward_evidence": self.config.environment == "demo",
                "message": "仅核对跟踪开始后的已知月末记录；不回填信号、计划或成交；此前策略和行情条件不由当前参数推定"}

    def _data(self, fetch_range):
        try:
            if fetch_range:
                signal_meta = self.store.load_role("signal")[1]
                update_online(self.store, self.config, *fetch_range,
                    series_id=self.store.series_identity(signal_meta) if self.store.heads() else None)
            if not self.fixed_clock:
                self.instant = utc(now_utc()).isoformat()
            frame, metadata, calendar = self.store.load_role("execution")
            if self.config.publication_delay_minutes is None:
                raise QuantError("MISSING_EXECUTION_CONFIG", "日常数据检查需明确发布延迟")
            reference = calendar.latest_completed(self.instant, self.config.publication_delay_minutes)
            required = set(self.config.symbols) | set(self.ledger.snapshot(self.account_id, self.instant)["positions"])
            quality = price_quality(frame, calendar, self.config, required, reference, self.instant)
            return {"status": "SUCCESS" if quality["status"] == "PASSED" else "BLOCKED", "code": quality["code"],
                    "snapshot_id": metadata["snapshot_id"], "expected_session": str(reference.date()), "quality": quality}
        except QuantError as exc:
            return {"status": "WAITING" if exc.code == "NO_COMPLETED_DATA" else "FAILED" if exc.code == "DOWNLOAD_FAILED" else "BLOCKED",
                    "code": exc.code, "message": str(exc)}

    def _import(self, events, expected_sequence, expected_hash, coverage_through, coverage_source):
        if expected_sequence is None or expected_hash != digest(events):
            raise QuantError("PREVIEW_REQUIRED", "日常提交仍需独立预检序号及文件内容哈希")
        current = self.ledger.sequence(self.account_id)
        if expected_sequence != current:
            # A committed batch may be retried on another business day. Only exact duplicates qualify.
            for row in events:
                event = self.ledger.normalize_event(row, self.account_id)
                existing = self.ledger.connection.execute("SELECT content_hash FROM events WHERE account_id=? AND event_id=?",
                                                          (self.account_id, event["event_id"])).fetchone()
                if not existing or existing[0] != digest(event) or expected_sequence > current:
                    raise QuantError("STALE_PREVIEW", "账户或账单变化，需要重新预检")
        from ..options.receipts import import_statement
        return import_statement(self.ledger,self.account_id,events,current,self.instant,
                                coverage_through=coverage_through,coverage_source=coverage_source)

    def _facts(self, frame, calendar, actions):
        if self.config.environment == "real":
            return {"status": "NO_ACTION", "message": "真实账户仅使用已提交凭据，不产生模拟成交",
                    "completed": [], "waiting": [], "errors": []}
        service, errors, waiting, completed = PlanService(self.ledger, self.config), [], [], []
        actions = normalize_actions(actions or [])
        timeline = {}
        for action in actions:
            times = [max(utc(action["effective_at"]), utc(action["available_at"]))]
            if action.get("payment_at"):
                times.append(max(utc(action["payment_at"]), utc(action["available_at"])))
            for instant in times:
                if instant <= utc(self.instant):
                    timeline.setdefault(instant, {"actions": False, "plans": []})["actions"] = True
        plans = self.ledger.connection.execute("SELECT plan_id FROM plans WHERE account_id=? AND execution_status IN ('READY','PARTIAL')", (self.account_id,)).fetchall()
        for row in plans:
            plan = service.get(row[0])
            if plan["manual_pending"]:
                waiting.append({"plan_id": row[0], "code": "PENDING_MANUAL_ORDER"})
                continue
            if frame is None:
                waiting.append({"plan_id": row[0], "code": "NO_DATA"})
                continue
            session = plan["payload"].get("execution_session")
            if not session:
                errors.append({"plan_id": row[0], "code": "MISSING_PLAN_ASSUMPTIONS"})
                continue
            close = calendar.close(session).to_pydatetime()
            rows = frame.loc[frame.session_date == session]
            processing = max([close] + [utc(value.to_pydatetime()) for value in rows.available_at])
            if processing > utc(self.instant):
                waiting.append({"plan_id": row[0], "code": "EXECUTION_NOT_ARRIVED"})
                continue
            if any(utc(a["effective_at"]) == close and a["symbol"] in {l["symbol"] for l in plan["payload"]["sizing"]["lines"]} for a in actions):
                errors.append({"plan_id": row[0], "code": "AMBIGUOUS_ACTION_ORDER"})
                continue
            timeline.setdefault(close, {"actions": False, "plans": []})["plans"].append(row[0])
        for instant, operations in sorted(timeline.items()):
            if operations["actions"]:
                apply_actions(self.ledger, self.account_id, actions, instant.isoformat())
            for plan_id in operations["plans"]:
                try:
                    result = simulate(service, plan_id, frame, calendar, self.instant, state_as_of=instant.isoformat(),option_valuation=self.option_valuation,hedge_stage_check=self.hedge_stage_checks.get(plan_id))
                    result["plan_id"] = plan_id
                    (waiting if result["status"] == "WAITING" else completed).append(result)
                except QuantError as exc:
                    errors.append({"plan_id": plan_id, "code": exc.code, "message": str(exc)})
        if actions:
            apply_actions(self.ledger, self.account_id, actions, self.instant)
        return {"status": "BLOCKED" if errors else "WAITING" if waiting else "SUCCESS", "completed": completed, "waiting": waiting, "errors": errors}

    def _planning(self, frame, metadata, calendar, data_result, facts):
        if data_result["status"] != "SUCCESS":
            return {"status": "WAITING" if data_result["status"] == "WAITING" else "BLOCKED", "code": data_result["code"]}
        if facts["status"] == "BLOCKED":
            return {"status": "BLOCKED", "code": "ACCOUNT_FACTS_BLOCKED"}
        service = PlanService(self.ledger, self.config)
        try:
            if not self.fixed_clock:
                self.instant = utc(now_utc()).isoformat()
            reference = calendar.latest_completed(self.instant, self.config.publication_delay_minutes)
            current = self.ledger.connection.execute("SELECT plan_id FROM plans WHERE account_id=? AND COALESCE(json_extract(payload,'$.purpose'),'monthly_strategy')!='hedge_stage' ORDER BY rowid DESC LIMIT 1", (self.account_id,)).fetchone()
            if current:
                plan = service.get(current[0])
                body = plan["payload"]
                if plan["manual_pending"]:
                    return {"status": "WAITING", "code": "PENDING_MANUAL_ORDER", "plan_id": plan["plan_id"]}
                if any(item.get("plan_id") == plan["plan_id"] for item in facts["waiting"]):
                    return {"status": "WAITING", "code": "FROZEN_EXECUTION_WAITING", "plan_id": plan["plan_id"]}
                if body.get("intent_status") == "WAITING_SETTLEMENT" or plan["execution_status"] in {"READY", "PARTIAL", "DRAFT"}:
                    if utc(self.instant) > calendar.close(body["signal"]["valid_through_session"]).to_pydatetime():
                        service.refresh(plan["plan_id"], self.instant)
                    else:
                        revised = service.revise(plan["plan_id"], frame, metadata, calendar, self.instant,option_valuation=self.option_valuation)
                        return {"status": "BLOCKED" if revised["check_status"] == "BLOCKED" else "WAITING" if revised["payload"].get("intent_status") == "WAITING_SETTLEMENT" else "SUCCESS",
                                "plan_id": revised["plan_id"], "checks": revised["payload"]["checks"]}
                if body["signal"]["decision_session"] == str(reference.date()):
                    return {"status": "NO_ACTION", "code": "MONTHLY_INTENT_EXISTS", "plan_id": plan["plan_id"]}
            if reference not in calendar.month_ends():
                return {"status": "NO_ACTION", "code": "NOT_REBALANCE_DAY"}
            if self.ledger.connection.execute("SELECT version FROM schema_version").fetchone()[0] >= 3 and self.ledger.connection.execute(
                    "SELECT 1 FROM strategy_bindings WHERE account_id=?", (self.account_id,)).fetchone():
                from ..strategies.bindings import BindingService
                from ..strategies.spec import DataBundle
                factor_latest = Path(self.config.runtime_dir) / "factors/latest.json"
                factor_id = json.loads(factor_latest.read_text())["snapshot_id"] if factor_latest.exists() else None
                from ..data.selection import bundle_for
                bundle = bundle_for(self.store)
                return BindingService(self.ledger, self.config).decide(self.account_id, bundle, reference,
                    as_of=self.instant if self.config.environment == "demo" else None,option_valuation=self.option_valuation)
            account_instant = ((calendar.close(reference) + timedelta(
                minutes=self.config.publication_delay_minutes)).isoformat()
                if self.config.environment == "demo" else self.instant)
            signal_frame, signal_meta, signal_calendar = self.store.load_role("signal")
            record = SignalArchive(self.ledger).generate(signal_frame, signal_meta, signal_calendar, self.config, reference,
                account_state=self.ledger.snapshot(self.account_id, account_instant))
            if not self.fixed_clock:
                self.instant = utc(now_utc()).isoformat()
            plan = service.create(self.account_id, decode_signal(record["signal"]), frame, metadata, calendar, self.instant,option_valuation=self.option_valuation)
            return {"status": "BLOCKED" if plan["check_status"] == "BLOCKED" else "SUCCESS", "plan_id": plan["plan_id"],
                    "signal_archive_id": record["archive_id"], "checks": plan["payload"]["checks"]}
        except QuantError as exc:
            return {"status": "BLOCKED", "code": exc.code, "message": str(exc)}
