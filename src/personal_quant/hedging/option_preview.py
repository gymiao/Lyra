"""Freeze selected quotes and ledger-backed protection before quantity research."""
from ..common import QuantError,decimal as D,utc,digest
from ..data.store import DataStore
from ..options.contracts import OptionContract
from ..options.data import OptionDataStore
from ..options.selection import select,FIELDS as SELECTION_PARAMETERS
from ..options.source import assess_source
from ..options.lifecycle import refresh
from .allocation_store import latest,resources
from .coverage_service import account_coverage,FIELDS as COVERAGE_FIELDS
from .option_sizing import option_candidate,LIMITS

FIELDS={'snapshot_id','selection_request','coverage_request','greeks','limits','funding_quote'}


def preview_options(book,account_id,risk,spec,method,request):
    if (not isinstance(request,dict) or set(request)!=FIELDS
            or not isinstance(request['selection_request'],dict)
            or set(request['selection_request'])!={'template_id','underlying','decision_at','parameters'}
            or not isinstance(request['selection_request']['parameters'],dict)
            or set(request['selection_request']['parameters'])!=SELECTION_PARAMETERS
            or not isinstance(request['limits'],dict) or set(request['limits'])!=LIMITS
            or not isinstance(request['coverage_request'],dict)
            or set(request['coverage_request']) not in (COVERAGE_FIELDS,COVERAGE_FIELDS|{'security_versions'})):
        raise QuantError('INVALID_HEDGE_OPTION_REQUEST','期权预览需确切链/选约/账户覆盖、Greek及完整参数')
    store=OptionDataStore(book.path.parent/'options/chains')
    with book.transaction():
        if risk['ledger_seq']!=book.sequence(account_id):raise QuantError('STALE_LEDGER_SEQUENCE','期权候选需当前账户前缀')
        if utc(request['selection_request']['decision_at'])!=utc(risk['as_of']):
            raise QuantError('HEDGE_OPTION_TIME_MISMATCH','选约与风险决策时点必须相同')
        parameters=request['selection_request']['parameters'];policy=spec.content()
        if (parameters['minimum_dte']!=policy['min_days_to_expiry'] or parameters['maximum_dte']!=policy['max_days_to_expiry']
                or parameters['exit_days_before_expiry']!=policy['exit_days_before_expiry']):
            raise QuantError('HEDGE_OPTION_RULE_MISMATCH','选约到期/退出窗口必须与目标一致')
        selection=select(store,request['snapshot_id'],request['selection_request'])
        contracts,_,metadata,_=store.load(request['snapshot_id'])
        terms=[OptionContract.from_dict(x['contract']) for x in selection['legs']]
        if metadata['data_type']!='synthetic' and not book.connection.execute("SELECT 1 FROM sqlite_master WHERE name='source_qualifications'").fetchone():
            assessment={'status':'UNQUALIFIED','actual_source_qualified':False,'checks':['OPTION_SOURCE_QUALIFICATION_REQUIRED']}
        else:assessment=assess_source(book,metadata,terms,risk['knowledge_cutoff'])
        query=request['coverage_request']
        if (query.get('ledger_seq')!=risk['ledger_seq'] or utc(query['as_of'])!=utc(risk['as_of'])
                or utc(query['knowledge_cutoff'])<utc(risk['knowledge_cutoff']) or query['ledger_view']!=risk['ledger_view']
                or risk['ledger_view']=='known_then' and utc(query['knowledge_cutoff'])!=utc(risk['knowledge_cutoff'])):
            raise QuantError('HEDGE_COVERAGE_BASIS_MISMATCH','保护覆盖必须是同一账户/风险时点/前缀和明确知识视图')
        prior=latest(book,account_id);expected=prior['allocations'] if prior else []
        if query.get('allocations')!=expected:
            raise QuantError('HEDGE_ALLOCATION_BASIS_MISMATCH','保护候选必须使用完整当前持久分配集，不能自填或漏掉已有保护')
        coverage=account_coverage(book,account_id,query)
        underlying=selection['underlying'];stock_id=query['security_ids'].get(underlying)
        groups={}
        for row in expected:
            if row['security_id']!=stock_id or not utc(row['valid_from'])<=utc(risk['as_of'])<utc(row['valid_until']):continue
            group=groups.setdefault(row['parent_id'],dict(parent_id=row['parent_id'],actual_put_shares='0',actual_call_shares='0',
                pending_put_shares='0',pending_call_shares='0',valid_until=row['valid_until']))
            field=('actual' if row['state']=='actual' else 'pending')+('_put_shares' if row['role']=='put_protection' else '_call_shares')
            group[field]=str(D(group[field])+D(row['share_end'])-D(row['share_start']))
            if utc(row['valid_until'])<utc(group['valid_until']):group['valid_until']=row['valid_until']
        checks=list(assessment['checks'])
        registered={e['symbol']:OptionContract.from_dict(e['contract']) for e in book.active_events(account_id,risk['as_of'],risk['ledger_seq']) if e['kind'].startswith('OPTION_')}
        for item in coverage['unallocated_actual_contracts']:
            c=registered[item['contract_id']]
            if c.underlying==underlying and c.right=='PUT' and D(item['signed_contracts'])>0:
                checks.append('UNALLOCATED_PROTECTION_REVIEW_REQUIRED')
        if book.connection.execute('SELECT version FROM schema_version').fetchone()[0]>=5:
            for body in refresh(book,account_id,risk['as_of'],persist=False,ledger_seq=risk['ledger_seq']):
                if not body.get('manual_execution',{}).get('pending'):continue
                for leg in body['selection']['legs']:
                    c=OptionContract.from_dict(leg['contract'])
                    if c.underlying!=underlying:continue
                    if body['plan_id'] not in query['inflight_plan_ids'] or not any(r['contract_id']==c.contract_id and r['state']=='inflight' for r in expected):
                        checks.append('UNALLOCATED_INFLIGHT_PROTECTION')
        _,_,calendar=DataStore(book.path.parent/'data').load(risk['valuation_snapshot_id'])
        mark_session=risk['valuation']['quotes'].get(underlying,{}).get('session')
        for leg in selection['legs']:
            quote=leg['reference_quote']
            if any(utc(quote[k])>utc(risk['knowledge_cutoff']) for k in ('exchange_timestamp','available_at','received_at')):
                checks.append('OPTION_QUOTE_NOT_KNOWN')
            if mark_session is None or abs((utc(quote['underlying_timestamp'])-utc(calendar.close(mark_session))).total_seconds())>float(request['limits']['max_mark_skew_seconds']):
                checks.append('HEDGE_UNDERLYING_TIME_MISMATCH')
            raw=risk['valuation']['prices'].get(underlying)
            if raw is None or abs(D(quote['underlying_price'])/D(raw)-1)>D(parameters['max_underlying_price_fraction']):
                checks.append('HEDGE_UNDERLYING_PRICE_MISMATCH')
        current=dict(risk);current['account']=book.snapshot(account_id,risk['as_of'],risk['account']['prices'],ledger_seq=risk['ledger_seq'])
        basis=resources(book,account_id)
    result=option_candidate(current,spec,method,selection,list(groups.values()),request['greeks'],request['limits'],funding_quote=request['funding_quote'])
    result.update(protection_basis=coverage['coverage_id'],allocation_version=prior['version_hash'] if prior else None,
                  resource_hash=basis,source_assessment=assessment,option_snapshot_id=request['snapshot_id'],
                  greek_qualification='明确输入的研究参考，供应商Greek/模型资格仍待独立核验')
    if checks:result.update(status='NO_FEASIBLE_HEDGE',checks=sorted(set(result['checks']+checks)),trades=[])
    result['candidate_id']=digest({k:v for k,v in result.items() if k!='candidate_id'})
    return result
