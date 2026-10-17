"""Shared scenario and chain services for CLI and Chinese dashboard."""
import json
import os
import shutil
import hashlib
from uuid import uuid4
from pathlib import Path
import pandas as pd
from ..common import QuantError, digest, now_utc, write_json
from ..locks import publication_lock
from .catalog import catalog, template
from .data import OptionDataStore
from .payoff import analyze
from .pricing import price


def scenario(request):
    if not isinstance(request,dict) or set(request)-{'template_id','parameters','legs','prices'}:
        raise QuantError('INVALID_SCENARIO','情景请求含未知字段')
    if ('template_id' in request)==('legs' in request):
        raise QuantError('INVALID_SCENARIO','请选择模板或显式腿之一')
    legs=template(request['template_id'],**request.get('parameters',{})) if 'template_id' in request else request['legs']
    result=analyze(legs,prices=request.get('prices'))
    result['request_hash']=digest(request)
    result['template_id']=request.get('template_id','custom_standard_legs')
    return result


def publish_report(root,request):
    result=scenario(request)
    # The output is a frozen scenario artifact; it cannot alter accounts/plans.
    root=Path(root);destination=root/result['request_hash']
    with publication_lock(root):
        if destination.exists():
            try:
                manifest=json.loads((destination/'scenario-manifest.json').read_text())
                if manifest['result_hash']!=digest(result) or manifest['request_hash']!=result['request_hash']:
                    raise QuantError('SCENARIO_VERSION_CONFLICT','同一请求结果不同，保留旧报告并显式修订参数/规则')
                for name,expected in manifest['files'].items():
                    if hashlib.sha256((destination/name).read_bytes()).hexdigest()!=expected:
                        raise QuantError('CORRUPT_SCENARIO_REPORT','旧情景报告内容变化，禁止覆盖')
            except (OSError,ValueError,KeyError) as exc:
                raise QuantError('CORRUPT_SCENARIO_REPORT','旧情景报告不完整，禁止作为成功结果') from exc
        else:
            pending=root/('.pending-'+uuid4().hex);pending.mkdir()
            try:
                write_json(pending/'scenario.json',result)
                pd.DataFrame(result['points']).to_csv(pending/'payoff.csv',index=False)
                write_json(pending/'scenario-manifest.json',{'kind':'option_scenario','data_type':'scenario_only',
                    'request':request,'request_hash':result['request_hash'],'generated_at':now_utc(),
                    'result_hash':digest(result),'no_account_writes':True,
                    'files':{name:hashlib.sha256((pending/name).read_bytes()).hexdigest() for name in ['scenario.json','payoff.csv']}})
                os.rename(pending,destination)
            finally:
                if pending.exists():shutil.rmtree(pending)
    return {**result,'report_path':str(destination)}


def command(args, config):
    if args.action=='wheel-state':
        from ..portfolio import Ledger
        from .wheel import decision
        if not args.file or not args.account_id or not args.as_of:
            raise QuantError('MISSING_ARGUMENT','Wheel阶段需file参数、account-id和as-of')
        path=Path(config.runtime_dir)/'account.sqlite'
        if not path.is_file():raise QuantError('UNKNOWN_ACCOUNT','请先明确建立并记录账户，不自动注入资金')
        book=Ledger(path,config.environment)
        try:return decision(book,args.account_id,args.as_of,json.loads(args.file.read_text()))
        finally:book.close()
    if args.action in {'greek-register','greek-assess'}:
        from ..hedging.greek_evidence import register,assess
        from ..portfolio.ledger import Ledger
        if not args.file:raise QuantError('MISSING_ARGUMENT','Greek核验需完整JSON请求')
        request=json.loads(args.file.read_text());book=Ledger(Path(config.runtime_dir)/'account.sqlite',config.environment)
        try:
            if args.action=='greek-register':
                if not args.destination or not args.commit:
                    raise QuantError('MISSING_ARGUMENT','Greek逐笔凭据登记需证据目录及commit')
                return register(book,request,args.destination)
            if args.commit or not isinstance(request,dict) or set(request)!={'item','contract','knowledge_cutoff'}:
                raise QuantError('INVALID_GREEK_EVIDENCE','Greek只读核验需item/contract/knowledge_cutoff，不接受commit')
            return assess(book,request['item'],request['contract'],request['knowledge_cutoff'])
        finally:book.close()
    if args.action in {'permissions-register','permissions-assess'}:
        from .permissions import register,assess
        from ..portfolio.ledger import Ledger
        if not args.file:raise QuantError('MISSING_ARGUMENT','权限核验需要file完整请求')
        request=json.loads(args.file.read_text());book=Ledger(Path(config.runtime_dir)/'account.sqlite',config.environment)
        try:
            if args.action=='permissions-register':
                if not args.destination or not args.commit:raise QuantError('MISSING_ARGUMENT','权限登记须证据目录destination及commit')
                return register(book,request,args.destination)
            if args.commit or not isinstance(request,dict) or set(request)!={'account_id','template_id','operation','as_of','contract_count','physical_cash','exit_days'}:
                raise QuantError('INVALID_OPTION_PERMISSION_REQUEST','权限审阅须完整操作请求，不能commit')
            return assess(book,**request)
        finally:book.close()
    if args.action=='source-register':
        from .source import register_source
        from ..portfolio.ledger import Ledger
        if not args.file or not args.destination or not args.commit:
            raise QuantError('MISSING_ARGUMENT','来源登记需完整file、证据目录destination及commit')
        book=Ledger(Path(config.runtime_dir)/'account.sqlite',config.environment)
        try:return register_source(book,json.loads(args.file.read_text()),args.destination)
        finally:book.close()
    if args.action=='account-report':
        from ..portfolio.ledger import Ledger
        from ..portfolio.report import report_from_store
        from ..data.store import DataStore
        from ..common import utc
        if not args.file or args.commit:
            raise QuantError('MISSING_ARGUMENT','账户估值报告需file；不接受成交commit')
        request=json.loads(args.file.read_text())
        if not isinstance(request,dict) or set(request)!={'account_id','as_of','option_valuation'}:
            raise QuantError('INVALID_OPTION_VALUATION','报告请求需account_id、as_of及option_valuation')
        if config.environment!='demo' and utc(request['as_of'])>utc(now_utc()):
            raise QuantError('FUTURE_ACCOUNT_EVENT','不能发布未来账户估值')
        book=Ledger(Path(config.runtime_dir)/'account.sqlite',config.environment)
        try:
            with publication_lock(book.path.parent):
                return report_from_store(book,request['account_id'],request['as_of'],DataStore(book.path.parent/'data'),
                    config,book.path.parent/'reports/account-latest',option_valuation=request['option_valuation'])
        finally:book.close()
    if args.action in {'exit-freeze','exit-simulate','exit-cancel'}:
        from .exit_tasks import preview_freeze,freeze_exit,execute_exit,cancel_exit
        from ..portfolio.ledger import Ledger
        if not args.file:raise QuantError('MISSING_ARGUMENT','退出任务需--file完整请求')
        if args.action!='exit-freeze' and not args.commit:raise QuantError('PREVIEW_REQUIRED','退出模拟/取消需显式--commit')
        if args.action=='exit-freeze' and args.commit and not args.expected_hash:raise QuantError('PREVIEW_REQUIRED','冻结提交需--expected-hash预检哈希')
        book=Ledger(Path(config.runtime_dir)/'account.sqlite',config.environment)
        try:
            store=OptionDataStore(Path(config.runtime_dir)/'options/chains');request=json.loads(args.file.read_text())
            if args.action=='exit-freeze':
                return freeze_exit(book,store,request,expected_hash=args.expected_hash) if args.commit else preview_freeze(book,store,request)
            return execute_exit(book,store,request) if args.action=='exit-simulate' else cancel_exit(book,request)
        finally:book.close()
    if args.action=='exit-review':
        from .management import preview_exit
        from ..portfolio.ledger import Ledger
        if not args.file or args.commit:raise QuantError('MISSING_ARGUMENT','退出审阅需--file完整请求，为只读入口，不接受commit')
        book=Ledger(Path(config.runtime_dir)/'account.sqlite',config.environment)
        try:return preview_exit(book,OptionDataStore(Path(config.runtime_dir)/'options/chains'),json.loads(args.file.read_text()))
        finally:book.close()
    if args.action=='plan-simulate':
        from .simulation import execute
        from ..portfolio.ledger import Ledger
        if not args.file or not args.commit:raise QuantError('MISSING_ARGUMENT','模拟需--file完整请求及显式--commit')
        book=Ledger(Path(config.runtime_dir)/'account.sqlite',config.environment)
        try:return execute(book,OptionDataStore(Path(config.runtime_dir)/'options/chains'),json.loads(args.file.read_text()))
        finally:book.close()
    if args.action=='manual-record':
        from ..portfolio.ledger import Ledger
        from .lifecycle import manual_action
        if not args.file or not args.commit:raise QuantError('PREVIEW_REQUIRED','人工事实记录需--file明确请求及--commit')
        book=Ledger(Path(config.runtime_dir)/'account.sqlite',config.environment)
        try:return manual_action(book,json.loads(args.file.read_text()))
        finally:book.close()
    if args.action in {'plan-review','pending-list','resolve-pending'}:
        from ..portfolio.ledger import Ledger
        from .lifecycle import review,resolve_pending
        book=Ledger(Path(config.runtime_dir)/'account.sqlite',config.environment)
        try:
            if book.connection.execute('SELECT version FROM schema_version').fetchone()[0]<5:
                raise QuantError('V19_NOT_ENABLED','需要显式启用v1.9')
            if args.action=='plan-review':
                if not args.plan_id:raise QuantError('MISSING_ARGUMENT','需要--plan-id')
                return review(book,args.plan_id,args.as_of or now_utc())
            if not args.account_id:raise QuantError('MISSING_ARGUMENT','需要--account-id')
            book._require_account(args.account_id)
            if args.action=='pending-list':
                return {'pending_events':[{'event_id':row['event_id'],'receipt_hash':digest(json.loads(row['payload'])),
                    'receipt':json.loads(row['payload']),'reason':row['reason']}
                    for row in book.connection.execute('SELECT * FROM pending_option_events WHERE account_id=?',(args.account_id,))]}
            if not args.commit or args.expected_sequence is None or not args.expected_hash or not args.event_id:
                raise QuantError('PREVIEW_REQUIRED','解决凭据需要明确event-id、commit、账户序号和原凭据哈希')
            return resolve_pending(book,args.account_id,args.event_id,expected_sequence=args.expected_sequence,expected_hash=args.expected_hash)
        finally:book.close()
    if args.action=='plan-activate':
        from .activation import activate
        from ..portfolio.ledger import Ledger
        if not args.file or not args.commit:raise QuantError('MISSING_ARGUMENT','激活需--file完整审阅请求及显式--commit')
        book=Ledger(Path(config.runtime_dir)/'account.sqlite',config.environment)
        try:return activate(book,OptionDataStore(Path(config.runtime_dir)/'options/chains'),json.loads(args.file.read_text()))
        finally:book.close()
    if args.action=='engine-assess':
        from .qualification import assess_engine
        if not args.file or not args.template_id:raise QuantError('MISSING_ARGUMENT','需要--file引擎verification.json及--template-id')
        return assess_engine(args.file,args.template_id)
    if args.action=='monthly-replay':
        from .monthly_replay import monthly_replay
        if not all((args.file,args.engine_root,args.dotnet,args.destination)) or args.capital is None or args.fee_per_contract is None:
            raise QuantError('MISSING_ARGUMENT','月度回放需冻结信号数组file、engine-root/dotnet/destination及capital/fee-per-contract')
        payload=json.loads(args.file.read_text());extra={}
        if isinstance(payload,dict):
            if not {'signals','packages','stock_basket','execution_path'}<=set(payload) or set(payload)-{'signals','packages','stock_basket','execution_path','final_lifecycle','retain_stock','rolling_end_session','wheel','wheel_end_session','prepare_stock'}:
                raise QuantError('INVALID_MONTHLY_REPLAY','扩展回放文件需signals/packages/stock_basket/execution_path')
            extra={key:value for key,value in payload.items() if key!='signals'};payload=payload['signals']
        return monthly_replay(args.engine_root,args.dotnet,args.destination,payload,
            initial_cash=args.capital,fee_per_contract=args.fee_per_contract,
            stock_commission_bps=args.stock_commission_bps or 0,**extra)
    if args.action=='monthly-compare':
        from .monthly_report import monthly_compare
        if not all((args.file,args.engine_root,args.dotnet,args.destination)) or any(value is None for value in (args.capital,args.fee_per_contract,args.stock_commission_bps)):
            raise QuantError('MISSING_ARGUMENT','月度比较需file/engine-root/dotnet/destination及显式capital/fee-per-contract/stock-commission-bps')
        payload=json.loads(args.file.read_text());extra={}
        if isinstance(payload,dict):
            if not {'signals','packages','stock_basket','execution_path'}<=set(payload) or set(payload)-{'signals','packages','stock_basket','execution_path','final_lifecycle','retain_stock','prepare_stock'}:
                raise QuantError('INVALID_MONTHLY_REPLAY','扩展比较文件需signals/packages/stock_basket/execution_path')
            extra={key:value for key,value in payload.items() if key!='signals'};payload=payload['signals']
        return monthly_compare(args.engine_root,args.dotnet,args.destination,payload,
            initial_cash=args.capital,fee_per_contract=args.fee_per_contract,stock_commission_bps=args.stock_commission_bps,**extra)
    if args.action=='monthly-forward':
        from .forward import freeze_forward
        from ..data.calendar import Calendar
        from ..portfolio.ledger import Ledger
        from ..common import utc
        from datetime import timedelta
        if (not all((args.file,args.snapshot_id,args.account_id)) or args.publication_delay_minutes is None
                or args.max_generation_delay_minutes is None or not args.commit):
            raise QuantError('MISSING_ARGUMENT','前向月末冻结需账户/规则/真实快照/延迟、最大实际生成窗口及显式commit')
        request=json.loads(args.file.read_text());day=utc(request['decision_at']).date()
        calendar=Calendar.market(str(day-timedelta(days=7)),str(day+timedelta(days=40)))
        book=Ledger(Path(config.runtime_dir)/'account.sqlite',config.environment)
        try:return freeze_forward(book,OptionDataStore(Path(config.runtime_dir)/'options/chains'),args.snapshot_id,
            request,calendar,Path(config.runtime_dir)/'options/monthly-forward',args.account_id,
            publication_delay_minutes=args.publication_delay_minutes,max_generation_delay_minutes=args.max_generation_delay_minutes)
        finally:book.close()
    if args.action=='monthly-freeze':
        from .monthly import freeze_monthly
        from ..data.calendar import Calendar
        from ..common import utc
        if not all((args.file,args.snapshot_id,args.scope)) or args.publication_delay_minutes is None:
            raise QuantError('MISSING_ARGUMENT','月度冻结需file/snapshot-id/scope及显式publication-delay-minutes')
        request=json.loads(args.file.read_text())
        date=utc(request['decision_at']).date()
        from datetime import timedelta
        calendar=Calendar.market(str(date-timedelta(days=7)),str(date+timedelta(days=40)))
        with publication_lock(config.runtime_dir):
            return freeze_monthly(OptionDataStore(Path(config.runtime_dir)/'options/chains'),args.snapshot_id,
                request,calendar,Path(config.runtime_dir)/'options/monthly',scope=args.scope,
                publication_delay_minutes=args.publication_delay_minutes)
    if args.action=='fixture-replay':
        from .replay import fixture_replay
        if not all((args.file,args.engine_root,args.dotnet,args.destination,args.snapshot_id)) or args.capital is None or args.fee_per_contract is None:
            raise QuantError('MISSING_ARGUMENT','合成引擎验证需file/engine-root/dotnet/destination/snapshot-id以及显式capital/fee-per-contract')
        request=json.loads(args.file.read_text());extra={}
        if not isinstance(request,dict):raise QuantError('INVALID_OPTION_REPLAY','诊断请求必须为对象')
        if 'selection' in request:
            if set(request)!={'selection','templates','minimum_spread_width'}:raise QuantError('INVALID_OPTION_REPLAY','扩展诊断须显式selection/templates/minimum_spread_width')
            extra={key:value for key,value in request.items() if key!='selection'};request=request['selection']
        return fixture_replay(args.engine_root,args.dotnet,args.destination,
            OptionDataStore(Path(config.runtime_dir)/'options/chains'),args.snapshot_id,request,
            initial_cash=args.capital,fee_per_contract=args.fee_per_contract,exercise_case=args.include_exercise,
            market_on_close=args.market_on_close,**extra)
    if args.action=='plan-draft':
        from ..portfolio.ledger import Ledger
        from .plans import draft
        if not all((args.file,args.account_id,args.snapshot_id)):raise QuantError('MISSING_ARGUMENT','需要--file草案配置、--account-id和--snapshot-id')
        book=Ledger(Path(config.runtime_dir)/'account.sqlite',config.environment)
        try:return draft(book,OptionDataStore(Path(config.runtime_dir)/'options/chains'),args.snapshot_id,args.account_id,json.loads(args.file.read_text()))
        finally:book.close()
    if args.action=='import-facts':
        from ..portfolio.ledger import Ledger
        from ..portfolio.imports import event_csv
        from .ledger import import_facts,normalize_option_event
        if not args.file or not args.account_id:raise QuantError('MISSING_ARGUMENT','需要--file标准期权事件CSV和--account-id')
        rows=event_csv(args.file.read_bytes());identity=digest(rows)
        book=Ledger(Path(config.runtime_dir)/'account.sqlite',config.environment)
        try:
            book._require_account(args.account_id)
            if book.connection.execute('SELECT version FROM schema_version').fetchone()[0]<5:
                raise QuantError('V19_NOT_ENABLED','期权事实预检需要v1.9')
            if args.commit:
                if args.expected_hash!=identity or args.expected_sequence is None:
                    raise QuantError('PREVIEW_REQUIRED','须提供预检文件哈希及账户序号才能提交事实/待核实凭据')
                from .receipts import import_batch
                request=dict(request_id='csv:'+identity+':'+str(args.expected_sequence),rows=rows,
                    expected_sequence=args.expected_sequence,expected_hash=identity)
                audit=import_batch(book,args.account_id,request,args.as_of or now_utc())
                return {**audit['result'],'receipt_audit_id':audit['audit_task_id'],
                    'has_intermediate_anomaly':audit['risk_history']['has_intermediate_anomaly']}
            supported=[];pending=[]
            for row in rows:
                try:normalize_option_event(book,row,args.account_id);supported.append(row)
                except QuantError as exc:pending.append({'event_id':row.get('event_id'),'reason':str(exc),'code':exc.code})
            return {'read_only':True,'expected_hash':identity,'expected_sequence':book.sequence(args.account_id),
                    'preview':book.preview(args.account_id,supported,args.as_of or now_utc(),{}) if supported else None,
                    'pending_events':pending,'status':'REVIEW_REQUIRED' if pending else 'READY_FOR_REVIEW'}
        finally:book.close()
    if args.action=='engine-smoke':
        from .engine import smoke
        if not all((args.engine_root,args.dotnet,args.destination)):
            raise QuantError('MISSING_ARGUMENT','需要--engine-root、--dotnet、--destination新目录')
        return smoke(args.engine_root,args.dotnet,args.destination)
    if args.action=='catalog':return {'data_type':'catalog','families':catalog()}
    if args.action=='register-contracts':
        from ..portfolio.ledger import Ledger
        from .ledger import register_contract
        if not args.contracts:raise QuantError('MISSING_ARGUMENT','需要--contracts合约JSON')
        book=Ledger(Path(config.runtime_dir)/'account.sqlite',config.environment)
        try:return {'contracts':[register_contract(book,body,args.contract_evidence_file).version_hash for body in json.loads(args.contracts.read_text())]}
        finally:book.close()
    if args.action in {'scenario','price','stress','risk-compare'}:
        if not args.file:raise QuantError('MISSING_ARGUMENT','需要--file JSON请求')
        request=json.loads(args.file.read_text())
        if args.action=='risk-compare':
            from .risk_lab import compare
            return compare(request)
        if args.action=='stress':
            from .stress import evaluate
            return evaluate(request)
        if args.action=='price':return price(**request)
        return publish_report(args.destination,request) if args.destination else scenario(request)
    store=OptionDataStore(Path(config.runtime_dir)/'options'/'chains')
    if args.action=='select':
        from .selection import select
        if not args.snapshot_id or not args.file:raise QuantError('MISSING_ARGUMENT','需要--snapshot-id和--file选约规则JSON')
        return select(store,args.snapshot_id,json.loads(args.file.read_text()))
    if args.action=='import-chain':
        if not all((args.file,args.contracts,args.metadata)):
            raise QuantError('MISSING_ARGUMENT','需要--file报价CSV、--contracts合约JSON、--metadata来源JSON')
        if config.environment=='real' and json.loads(args.metadata.read_text()).get('data_type')!='real_market':
            raise QuantError('ENVIRONMENT_MISMATCH','真实工作区不能导入合成期权链')
        return store.save(json.loads(args.contracts.read_text()),pd.read_csv(args.file),json.loads(args.metadata.read_text()))
    if args.action=='check-chain':
        if not args.snapshot_id:raise QuantError('MISSING_ARGUMENT','需要--snapshot-id')
        return store.check(args.snapshot_id,args.as_of or now_utc(),max_age_seconds=args.max_age_seconds,
            max_underlying_skew_seconds=args.max_underlying_skew_seconds,max_spread_fraction=args.max_spread_fraction)
    raise QuantError('UNKNOWN_OPTION_COMMAND','未知期权操作')
