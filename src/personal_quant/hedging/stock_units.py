"""Exact stock unit conversion from supplied active ledger facts, never orders."""
from ..common import QuantError,decimal as D,digest,utc


def _actions(events,symbol,origin_at,origin_seq,as_of):
    start,end=utc(origin_at),utc(as_of)
    if start>end:raise QuantError('INVALID_UNIT_TIME','原数量时点不能晚于换算时点')
    result=[];seen=set()
    for event in events:
        if event['kind']!='SPLIT' or event['symbol']!=symbol:continue
        clock=utc(event['effective_at'])
        if clock>end or clock<start:continue
        if clock==start:
            if origin_seq is None:raise QuantError('AMBIGUOUS_UNIT_TIME','同一时点拆股与数量需明确原账本序号')
            if event['seq']<=origin_seq:continue
        key=event['event_id']
        if key in seen:raise QuantError('DUPLICATE_UNIT_FACT','不能重复应用同一拆股事实')
        seen.add(key)
        if D(event['ratio'])<=0:raise QuantError('INVALID_UNIT_RATIO','拆股比例须严格为正')
        result.append(event)
    return sorted(result,key=lambda e:(utc(e['effective_at']),e['seq']))


def quantity(events,symbol,value,origin_at,as_of,*,origin_seq=None):
    """Return quantity in as_of units, preserving fractional shares exactly."""
    value=D(value)
    if value<0:raise QuantError('INVALID_UNIT_QUANTITY','数量换算须非负，方向另行保存')
    actions=_actions(events,symbol,origin_at,origin_seq,as_of);factor=D(1)
    for event in actions:factor*=D(event['ratio'])
    return dict(quantity=str(value*factor),factor=str(factor),actions=[
        dict(event_id=e['event_id'],seq=e['seq'],content_hash=digest({k:v for k,v in e.items() if k!='seq'})) for e in actions])


def stage_quantities(events,plan_id,lines,origin_at,as_of,*,origin_seq=None):
    """Convert frozen targets and each receipt separately; do not scale cash/fees."""
    expected={};filled={};proofs={}
    for line in lines:
        key=(line['symbol'],line['side'])
        if key in expected or line['side'] not in {'BUY','SELL'}:raise QuantError('INVALID_UNIT_LINES','原方向/标的必须唯一合法')
        value=quantity(events,key[0],line['quantity'],origin_at,as_of,origin_seq=origin_seq)
        expected[key]=D(value['quantity'])
        for action in value['actions']:proofs[action['event_id']]=action
    for event in events:
        if event.get('plan_id')!=plan_id or event['kind'] not in {'BUY','SELL'} or utc(event['effective_at'])>utc(as_of):continue
        key=(event['symbol'],event['kind'])
        if key not in expected:raise QuantError('UNRESOLVED_HEDGE_EXECUTION','原成交方向/标的与冻结阶段不符')
        value=quantity(events,key[0],event['quantity'],event['effective_at'],as_of,origin_seq=event['seq'])
        filled[key]=filled.get(key,D(0))+D(value['quantity'])
        for action in value['actions']:proofs[action['event_id']]=action
    if any(filled.get(k,D(0))>q for k,q in expected.items()):
        raise QuantError('UNRESOLVED_HEDGE_EXECUTION','换算后实际成交超过原数量，须核实而非重开')
    return dict(expected=expected,filled=filled,remaining={k:q-filled.get(k,D(0)) for k,q in expected.items() if q>filled.get(k,D(0))},
        actions=sorted(proofs.values(),key=lambda a:a['seq']))


def stage_basis(stage,body):
    clock=stage.get('unit_basis_at',body.get('as_of'))
    seq=stage.get('unit_basis_sequence',body.get('snapshot',{}).get('ledger_seq'))
    if not isinstance(clock,str) or not clock or (seq is not None and (type(seq) is not int or seq<0)):
        raise QuantError('INVALID_STOCK_UNIT_BASIS','原股票数量必须保留明确单位时点，未知前缀不补造')
    utc(clock)
    return clock,seq


def lines_at(events,lines,origin_at,as_of,*,origin_seq):
    return [{**line,'quantity':quantity(events,line['symbol'],line['quantity'],origin_at,as_of,origin_seq=origin_seq)['quantity']} for line in lines]


def rebase_stage(events,stage,body,as_of,sequence):
    """Revision-only physical unit basis; native source quantities stay unchanged."""
    origin,seq=stage_basis(stage,body)
    return {**stage,'lines':lines_at(events,stage['lines'],origin,as_of,origin_seq=seq),
            'native_lines':stage.get('native_lines',stage['lines']),
            'unit_basis_at':utc(as_of).isoformat(),'unit_basis_sequence':sequence}
