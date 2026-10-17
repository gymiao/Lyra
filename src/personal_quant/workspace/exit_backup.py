"""Validate archived prefix exits without depending on installed current source."""
import hashlib
import json
from ..common import QuantError,decimal as D,digest,utc
from ..options.contracts import OptionContract
from ..options.engine import LEAN_COMMIT


def validate(root,book,audit,proposal,*,complete=True):
    if (book.environment!='demo' or set(audit['request'])!={'exit_id','adapter'}
            or audit['result']['plan_id']!=proposal['plan_id'] or utc(audit['effective_at'])!=utc(proposal['execution_at'])):
        raise QuantError('CORRUPT_OPTION_AUDIT','前缀退出模式、计划或成交时间不一致')
    receipts=audit.get('receipts',[])
    if not receipts or len({r['event_id'] for r in receipts})!=len(receipts):
        raise QuantError('CORRUPT_OPTION_AUDIT','前缀退出凭据缺失或重复')
    needed={r['receipt_hash']:r['event_id'] for r in receipts};found={}
    for file in root.glob('simulation/options/*/prefix-*/verification.json'):
        proof=json.loads(file.read_text());directory=file.parent
        events=json.loads((directory/'engine-events.json').read_text())
        matched=[(digest({'proof':proof,'receipt':event}),event) for event in events]
        selected=[(identity,event) for identity,event in matched if identity in needed]
        if not selected:continue
        if proof.get('status')!='PASSED' or proof.get('engine_commit')!=LEAN_COMMIT:
            raise QuantError('CORRUPT_OPTION_AUDIT','退出前缀不是固定引擎通过的机械验证')
        if hashlib.sha256((directory/'bin/LyraX.Options.dll').read_bytes()).hexdigest()!=proof['adapter_dll_sha256']:
            raise QuantError('CORRUPT_OPTION_AUDIT','退出前缀程序集改变')
        for name,expected in proof['adapter_source'].items():
            path=directory/'source'/name
            if '/' in name or '\\' in name or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
                raise QuantError('CORRUPT_OPTION_AUDIT','退出前缀适配源码归档改变')
        for identity,event in selected:
            if needed[identity]!=str(event['order_id'])+':'+str(event['event_id']):
                raise QuantError('CORRUPT_OPTION_AUDIT','退出凭据与原生事件ID不一致')
            found[identity]=event
    if set(found)!=set(needed):raise QuantError('MISSING_BACKUP_REFERENCE','备份缺少退出实际原生前缀')
    lines={line['contract_id']:line for line in proposal['review']['lines']};quantities={}
    owner=book.connection.execute('SELECT payload FROM option_plans WHERE plan_id=?',(proposal['plan_id'],)).fetchone()
    body=json.loads(owner[0]);signal=body['activation']['monthly_signal_id']
    for receipt in receipts:
        stored=book.connection.execute('SELECT payload FROM events WHERE account_id=? AND event_id=?',(audit['account_id'],receipt['event_id'])).fetchone()
        if stored is None:raise QuantError('CORRUPT_OPTION_AUDIT','退出审计缺少账本事实')
        row=json.loads(stored[0]);native=found[receipt['receipt_hash']];line=lines.get(row['symbol'])
        contract=OptionContract.from_dict(row['contract']);quantity=D(row['quantity'])
        if (not line or row['plan_id']!=proposal['plan_id'] or row['kind']!='OPTION_TRADE' or row['action']!='CLOSE'
                or utc(row['effective_at'])!=utc(proposal['execution_at']) or utc(native['utc_time'])!=utc(row['effective_at'])
                or native['tag'] not in {signal+'|CLOSE',signal+'|CLOSE_DELIVERY_RISK'}
                or native['right']!=contract.right or native['expiry']!=contract.expiry or D(native['strike'])!=contract.strike
                or native['underlying']!=contract.underlying or abs(D(native['quantity']))!=quantity
                or D(native['price'])!=D(row['price']) or D(native['fee'])!=D(row['fee'])
                or ('BUY' if D(native['quantity'])>0 else 'SELL')!=row['trade_side']):
            raise QuantError('CORRUPT_OPTION_AUDIT','退出原生归档与实际账本合约/金额/方向不一致')
        if quantity<=0 or quantity!=quantity.to_integral_value() or row['trade_side']!=line['side']:
            raise QuantError('CORRUPT_OPTION_AUDIT','退出凭据不是冻结方向的正整数张数')
        if any(quantities.get(key,D(0))<D(lines[key]['contracts']) for key in line['depends_on']):
            raise QuantError('CORRUPT_OPTION_AUDIT','退出凭据未遵守先关闭义务再关闭保护的依赖')
        quantities[row['symbol']]=quantities.get(row['symbol'],D(0))+quantity
        if quantities[row['symbol']]>D(line['contracts']):
            raise QuantError('CORRUPT_OPTION_AUDIT','退出凭据数量超过冻结计划')
    if complete and any(quantities.get(identity,D(0))!=D(line['contracts']) for identity,line in lines.items()):
        raise QuantError('CORRUPT_OPTION_AUDIT','完成退出数量与冻结计划不一致')
    return quantities


def validate_progress(root,book,progress,proposal):
    """A pending exit needs the same native receipts as a completed exit."""
    if set(progress)!={'closed','receipts'}:
        raise QuantError('CORRUPT_OPTION_AUDIT','部分退出进度字段不完整')
    audit={'request':{'exit_id':proposal['exit_id'],'adapter':'verified_native_prefix'},
           'result':{'plan_id':proposal['plan_id']},'effective_at':proposal['execution_at'],
           'account_id':proposal['account_id'],'receipts':progress['receipts']}
    actual=validate(root,book,audit,proposal,complete=False)
    if {k:D(v) for k,v in progress['closed'].items()}!=actual:
        raise QuantError('CORRUPT_OPTION_AUDIT','部分退出累计数量与实际原生凭据不一致')
