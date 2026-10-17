"""Fixed-rule time windows and cost scenarios, using the existing bt attempt service."""
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
import os
import pandas as pd
from ..common import QuantError, canonical, digest, now_utc, utc, write_json, finite_float
from ..execution.daily import daily_lock
from ..config import Config
from ..strategies.spec import DataBundle
from ..strategies.store import StrategyStore
from .experiments import ResearchSpec
from .service import ResearchService, process_identity, worker_alive


class ValidationService:
    def __init__(self, ledger, config):
        self.ledger,self.config=ledger,config
        if ledger.connection.execute('SELECT version FROM schema_version').fetchone()[0]<4:
            raise QuantError('V18_NOT_ENABLED','验证套件需要v1.8工作区')
        self.root=ledger.path.parent

    def protocol(self, request):
        if not isinstance(request,dict) or set(request)!={'name','specification','future_start'} or not isinstance(request['name'],str) or not request['name'].strip():
            raise QuantError('INVALID_PROTOCOL','协议需要名称、固定规格和未来起点（历史验证填null）')
        self._items(request['specification'])
        if request['future_start'] is not None and any(pd.Timestamp(w['start']).date()<utc(request['future_start']).date() for w in request['specification']['windows']):
            raise QuantError('OBSERVED_EVALUATION','未来观察窗口不能早于登记的未来起点')
        if request['future_start'] is not None and utc(request['future_start'])<=utc(now_utc()):
            raise QuantError('OBSERVED_EVALUATION','未来观察起点必须晚于实际登记时间')
        body={**request,'registered_at':now_utc(),'purpose':'future_observation' if request['future_start'] else 'observed_validation',
              'not_proof_of_unseen_external_data':True,
              'evidence_mode':'registered_historical_reconstruction',
              'forward_evidence_requires_archived_received_signals':True}
        identity=digest(body)
        with self.ledger.transaction():
            self.ledger.connection.execute('INSERT INTO validation_protocols VALUES(?,?,?)',(identity,canonical(body),body['registered_at']))
        return {'protocol_id':identity,**body}

    def _items(self,request):
        expected={'members','benchmark_member_id','data_bundle','windows','cost_scenarios'}
        if not isinstance(request,dict) or set(request)!=expected:
            raise QuantError('INVALID_VALIDATION','验证规格字段不完整/未知')
        if not isinstance(request['members'],dict) or not 2<=len(request['members'])<=7:
            raise QuantError('INVALID_VALIDATION','需要一个基准及1至6个候选成员')
        windows=request['windows'];costs=request['cost_scenarios']
        if not isinstance(windows,list) or not windows or not isinstance(costs,list) or not costs:
            raise QuantError('INVALID_VALIDATION','至少一个窗口及成本场景')
        if len(windows)*len(costs)*len(request['members'])>48:
            raise QuantError('VALIDATION_TOO_LARGE','最多48个成员回测，请缩小套件')
        if any(not isinstance(c,dict) or not isinstance(c.get('id'),str) for c in costs):
            raise QuantError('INVALID_VALIDATION','成本场景必须包含文本ID')
        if len({c.get('id') for c in costs})!=len(costs):
            raise QuantError('INVALID_VALIDATION','成本场景ID必须唯一')
        previous=None
        for window in windows:
            from datetime import date
            if not isinstance(window,dict) or set(window)!={'start','end'}:
                raise QuantError('INVALID_VALIDATION','窗口必须明确起止日期')
            try:
                for value in window.values():
                    if not isinstance(value,str) or date.fromisoformat(value).isoformat()!=value:raise ValueError()
            except ValueError as exc:raise QuantError('INVALID_VALIDATION','窗口日期需要YYYY-MM-DD') from exc
            if set(window)!={'start','end'} or pd.Timestamp(window['start'])>pd.Timestamp(window['end']) or (previous and window['start']<=previous):
                raise QuantError('INVALID_VALIDATION','窗口需按时间排序且互不重叠')
            previous=window['end']
        members={name:StrategyStore(self.ledger).get(ref['strategy_id'],ref['revision']) for name,ref in request['members'].items()}
        bundle=DataBundle(**request['data_bundle']);items=[]
        for i,window in enumerate(windows):
            for cost in costs:
                if set(cost)!={'id','commission_multiplier','slippage_multiplier','fixed_fee_multiplier'} or not isinstance(cost['id'],str) or not cost['id'].strip():
                    raise QuantError('INVALID_VALIDATION','成本场景需明确三种费率倍数和ID')
                scales=[finite_float(cost[key]) for key in ['commission_multiplier','slippage_multiplier','fixed_fee_multiplier']]
                if any(x<0 or x>10 for x in scales): raise QuantError('INVALID_VALIDATION','费用倍数须在0至10之间')
                config=replace(self.config,evaluation_start=window['start'],evaluation_end=window['end'],
                    commission_bps=self.config.commission_bps*scales[0],slippage_bps=self.config.slippage_bps*scales[1],fixed_fee=self.config.fixed_fee*scales[2])
                spec=ResearchSpec.create(config,members,request['benchmark_member_id'],bundle,purpose='validation')
                items.append({'window':i,'cost_id':cost['id'],'spec':spec.content()})
        return items

    def create(self,request,*,protocol_id=None):
        if protocol_id:
            row=self.ledger.connection.execute('SELECT payload FROM validation_protocols WHERE protocol_id=?',(protocol_id,)).fetchone()
            if not row: raise QuantError('UNKNOWN_PROTOCOL','协议不存在')
            protocol=json.loads(row[0])
            original=protocol['specification']
            if protocol['future_start']:
                from ..data.store import DataStore
                store=DataStore(self.root/'data')
                same_rules={k:v for k,v in original.items() if k!='data_bundle'}=={k:v for k,v in request.items() if k!='data_bundle'}
                old_bundle,new_bundle=original['data_bundle'],request['data_bundle']
                _,old_meta,_=store.load(old_bundle['signal_snapshot_id']);_,new_meta,_=store.load(new_bundle['signal_snapshot_id'])
                same_series=store.series_identity(old_meta)==store.series_identity(new_meta)
                unchanged_factors=old_bundle.get('factor_snapshot_id')==new_bundle.get('factor_snapshot_id')
                if not same_rules or not same_series or not unchanged_factors:
                    raise QuantError('FROZEN_PROTOCOL','未来协议仅允许同来源价格系列更新，规则和因子必须保持')
            elif original!=request: raise QuantError('FROZEN_PROTOCOL','套件与已登记规则不同')
            if protocol['future_start'] and utc(now_utc())<utc(protocol['future_start']):
                return {'status':'WAITING_FOR_DATA','protocol_id':protocol_id}
        items=self._items(request)
        body={'request':request,'items':items,'protocol_id':protocol_id,'mode':'independent_cash_windows',
              'history_is_reconstruction':True,'max_member_backtests':48}
        identity=digest(body)
        with self.ledger.transaction():
            self.ledger.connection.execute('INSERT OR IGNORE INTO validation_suites VALUES(?,?,?,?,?)',(identity,'CREATED',canonical(body),'{}',now_utc()))
            for item in items:
                key=digest({'suite':identity,'item':item})
                self.ledger.connection.execute('INSERT OR IGNORE INTO validation_items VALUES(?,?,?,?,?,?)',(key,identity,'CREATED',canonical(item),None,'{}'))
        return self.get(identity)

    def get(self,identity):
        row=self.ledger.connection.execute('SELECT * FROM validation_suites WHERE suite_id=?',(identity,)).fetchone()
        if not row: raise QuantError('UNKNOWN_VALIDATION','套件不存在')
        body=dict(row);body['payload']=json.loads(body['payload']);body['details']=json.loads(body['details'])
        body['items']=[{**dict(r),'payload':json.loads(r['payload']),'details':json.loads(r['details'])} for r in self.ledger.connection.execute('SELECT * FROM validation_items WHERE suite_id=? ORDER BY item_id',(identity,))]
        return body

    def list(self):
        return [self.get(r[0]) for r in self.ledger.connection.execute('SELECT suite_id FROM validation_suites ORDER BY created_at DESC LIMIT 100')]

    def run(self,identity,*,retry=False):
        with daily_lock(self.root/'.validation.lock'):
            suite=self.get(identity)
            if suite['status']=='SUCCESS':
                for item in suite['items']: ResearchService(self.ledger)._report(item['attempt_id'])
                return suite
            with self.ledger.transaction():
                foreign_attempt=self.ledger.connection.execute("SELECT attempt_id FROM research_attempts WHERE status IN ('CREATED','RUNNING','PUBLISHING')").fetchone()
                owned_attempts={i['attempt_id'] for i in suite['items']}
                if foreign_attempt and foreign_attempt[0] not in owned_attempts:
                    raise QuantError('RESEARCH_ALREADY_RUNNING','当前已有独立研究任务，套件尚未取得执行权')
                active=self.ledger.connection.execute("SELECT suite_id FROM validation_suites WHERE status='RUNNING' AND suite_id<>?",(identity,)).fetchone()
                if active: raise QuantError('VALIDATION_ALREADY_RUNNING','其他套件正在运行或需恢复')
                self.ledger.connection.execute('UPDATE validation_suites SET status=?,details=? WHERE suite_id=?',('RUNNING',canonical({'worker':process_identity()}),identity))
            service=ResearchService(self.ledger);failed=[]
            try:
                for item in suite['items']:
                    if item['status']=='SUCCESS':
                        service._report(item['attempt_id']);continue
                    if item['status']=='FAILED' and not retry:
                        failed.append(item['item_id']);continue
                    try:
                        spec=ResearchSpec.from_dict(item['payload']['spec']);spec.require_current_implementation()
                        attempt=service.submit(spec,rerun=retry,suite_id=identity)
                        with self.ledger.transaction():
                            self.ledger.connection.execute('UPDATE validation_items SET status=?,attempt_id=? WHERE item_id=?',('RUNNING',attempt['attempt_id'],item['item_id']))
                        if attempt['status']=='CREATED': service.run(attempt['attempt_id'])
                        elif attempt['status']!='SUCCESS': raise QuantError('ATTEMPT_REQUIRES_RECOVERY','子实验需核实恢复后明确重跑')
                        manifest=service._report(attempt['attempt_id'])
                        detail={'run_id':manifest['run_id'],'metrics':manifest['metrics'],'mode':'independent_cash_window'}
                        with self.ledger.transaction(): self.ledger.connection.execute('UPDATE validation_items SET status=?,details=? WHERE item_id=?',('SUCCESS',canonical(detail),item['item_id']))
                    except Exception as exc:
                        failed.append(item['item_id'])
                        with self.ledger.transaction(): self.ledger.connection.execute('UPDATE validation_items SET status=?,details=? WHERE item_id=?',('FAILED',canonical({'code':getattr(exc,'code','VALIDATION_FAILED'),'message':str(exc)}),item['item_id']))
                status='INCOMPLETE' if failed else 'SUCCESS'
                with self.ledger.transaction(): self.ledger.connection.execute('UPDATE validation_suites SET status=?,details=? WHERE suite_id=?',(status,canonical({'failed_items':failed,'not_stitched_equity':True,'cross_cost_ranking':False}),identity))
                self.publish_summary(identity)
                return self.get(identity)
            except BaseException:
                # RUNNING and PID evidence remain for explicit recovery.
                raise

    def publish_summary(self, identity):
        import csv
        from ..locks import publication_lock
        suite=self.get(identity)
        rows=[]
        for item in suite['items']:
            if not item['details'].get('metrics'):
                rows.append({'item_id':item['item_id'],'window':item['payload']['window'],'cost_id':item['payload']['cost_id'],'status':item['status'],'failure':item['details'].get('message','')})
            for member,metrics in item['details'].get('metrics',{}).items():
                rows.append({'item_id':item['item_id'],'window':item['payload']['window'],
                    'cost_id':item['payload']['cost_id'],'member':member,'status':item['status'],**metrics})
        directory=self.root/'reports/validation'/identity
        with publication_lock(self.root):
            directory.mkdir(parents=True,exist_ok=True)
            write_json(directory/'summary.json',suite)
            fields=sorted(set().union(*(r.keys() for r in rows))) if rows else ['item_id','status']
            temporary=directory/'summary.csv.tmp'
            with temporary.open('w',newline='',encoding='utf-8-sig') as output:
                writer=csv.DictWriter(output,fieldnames=fields);writer.writeheader();writer.writerows(rows)
            os.replace(temporary,directory/'summary.csv')
        return directory

    def recover(self,identity):
        with daily_lock(self.root/'.validation.lock'):
            suite=self.get(identity)
            if suite['status']=='SUCCESS':return suite
            if worker_alive(suite['details'].get('worker')): return {'status':'WORKER_ALIVE'}
            ResearchService(self.ledger).recover()
            with self.ledger.transaction(): self.ledger.connection.execute('UPDATE validation_suites SET status=? WHERE suite_id=?',('INCOMPLETE',identity))
            return self.get(identity)

    def launch(self,identity,*,retry=False):
        with daily_lock(self.root/'.validation-submission.lock'):
            suite=self.get(identity)
            if suite['status']=='SUCCESS' or worker_alive(suite['details'].get('worker')):return suite
            job=self.root/'validation-jobs'/identity;job.mkdir(parents=True,exist_ok=True)
            config_path=job/'config.json';write_json(config_path,self.config.content())
            log=job/'worker.log';env=dict(os.environ);env.pop('PYTHONPATH',None);env.pop('PYTHONHOME',None);env['PYTHONNOUSERSITE']='1'
            args=[sys.executable,'-m','personal_quant','--config',str(config_path),'validation-worker','--suite-id',identity]
            if retry:args.append('--retry')
            with log.open('ab') as output:process=subprocess.Popen(args,stdout=output,stderr=subprocess.STDOUT,env=env,start_new_session=True)
            with self.ledger.transaction():self.ledger.connection.execute('UPDATE validation_suites SET details=? WHERE suite_id=?',(canonical({'worker':process_identity(process.pid),'log':str(log)}),identity))
            return self.get(identity)
