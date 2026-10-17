"""Predeclared bounded option studies using existing LEAN comparison and ffn."""
import json
from pathlib import Path
import shutil
from copy import deepcopy
from ..common import QuantError,decimal as D,digest,write_json,now_utc
from ..strategies.archive import source_fingerprint
from ..locks import publication_lock
from .packages import verify


def normalize(spec):
    fields={'schema_version','question','input_bundle','initial_cash','templates','windows','costs','selection_parameters','packages','exit_policy','cash_interest'}
    if not isinstance(spec,dict) or set(spec)!=fields or spec['schema_version']!=1 or not isinstance(spec['question'],str) or not spec['question'].strip():
        raise QuantError('INVALID_RESEARCH_PROTOCOL','研究需完整预声明问题、输入、区间、参数、成本及退出政策')
    from ..options.catalog import MONTHLY_RESEARCH
    templates=spec['templates'];windows=spec['windows'];costs=spec['costs']
    if (not isinstance(templates,list) or not 1<=len(templates)<=4 or len(set(templates))!=len(templates) or set(templates)-MONTHLY_RESEARCH
            or not isinstance(windows,list) or not 2<=len(windows)<=4 or not isinstance(costs,list) or not 1<=len(costs)<=3
            or len(templates)*len(windows)*len(costs)>24 or D(spec['initial_cash'])<=0
            or type(spec['packages']) is not int or not 1<=spec['packages']<=100 or spec['cash_interest']!=0 or spec['exit_policy']!='scheduled_close'):
        raise QuantError('INVALID_RESEARCH_PROTOCOL','实验上限24，固定资金/包数、零现金利息和统一约定平仓政策')
    if not isinstance(spec['selection_parameters'],dict) or set(spec['selection_parameters'])!=set(templates) or any(not isinstance(v,dict) for v in spec['selection_parameters'].values()):
        raise QuantError('INVALID_RESEARCH_PARAMETERS','须逐模板预声明完整参数，不在运行后补选')
    names=set();previous=None;assessment=False
    for window in windows:
        if not isinstance(window,dict) or set(window)!={'name','purpose','decision_start','decision_end'} or window['purpose'] not in {'development','assessment'} or window['name'] in names:
            raise QuantError('INVALID_RESEARCH_WINDOW','窗口需唯一名称、开发/评估用途及决策区间')
        import datetime
        try:start=datetime.date.fromisoformat(window['decision_start']);end=datetime.date.fromisoformat(window['decision_end'])
        except (TypeError,ValueError) as exc:raise QuantError('INVALID_RESEARCH_WINDOW','窗口日期无效') from exc
        if start>end or (previous and start<=previous) or (assessment and window['purpose']=='development'):
            raise QuantError('RESEARCH_WINDOW_OVERLAP','开发在前、评估在后，决策窗口不可重叠')
        previous=end;assessment|=window['purpose']=='assessment';names.add(window['name'])
    if not assessment or windows[0]['purpose']!='development':raise QuantError('MISSING_ASSESSMENT_WINDOW','至少一个开发和其后的评估窗口')
    names=set()
    for cost in costs:
        if not isinstance(cost,dict) or set(cost)!={'name','fee_per_contract','stock_commission_bps','spread_multiplier'} or cost['name'] in names:
            raise QuantError('INVALID_RESEARCH_COST','成本需唯一名称、期权佣金、股票费率和价差倍数')
        if D(cost['fee_per_contract'])<0 or D(cost['stock_commission_bps'])<0 or D(cost['spread_multiplier'])<1:
            raise QuantError('INVALID_RESEARCH_COST','费用非负，价差倍数至少1，不能静默改善报价')
        names.add(cost['name'])
    return spec



def coverage(calendar,cycles,window):
    expected={str(day.date()) for day in calendar.month_ends() if window['decision_start']<=str(day.date())<=window['decision_end']}
    dates=[m['decision_session'] for m in cycles if window['decision_start']<=m['decision_session']<=window['decision_end']]
    available=set(dates);missing=sorted(expected-available);unexpected=sorted(available-expected)
    return {'candidate_decisions':len(expected),'covered_decisions':len(expected & available),'missing_decisions':missing,
            'unexpected_decisions':unexpected,'duplicate_decisions':len(dates)!=len(available),
            'coverage_fraction':len(expected & available)/len(expected) if expected else None,
            'complete':bool(expected) and not missing and not unexpected and len(dates)==len(available)}


def freeze(directory,spec):
    spec=normalize(spec);root=Path(directory).absolute();manifest=verify(spec['input_bundle'])
    if manifest['checks']:raise QuantError('INPUT_PACKAGE_BLOCKED','研究包仍有未解决检查')
    body={'schema_version':1,'spec':spec,'source_hash':source_fingerprint(),'input_bundle_id':manifest['input_bundle_id']}
    body['protocol_id']=digest(body)
    if root.exists():
        old=json.loads((root/'protocol.json').read_text())
        if old!=body:raise QuantError('RESEARCH_PROTOCOL_FROZEN','研究参数或代码改变需新实验，不覆盖最终评估')
        return old
    root.mkdir(parents=True);shutil.copytree(spec['input_bundle'],root/'inputs');write_json(root/'protocol.json',body)
    return body


def run(directory,engine_root,dotnet):
    root=Path(directory).absolute();body=json.loads((root/'protocol.json').read_text());spec=normalize(body['spec'])
    if digest({k:v for k,v in body.items() if k!='protocol_id'})!=body['protocol_id'] or body['source_hash']!=source_fingerprint():
        raise QuantError('RESEARCH_PROTOCOL_CHANGED','冻结研究或代码身份改变，请另建实验')
    manifest=verify(root/'inputs')
    if manifest['input_bundle_id']!=body['input_bundle_id']:raise QuantError('INPUT_PACKAGE_CHANGED','研究输入身份改变')
    from ..data.store import DataStore
    from ..options.data import OptionDataStore
    from ..options.monthly import freeze_monthly
    from ..options.monthly_report import monthly_compare,load_monthly_report
    import pandas as pd
    scenario=json.loads((root/'inputs/scenario.json').read_text());_,_,calendar=DataStore(root/'inputs/data').load(manifest['roles']['signal'])
    store=OptionDataStore(root/'inputs/chains');rows=[]
    with publication_lock(root):
        for wi,window in enumerate(spec['windows']):
            months=[m for m in scenario['cycles'] if window['decision_start']<=m['decision_session']<=window['decision_end']]
            covered=coverage(calendar,scenario['cycles'],window)
            for ci,cost in enumerate(spec['costs']):
                for ti,template in enumerate(spec['templates']):
                    folder=root/f'window-{wi}-cost-{ci}-template-{ti}'
                    record={'window':window,'cost':cost,'template_id':template,'status':'BLOCKED','fair_ranking':False,**covered}
                    try:
                        if not covered['complete']:raise QuantError('INCOMPLETE_RESEARCH_COVERAGE','窗口缺少、重复或含非月末候选，不能只把成功月份作为覆盖分母')
                        if len(months)<2:raise QuantError('INSUFFICIENT_RESEARCH_COVERAGE','窗口至少两个可用月度决策，不能只报告成功片段')
                        folder.mkdir(exist_ok=True);signals=[]
                        for month in months:
                            request={'template_id':template,'underlying':scenario['spec']['option_underlying'],
                                'decision_at':(calendar.close(month['decision_session'])+pd.Timedelta(minutes=30)).isoformat(),
                                'parameters':spec['selection_parameters'][template]}
                            signal=freeze_monthly(store,month['snapshot_id'],request,calendar,folder/'signals',scope=body['protocol_id']+template,publication_delay_minutes=30)
                            if signal['status']!='FROZEN_FOR_RESEARCH':raise QuantError('RESEARCH_SELECTION_BLOCKED','候选链或规则不足，保留失败覆盖率')
                            signals.append(signal)
                        path=deepcopy(scenario['execution_path']);multiplier=D(cost['spread_multiplier'])
                        identities={leg['contract']['contract_id'] for signal in signals for leg in signal['selection']['legs']}
                        first=signals[0]['applicable_session']
                        last=str(max(d for d in calendar.sessions if d<=pd.Timestamp(signals[-1]['selection']['expiry'])-pd.Timedelta(days=signals[-1]['selection']['exit_days_before_expiry'])).date())
                        path['options']={key:{d:q for d,q in value.items() if first<=d<=last} for key,value in path['options'].items() if key in identities}
                        path['stocks']={key:{d:q for d,q in value.items() if first<=d<=last} for key,value in path['stocks'].items() if key==scenario['spec']['option_underlying']}
                        for quotes in path['options'].values():
                            for quote in quotes.values():
                                bid,ask=D(quote['bid']),D(quote['ask']);mid=(bid+ask)/2;half=(ask-bid)*multiplier/2
                                if mid-half<=0:raise QuantError('NONPOSITIVE_STRESS_QUOTE','价差压力导致非正bid，不假造可成交报价')
                                quote.update(bid=str(mid-half),ask=str(mid+half))
                        report_dir=folder/'comparison'
                        if report_dir.exists():report=load_monthly_report(report_dir)
                        else:report=monthly_compare(engine_root,dotnet,report_dir,signals,initial_cash=spec['initial_cash'],
                            fee_per_contract=cost['fee_per_contract'],stock_commission_bps=cost['stock_commission_bps'],
                            packages=[spec['packages']]*len(signals),execution_path=path)
                        record.update(status='PASSED',fair_ranking=True,metrics=report['metrics'],
                            covered_decisions=len(signals),candidate_decisions=covered['candidate_decisions'],report=str(report_dir),
                            meaning='同窗口同成本候选与持股/现金比较；不同窗口与成本不合并排名，不拼接净值')
                    except (QuantError,OSError,ValueError,KeyError) as exc:
                        record.update(code=getattr(exc,'code','RESEARCH_FAILED'),reason=str(exc),candidate_decisions=covered['candidate_decisions'])
                    rows.append(record);write_json(root/'progress.json',{'protocol_id':body['protocol_id'],'experiments':rows})
        result={'status':'PASSED' if all(r['status']=='PASSED' for r in rows) else 'INCOMPLETE','protocol_id':body['protocol_id'],
                'data_type':'synthetic_QuantLib_model_research' if scenario.get('model') else 'synthetic_imported_path_research','experiments':rows,'completed_at':now_utc(),
                'external_flows':0,'cash_interest':0,'automatic_parameter_search':False,'rank_across_windows':False,
                'meaning':'价差已包含于bid/ask成交，报告成本不从净值重复扣除；最终评估不用于自动选参。'}
        write_json(root/'result.json',result);return result
