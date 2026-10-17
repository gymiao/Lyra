"""Point-in-time bid/ask marks for actual account positions, never estimated fills."""
import json
from ..common import QuantError, decimal as D, utc, digest
from .contracts import OptionContract
from .data import quality
from .source import assess_source

LIMITS = {'max_age_seconds','max_underlying_skew_seconds','max_spread_fraction','max_leg_skew_seconds'}


def planning_marks(book,account_id,prices,as_of,request,reference_at,*,knowledge_cutoff=None):
    """Explicit qualified marks shared by stock planning and stock simulation."""
    state=book.snapshot(account_id,as_of)
    if request is not None and (not isinstance(request,dict) or set(request)!={'snapshot_id','limits'}
                               or not isinstance(request['snapshot_id'],str) or not request['snapshot_id']):
        raise QuantError('INVALID_OPTION_VALUATION','期权估值必须显式提供snapshot_id和limits')
    if not state.get('option_positions'):
        return dict(prices),{'status':'NO_OPTION_POSITIONS','prices':{},'executable':False}
    if request is None:
        raise QuantError('OPTION_VALUATION_REQUEST_REQUIRED','持有期权时须显式提供本次合格报价；不继承旧估值')
    from .data import OptionDataStore
    marks=quote_set(book,account_id,OptionDataStore(book.path.parent/'options/chains'),
                    request['snapshot_id'],as_of,request['limits'],knowledge_cutoff=knowledge_cutoff)
    if marks['status']!='COMPLETE':
        raise QuantError('INCOMPLETE_OPTION_VALUATION','期权估值检查不通过：'+','.join(marks['checks']))
    if set(prices)&set(marks['prices']):
        raise QuantError('OPTION_SECURITY_ID_CONFLICT','股票与期权估值标识冲突')
    for item in marks['quotes'].values():
        quote=item['quote']
        if abs((utc(quote['underlying_timestamp'])-utc(reference_at)).total_seconds())>float(request['limits']['max_underlying_skew_seconds']):
            raise QuantError('OPTION_STOCK_TIME_MISMATCH','股票收盘参考价与期权标的报价时点不一致')
    return {**prices,**marks['prices']},marks


def quote_set(book, account_id, store, snapshot_id, as_of, limits, *, ledger_seq=None,knowledge_cutoff=None):
    knowledge=utc(knowledge_cutoff) if knowledge_cutoff is not None else utc(as_of)
    if knowledge<utc(as_of):
        raise QuantError('INVALID_OPTION_VALUATION','处理知识截止不能早于估值所属时点')
    if not isinstance(limits,dict) or set(limits)!=LIMITS or any(D(v)<0 for v in limits.values()):
        raise QuantError('INVALID_OPTION_VALUATION','期权估值需完整非负报价检查参数')
    if D(limits['max_spread_fraction'])>1:
        raise QuantError('INVALID_OPTION_VALUATION','估值价差上限不能大于1')
    if ledger_seq is not None and (type(ledger_seq) is not int or not 0<=ledger_seq<=book.sequence(account_id)):
        raise QuantError('INVALID_LEDGER_SEQUENCE','期权估值前缀必须是该账户已存在的非负序号')
    state=book.snapshot(account_id,as_of,ledger_seq=ledger_seq);positions=state.get('option_positions',{})
    result={'status':'NO_OPTION_POSITIONS','snapshot_id':None,'as_of':utc(as_of).isoformat(),
            'prices':{},'quotes':{},'checks':[],'mark_basis':'bid_ask_mid_per_quote_unit',
            'meaning':'期权估值参考中价；不等同于可成交价格，不重复乘以张数或合约乘数',
            'limits':limits,'executable':False}
    if ledger_seq is not None:result['ledger_seq']=ledger_seq
    if knowledge_cutoff is not None:
        result['knowledge_cutoff']=knowledge.isoformat()
        result['meaning']+='；成交状态重述，允许迟到收盘凭据，不宣称其事前已可用'
    if not positions:return result
    contracts,records,metadata,_=store.load(snapshot_id)
    terms={}
    for event in book.active_events(account_id,as_of,ledger_seq=ledger_seq):
        if event['kind'].startswith('OPTION_'):
            terms[event['symbol']]=OptionContract.from_dict(event['contract'])
    assessment=assess_source(book,metadata,[terms[s] for s in positions],as_of)
    result.update(snapshot_id=snapshot_id,data_type=metadata['data_type'],source=metadata['source'],source_assessment=assessment)
    checks=list(assessment['checks']);marks={};used=[]
    for symbol in positions:
        c=terms[symbol];status=[]
        if symbol not in contracts or contracts[symbol].version_hash!=c.version_hash:
            status.append('OPTION_UNIT_CONFLICT')
        candidates=[r for r in records if r['contract_id']==symbol and utc(r['exchange_timestamp'])<=utc(as_of)
                    and all(utc(r[k])<=knowledge for k in ('available_at','received_at'))]
        row=max(candidates,key=lambda r:utc(r['exchange_timestamp'])) if candidates else None
        if row is None:status.append('MISSING_AVAILABLE_OPTION_QUOTE')
        else:
            status.extend(quality(row,c,as_of,max_age_seconds=float(limits['max_age_seconds']),
                max_underlying_skew_seconds=float(limits['max_underlying_skew_seconds']),
                max_spread_fraction=limits['max_spread_fraction'],knowledge_cutoff=knowledge))
        result['quotes'][symbol]={'status':'BLOCKED' if status else 'CHECKED','checks':sorted(set(status)),
                                 'contract_version':c.version_hash,'quote':row}
        checks.extend(code+':'+symbol for code in status)
        if not status:
            marks[symbol]=str((D(row['bid'])+D(row['ask']))/2);used.append(row)
    if len(used)>1 and (max(utc(r['exchange_timestamp']) for r in used)-min(utc(r['exchange_timestamp']) for r in used)).total_seconds()>float(limits['max_leg_skew_seconds']):
        checks.append('OPTION_VALUATION_TIME_MISMATCH')
    # Publish no partial mark set as a complete portfolio valuation.
    result['checks']=sorted(set(checks));result['prices']=marks if not checks else {}
    result['status']='INCOMPLETE' if checks else 'COMPLETE'
    result['valuation_id']=digest(result)
    return result
