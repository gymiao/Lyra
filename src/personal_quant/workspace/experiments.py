"""Read-only comparisons of complete, separately funded simulations."""
import json
import math
from pathlib import Path
import sqlite3
import pandas as pd
import ffn
from ..common import QuantError,decimal as D,digest
from .service import read_workspace,create,status
from ..portfolio.report import load_account_report
from ..portfolio import Ledger


def clone(directory,destination):
    root,identity,config,_=read_workspace(directory)
    if identity['kind']=='etf':
        from .packages import import_prices
        from .inputs import require
        from ..data.store import DataStore
        import tempfile,shutil
        destination=Path(destination).absolute();destination.parent.mkdir(parents=True,exist_ok=True)
        staging=Path(tempfile.mkdtemp(prefix='.clone-input-',dir=destination.parent))
        try:
            store=DataStore(root/config.runtime_dir/'data');book=Ledger.read_only(root/config.runtime_dir/'account.sqlite','demo')
            try:
                run=book.connection.execute('SELECT run_id FROM simulation_runs ORDER BY updated_at DESC LIMIT 1').fetchone() if book.connection.execute("SELECT 1 FROM sqlite_master WHERE name='simulation_runs'").fetchone() else None
                roles={k:v['snapshot_id'] for k,v in require(book,store,run[0])['roles'].items()} if run else {k:store.load_role(k)[1]['snapshot_id'] for k in ('signal','execution','valuation')}
            finally:book.close()
            import_prices({'schema_version':1,'data_root':str(store.root),'roles':roles},staging/'package')
            return create(destination,{'schema_version':1,'account_id':identity['account_id'],'initial_cash':identity['initial_cash'],
                                      'kind':'etf','input_bundle':str(staging/'package')},config)
        finally:shutil.rmtree(staging)
    return create(destination,{'schema_version':1,'account_id':identity['account_id'],
        'initial_cash':identity['initial_cash'],'kind':identity['kind']},config)


def curve(directory,run_id,*,include_execution=False):
    try:return _curve(directory,run_id,include_execution=include_execution)
    except QuantError:raise
    except (OSError,ValueError,KeyError,TypeError,sqlite3.Error) as exc:
        raise QuantError('CORRUPT_EXPERIMENT','实验报告/账本或引用缺失，不能比较：'+str(exc)) from exc


def _curve(directory,run_id,*,include_execution=False):
    root,identity,config,_=read_workspace(directory)
    book=Ledger.read_only(root/config.runtime_dir/'account.sqlite','demo');con=book.connection
    try:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='simulation_runs'").fetchone():
            raise QuantError('INCOMPLETE_EXPERIMENT','工作区尚未建立模拟运行')
        run=con.execute('SELECT * FROM simulation_runs WHERE run_id=?',(run_id,)).fetchone()
        if not run or run['status']!='COMPLETED':raise QuantError('INCOMPLETE_EXPERIMENT','比较需要已完成的明确运行')
        funding=con.execute("SELECT payload FROM events WHERE account_id=? AND json_extract(payload,'$.kind') IN ('DEPOSIT','WITHDRAWAL')",(identity['account_id'],)).fetchall()
        if len(funding)!=1 or D(json.loads(funding[0][0])['amount'])!=D(identity['initial_cash']):
            raise QuantError('EXTERNAL_FLOWS_PRESENT','含额外入出金的账户不能按研究净值直接比较')
        rows=con.execute('SELECT session,details FROM simulation_checkpoints WHERE run_id=? ORDER BY session',(run_id,)).fetchall()
        if not rows:raise QuantError('EMPTY_EXPERIMENT','尚无完整观察点')
        values=[]
        for row in rows:
            detail=json.loads(row['details'])
            report=load_account_report(root/config.runtime_dir/'reports/account-latest',detail['report_id'])
            clock_ok=(pd.Timestamp(report['as_of'])==pd.Timestamp(detail['as_of']) if identity['kind']=='options'
                      else str(pd.Timestamp(report['as_of']).tz_convert('America/New_York').date())==row['session'])
            if (report['equity']!=detail['equity'] or report['account_id']!=identity['account_id']
                    or report['source_hash']!=run['source_hash']
                    or not clock_ok):
                raise QuantError('CORRUPT_EXPERIMENT','检查点与已发布报告的身份、时间或金额不同')
            snapshot=book.snapshot(identity['account_id'],report['as_of'],report.get('prices',{}))
            fields=('equity','settled_cash','receivables','payables','positions','option_positions',
                    'deposits','withdrawals','investment_pnl','option_market_value')
            if (not report.get('effective_events_hash') or report['effective_events_hash']!=digest(book.active_events(identity['account_id'],report['as_of']))
                    or any(report.get(key)!=snapshot.get(key) for key in fields) or snapshot['anomalies']):
                raise QuantError('STALE_EXPERIMENT','历史报告的金融事实已变化；先重建可追溯实验，不能比较旧曲线')
            values.append(report['equity'])
        if any(value is None for value in values):raise QuantError('INCOMPLETE_VALUATION','模拟观察点缺估值')
        initial=pd.Timestamp(rows[0]['session'])-pd.Timedelta(days=1)
        series=pd.Series([float(identity['initial_cash']),*map(float,values)],index=[initial,*[pd.Timestamp(row['session']) for row in rows]])
        if identity['kind']=='options':
            from .option_experiments import describe
            try:policy,execution=describe(book,root/config.runtime_dir,identity,config,run,rows,series)
            except QuantError:raise
            except (OSError,ValueError,KeyError,TypeError) as exc:
                raise QuantError('CORRUPT_EXPERIMENT','期权实验归档缺失或不完整，不能进行严格比较：'+str(exc)) from exc
            return (series,policy,execution) if include_execution else (series,policy)
        from .inputs import require as require_inputs,verify_checkpoints
        from ..data.store import DataStore
        basis=require_inputs(book,DataStore(root/config.runtime_dir/'data'),run_id)
        verify_checkpoints(book,run_id,basis)
        policy={key:config.content()[key] for key in ('currency','market','commission_bps','slippage_bps','fixed_fee',
            'settlement_lag_sessions','lot_size','publication_delay_minutes','volatility_annual_factor')}
        policy.update(initial_cash=identity['initial_cash'],snapshot=basis['roles']['signal']['snapshot_id'],
                      input_bundle_id=basis['input_bundle_id'],run_mode=basis['run_mode'],source_hash=run['source_hash'],
                      dates=[str(day.date()) for day in series.index],engine='account_simulator',cash_interest=0,data_type=basis['roles']['signal']['data_type'])
        events=book.active_events(identity['account_id'],report['as_of'])
        execution={'recorded_cost':str(sum((D(e['fee'])+(D(e['amount']) if e['kind']=='FEE' else D(0)) for e in events),D(0))),
            'meaning':'账本已扣费用；ETF模拟成交费用按配置包含佣金/滑点，不再次从曲线扣除'}
        return (series,policy,execution) if include_execution else (series,policy)
    finally:book.close()


def compare(request):
    if not isinstance(request,list) or not 2<=len(request)<=7:raise QuantError('INVALID_COMPARISON','需要2至7个明确实验')
    curves={};policy=None;identities=set();execution={}
    for item in request:
        if (not isinstance(item,dict) or set(item)!={'name','workspace','run_id'}
                or any(not isinstance(value,str) or not value for value in item.values()) or item['name'] in curves):
            raise QuantError('INVALID_COMPARISON','名称须唯一，并提供工作区与run-id')
        root,body,_,_=read_workspace(item['workspace'])
        if body['workspace_id'] in identities:raise QuantError('DUPLICATE_EXPERIMENT','同一工作区不可重复充当独立组合')
        identities.add(body['workspace_id']);series,current,cost=curve(root,item['run_id'],include_execution=True)
        if policy is not None and current!=policy:
            differences=[key for key in sorted(set(current)|set(policy)) if current.get(key)!=policy.get(key)]
            raise QuantError('INCOMPARABLE_EXPERIMENT','资金/数据/时间/执行口径不同：'+', '.join(differences))
        curves[item['name']]=series;policy=current;execution[item['name']]=cost
    frame=pd.DataFrame(curves);metrics={}
    for name,series in curves.items():
        stats=ffn.calc_stats(series,annualization_factor=policy['volatility_annual_factor'])
        def number(value):return None if value is None or not math.isfinite(float(value)) else float(value)
        metrics[name]={'total_return':float(series.iloc[-1]/series.iloc[0]-1),'cagr':number(stats.cagr),
                       'max_drawdown':number(stats.max_drawdown),'annual_volatility':number(stats.daily_vol),
                       'observations':len(series)-1,'calendar_days':(series.index[-1]-series.index[0]).days,
                       'short_sample_annualization':(series.index[-1]-series.index[0]).days<365}
    return {'status':'PASSED','read_only':True,'data_type':'synthetic_historical_simulation','policy':policy,
            'request_hash':digest(request),'request':request,'metrics':metrics,'execution':execution,
            'meaning':'独立账户、相同资金及执行/数据口径比较；无外部资金流，初始资金点不是投资收益。未作收益排名或自动选策略。',
            'curves':{name:{str(day.date()):float(value) for day,value in series.items()} for name,series in curves.items()}}
