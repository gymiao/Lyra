"""Atomic, audited activation of isolated synthetic demonstration plans."""
import json
import shutil
import tempfile
from pathlib import Path
from ..common import QuantError,canonical,decimal as D,digest,now_utc,utc
from ..locks import publication_lock,publish_directory
from .monthly import validate_frozen
from .qualification import assess_engine,ENGINE_TEMPLATES
from .data import quality
from .plans import sizing,unfilled_resources
from .lifecycle import review

FIELDS={'request_id','plan_id','as_of','valid_until','expected_sequence','monthly_signal',
        'engine_evidence_file','quote_snapshot_id','reconciliation_max_days'}


def activate(book,store,request):
    if not isinstance(request,dict) or not FIELDS<=set(request) or set(request)-FIELDS-{'hedge_stage_check','execution_window'} or not isinstance(request['request_id'],str) or not request['request_id']:
        raise QuantError('INVALID_OPTION_ACTIVATION','激活需稳定请求ID、计划/账户序号、月度证据、当前报价及显式期限/对账参数')
    clock=utc(request['as_of']);until=utc(request['valid_until'])
    if type(request['expected_sequence']) is not int or request['expected_sequence']<0:
        raise QuantError('INVALID_OPTION_ACTIVATION','账户序号必须为非负整数')
    days=D(request['reconciliation_max_days'])
    if clock>utc(now_utc()) or days<0 or days!=days.to_integral_value():raise QuantError('INVALID_OPTION_ACTIVATION','时间或对账期限无效')
    identity='option-activation:'+digest({'plan_id':request['plan_id'],'request_id':request['request_id']})
    with publication_lock(book.path.parent),book.transaction():
        previous=book.connection.execute('SELECT details FROM tasks WHERE task_id=?',(identity,)).fetchone()
        if previous:
            audit=json.loads(previous[0])
            if audit['request_hash']!=digest(request):raise QuantError('EVENT_CONFLICT','相同激活请求ID内容冲突')
            if book.environment!='demo' and isinstance(request['monthly_signal'],dict) and request['monthly_signal'].get('schema_version')==2:
                from .forward import verify_registered
                verify_registered(book,store,request['monthly_signal'])
            from ..hedging.stage_gate import validate_cached
            validate_cached(book,audit,'OPEN')
            return audit
        body=review(book,request['plan_id'],clock)
        if book.sequence(body['account_id'])!=request['expected_sequence']:raise QuantError('STALE_PREVIEW','账户序号已变化')
        from ..hedging.stage_gate import require_for_plan
        stage_check=require_for_plan(book,body['account_id'],'option',body['plan_id'],'OPEN',request['as_of'],request.get('hedge_stage_check'))
        if body.get('activation') or body['status']!='DRAFT' or body.get('manual_execution',{}).get('pending'):
            raise QuantError('INVALID_OPTION_ACTIVATION','只能首次激活没有实际成交/在途订单的草案')
        checks=[]
        from ..hedging.monitor import require_planning
        try:require_planning(book,body['account_id'],request['as_of'],stage_check=stage_check)
        except QuantError as exc:checks.append(exc.code)
        def block(code):checks.append(code)
        for other in book.connection.execute('SELECT plan_id,payload FROM option_plans WHERE account_id=?',(body['account_id'],)):
            if other['plan_id']==body['plan_id']:continue
            candidate=json.loads(other['payload'])
            if candidate['intent_id']==body['intent_id'] or candidate['selection']['decision_hash']==body['selection']['decision_hash']:
                current=review(book,other['plan_id'],clock)
                if current.get('intent_closure',{}).get('reason')=='EXTERNAL_CAPITAL_CHANGED':
                    block('OPTION_INTENT_CLOSED_FOR_CAPITAL_CHANGE')
                if current['status'] in {'READY','PARTIAL','FILLED'} or current.get('manual_execution',{}).get('pending'):
                    block('OPTION_INTENT_ALREADY_ACTIVATED')
        forward=False
        if book.environment=='demo':
            monthly=validate_frozen(request['monthly_signal'])
        else:
            from .forward import validate_forward,verify_registered
            try:
                monthly=validate_forward(request['monthly_signal']);forward=True
            except QuantError:
                monthly=validate_frozen(request['monthly_signal'])
                block('FORWARD_SIGNAL_REQUIRED')
        if (monthly['selection']['decision_hash']!=body['selection']['decision_hash']
                or monthly['input']['snapshot_id']!=body['snapshot_id']):
            block('MONTHLY_SIGNAL_MISMATCH')
        if forward:
            path=book.path.parent/'options/monthly-forward'/(monthly['monthly_signal_id']+'.json')
            try:
                stored=validate_forward(json.loads(path.read_text()),monthly['monthly_signal_id'])
                if (stored!=monthly or monthly['account_id']!=body['account_id']
                        or monthly['environment']!=book.environment
                        or not utc(monthly['generated_at'])<=utc(body['created_at'])<=clock):
                    block('FORWARD_SIGNAL_NOT_BOUND')
                verify_registered(book,store,monthly)
            except (OSError,ValueError,KeyError,TypeError):
                block('FORWARD_SIGNAL_NOT_BOUND')
        from .execution_window import assess as assess_window
        window=assess_window(monthly,request,book.environment)
        checks.extend(window['checks'])
        if body['selection']['template_id'] not in ENGINE_TEMPLATES:
            block('TEMPLATE_ACTIVATION_NOT_VALIDATED')
            evidence={'status':'BLOCKED'}
        else:
            evidence=assess_engine(request['engine_evidence_file'],body['selection']['template_id'])
            if evidence['status']!='PASSED':block('ENGINE_LIFECYCLE_UNQUALIFIED')
        contracts,quotes,metadata,manifest=store.load(request['quote_snapshot_id']);latest={}
        if book.environment!='demo' and (utc(manifest['created_at'])>clock or any(
                utc(quote['received_at'])>utc(manifest['created_at']) for quote in quotes)):
            block('QUOTE_SNAPSHOT_CAPTURE_TIME')
        for quote in quotes:
            if all(utc(quote[field])<=clock for field in ('exchange_timestamp','available_at','received_at')):
                symbol=quote['contract_id']
                if symbol not in latest or utc(quote['exchange_timestamp'])>utc(latest[symbol]['exchange_timestamp']):latest[symbol]=quote
        parameters=body['request']['selection']['parameters'];priced=json.loads(canonical(body['selection']));marks={};current_quotes=[]
        for leg in priced['legs']:
            symbol=leg['contract']['contract_id'];quote=latest.get(symbol);contract=contracts.get(symbol)
            if quote is None or contract is None or contract.version_hash!=leg['contract_version']:
                block('MISSING_CURRENT_QUOTE:'+symbol);continue
            issues=quality(quote,contract,clock,max_age_seconds=float(parameters['max_age_seconds']),
                max_underlying_skew_seconds=float(parameters['max_underlying_skew_seconds']),max_spread_fraction=parameters['max_spread_fraction'])
            checks.extend(issue+':'+symbol for issue in issues)
            leg['reference_quote']=quote
            current_quotes.append(quote)
            marks[contract.underlying]=quote['underlying_price'];marks[symbol]=(D(quote['bid'])+D(quote['ask']))/2
        if len(current_quotes)>1:
            times=[utc(q['exchange_timestamp']) for q in current_quotes]
            if (max(times)-min(times)).total_seconds()>float(parameters['max_leg_skew_seconds']):block('CURRENT_LEG_TIME_MISMATCH')
            spots=[D(q['underlying_price']) for q in current_quotes]
            if min(spots)<=0 or max(spots)/min(spots)-1>D(parameters['max_underlying_price_fraction']):block('CURRENT_UNDERLYING_PRICE_MISMATCH')
        source_check=None;permission_check=None
        if book.environment!='demo':
            from .source import assess_source
            from .permissions import assess as assess_permissions
            source_check=assess_source(book,metadata,[contracts[l['contract']['contract_id']] for l in priced['legs'] if l['contract']['contract_id'] in contracts],request['as_of'])
            checks.extend(source_check['checks'])
            if not source_check['actual_source_qualified']:block('OPTION_SOURCE_QUALIFICATION_REQUIRED')
            gross=sum((D(l['contract']['exercise_cash'])*abs(D(l['quantity_per_package']))*D(body['request']['packages'])
                for l in priced['legs'] if (l['contract']['right']=='CALL' and D(l['quantity_per_package'])>0)
                    or (l['contract']['right']=='PUT' and D(l['quantity_per_package'])<0)),D(0))
            permission_check=assess_permissions(book,body['account_id'],body['selection']['template_id'],'OPEN',request['as_of'],
                contract_count=sum(int(abs(D(l['quantity_per_package']))*D(body['request']['packages'])) for l in priced['legs']),
                physical_cash=gross,exit_days=body['selection']['exit_days_before_expiry'])
            checks.extend(permission_check['checks'])
            if permission_check['status']!='QUALIFIED':block('ACCOUNT_OPTION_PERMISSIONS_REQUIRED')
            if not forward or metadata['data_type']!='real_market' or body['data_type']!='real_market':
                block('FORWARD_SIGNAL_REQUIRED')
        elif metadata['data_type']!='synthetic' or body['data_type']!='synthetic':block('DEMO_SYNTHETIC_REQUIRED')
        try:book.check_reconciliation(body['account_id'],clock,int(days))
        except QuantError as exc:block(exc.code)
        snapshot=book.snapshot(body['account_id'],clock,marks)
        sized=sizing(priced,snapshot,body['request']['packages'],body['request']['risk']);checks.extend(sized['checks'])
        audit={'status':'BLOCKED' if checks else 'ACTIVATED','request':request,'request_hash':digest(request),
            'checks':sorted(set(checks)),'execution_window':window,'source_assessment':source_check,'permission_assessment':permission_check,'hedge_stage_check':stage_check,'engine_assessment':evidence,'account_basis':snapshot,'recorded_at':now_utc(),
            'meaning':('历史合成演示；不提交券商订单' if book.environment=='demo' else
                       '前向人工计划核验；READY仅表示本地建议，不提交券商订单或授予API权限')}
        if not checks:
            source=Path(request['engine_evidence_file']).parent
            target=book.path.parent/'options/engine-evidence'/evidence['evidence_hash']
            if any(item.is_symlink() for item in source.rglob('*')):raise QuantError('UNSAFE_ENGINE_EVIDENCE','引擎证据归档不接受符号链接')
            if not target.exists():
                if target.resolve().is_relative_to(source.resolve()):raise QuantError('INVALID_ENGINE_EVIDENCE_PATH','证据不能复制到自身子目录')
                target.parent.mkdir(parents=True,exist_ok=True)
                staged=Path(tempfile.mkdtemp(prefix='.pending-',dir=target.parent))
                try:
                    shutil.copytree(source,staged,dirs_exist_ok=True)
                    staged_check=assess_engine(staged/'verification.json',body['selection']['template_id'])
                    if staged_check['status']!='PASSED' or staged_check['evidence_hash']!=evidence['evidence_hash']:
                        raise QuantError('ENGINE_EVIDENCE_CHANGED','冻结证据在复制期间发生变化')
                    publish_directory(staged,target)
                finally:
                    if staged.exists():shutil.rmtree(staged)
            frozen_evidence=assess_engine(target/'verification.json',body['selection']['template_id'])
            if frozen_evidence['status']!='PASSED' or frozen_evidence['evidence_hash']!=evidence['evidence_hash']:
                raise QuantError('ENGINE_EVIDENCE_CHANGED','冻结证据在复制或激活前发生变化')
            before=json.loads(canonical(body))
            from .ledger import register_contract
            for leg in body['selection']['legs']:register_contract(book,leg['contract'])
            body.update(sizing=sized,account_basis=snapshot,status='READY',execution_status='READY',check_status='PASSED',checks=[],executable=True,
                limitations=(["合成历史demo建议；不提交券商订单或授予真实/前向交易权限"] if book.environment=='demo' else
                             ["基于实际来源凭据的前向人工计划；系统不向券商提交订单"])+[
                    '执行前需按当前时点重新检查报价、资金、持仓及对账；实际成交仅依据导入凭据'],
                activation={'as_of':clock.isoformat(),'valid_until':until.isoformat(),'basis_sequence':request['expected_sequence'],
                    'quote_snapshot_id':request['quote_snapshot_id'],'monthly_signal_id':monthly['monthly_signal_id'],
                    'engine_evidence_id':evidence['evidence_hash'],
                    'data_type':('synthetic_historical_demonstration' if book.environment=='demo' else
                                 'forward_paper' if book.environment=='paper' else 'real_account_manual_plan'),
                    'before':before})
            resources=unfilled_resources(body,{})
            body['active_reservation']=resources
            book.connection.execute('UPDATE option_plans SET status=?,payload=?,reserved_cash=?,reserved_positions=? WHERE plan_id=?',
                ('READY',canonical(body),resources['reserved_cash'],canonical(resources['reserved_positions']),body['plan_id']))
            for row in book.connection.execute("SELECT plan_id,payload FROM plans WHERE account_id=? AND execution_status IN ('READY','PARTIAL')",(body['account_id'],)).fetchall():
                payload=json.loads(row['payload']);payload.setdefault('checks',[]).append({'code':'OPTION_RESOURCE_CHANGED','message':'期权预留改变，须重新检查ETF计划'})
                book.connection.execute('UPDATE plans SET check_status=?,payload=? WHERE plan_id=?',('BLOCKED',canonical(payload),row['plan_id']))
            audit['result']=body
        book.record_task(identity,'SUCCESS' if not checks else 'BLOCKED',audit)
        return audit
