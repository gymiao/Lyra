"""Option facts in LyraX's existing event ledger; no second cash balance."""
import json
import hashlib
from pathlib import Path
from ..locks import publication_lock
from ..common import QuantError, canonical, decimal as D, now_utc, utc, digest
from .contracts import OptionContract

OPTION_KINDS={'OPTION_TRADE','OPTION_EXERCISE','OPTION_ASSIGNMENT','OPTION_EXPIRY','OPTION_CASH_SETTLEMENT'}


def verify_contract_evidence(root,contract):
    identity=contract.evidence_hash
    if len(identity)!=64 or any(character not in '0123456789abcdef' for character in identity):
        raise QuantError('OPTION_CONTRACT_EVIDENCE_REQUIRED','真实账户必须提供实际合约单位凭据及其SHA256')
    path=Path(root)/'options/contract-evidence'/identity
    if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=identity:
        raise QuantError('OPTION_CONTRACT_EVIDENCE_REQUIRED','实际合约单位凭据缺失或改变，不能依据测试条款更新真实账户')


def register_contract(ledger,body,evidence_file=None):
    if ledger.connection.execute('SELECT version FROM schema_version').fetchone()[0]<5:
        raise QuantError('V19_NOT_ENABLED','期权凭据需要显式备份并升级v1.9')
    contract=OptionContract.from_dict(body)
    if ledger.environment=='real':
        if evidence_file is not None:
            path=Path(evidence_file)
            if path.is_symlink() or not path.is_file():
                raise QuantError('OPTION_CONTRACT_EVIDENCE_REQUIRED','实际合约单位凭据必须是普通文件')
            evidence_bytes=path.read_bytes()
            if hashlib.sha256(evidence_bytes).hexdigest()!=contract.evidence_hash:
                raise QuantError('OPTION_CONTRACT_EVIDENCE_REQUIRED','实际合约单位凭据必须与条款中的SHA256一致')
            target=ledger.path.parent/'options/contract-evidence'/contract.evidence_hash
            with publication_lock(ledger.path.parent):
                target.parent.mkdir(parents=True,exist_ok=True)
                if target.is_symlink():raise QuantError('OPTION_CONTRACT_EVIDENCE_REQUIRED','实际合约单位凭据不能是链接')
                if not target.exists():
                    from uuid import uuid4
                    import os
                    pending=target.with_name('.pending-'+uuid4().hex)
                    try:pending.write_bytes(evidence_bytes);os.rename(pending,target)
                    finally:pending.unlink(missing_ok=True)
        verify_contract_evidence(ledger.path.parent,contract)
    with publication_lock(ledger.path.parent),ledger.transaction():
        ledger.connection.execute('INSERT OR IGNORE INTO option_contracts VALUES(?,?,?,?)',
            (contract.version_hash,contract.contract_id,canonical(contract.content()),now_utc()))
    return contract


def normalize_option_event(ledger,raw,account_id):
    if ledger.connection.execute('SELECT version FROM schema_version').fetchone()[0]<5:
        raise QuantError('V19_NOT_ENABLED','期权凭据需要v1.9')
    extra={'contract_version','action','trade_side','position_side'}
    if raw.get('kind') not in OPTION_KINDS or 'contract_version' not in raw:
        raise QuantError('INVALID_OPTION_EVENT','期权事实类型或合约版本缺失')
    row=ledger.connection.execute('SELECT payload FROM option_contracts WHERE version_hash=?',(raw['contract_version'],)).fetchone()
    if not row:raise QuantError('UNKNOWN_OPTION_CONTRACT','先登记有单位凭据的合约版本')
    contract=OptionContract.from_dict(json.loads(row[0]));contract.require_standard_vanilla()
    if ledger.environment=='real':verify_contract_evidence(ledger.path.parent,contract)
    if raw.get('symbol',contract.contract_id)!=contract.contract_id:
        raise QuantError('OPTION_UNIT_CONFLICT','期权标的必须是确切合约ID')
    # Reuse the common ID/source/account/currency/time/fee validation boundary.
    base={key:value for key,value in raw.items() if key not in extra}
    option_plan=None
    if raw.get('plan_id'):
        option_plan=ledger.connection.execute('SELECT account_id FROM option_plans WHERE plan_id=?',(raw['plan_id'],)).fetchone()
        if option_plan is None or option_plan[0]!=account_id:
            raise QuantError('INVALID_PLAN_REFERENCE','期权关联计划必须存在且属于同一账户')
        base['plan_id']=''
    base.update(kind='SPLIT',symbol=contract.contract_id)
    event=ledger.normalize_event(base,account_id)
    if option_plan is not None:event['plan_id']=str(raw['plan_id'])
    event.update(kind=raw['kind'],contract=contract.content(),contract_version=contract.version_hash,
                 action=raw.get('action'),trade_side=raw.get('trade_side'),position_side=raw.get('position_side'))
    quantity=D(event['quantity'])
    if quantity<=0 or quantity!=quantity.to_integral_value():raise QuantError('INVALID_OPTION_EVENT','期权事实必须使用正整张数')
    if utc(event['effective_at'])<utc(contract.listed_at):raise QuantError('INVALID_OPTION_EVENT','事件早于合约挂牌')
    if event['kind']=='OPTION_TRADE':
        if event['action'] not in {'OPEN','CLOSE'} or event['trade_side'] not in {'BUY','SELL'} or D(event['price'])<=0:
            raise QuantError('INVALID_OPTION_EVENT','成交需明确开平仓、买卖和实际正成交价')
        if utc(event['effective_at'])>utc(contract.last_trade_at):raise QuantError('INVALID_OPTION_EVENT','成交晚于最后交易时点')
        if D(event['amount']):raise QuantError('INVALID_OPTION_EVENT','权利金由实际单价/乘数/数量计算，不重复录入amount')
    else:
        if event['position_side'] not in {'LONG','SHORT'}:raise QuantError('INVALID_OPTION_EVENT','生命周期事件需明确多/空头')
        if event['kind']=='OPTION_EXERCISE' and event['position_side']!='LONG':raise QuantError('INVALID_OPTION_EVENT','只有多头可行权')
        if event['kind']=='OPTION_ASSIGNMENT' and event['position_side']!='SHORT':raise QuantError('INVALID_OPTION_EVENT','只有空头会被指派')
        if event['kind'] in {'OPTION_EXERCISE','OPTION_ASSIGNMENT'} and contract.settlement!='PHYSICAL':
            raise QuantError('INVALID_OPTION_EVENT','现金结算合约不能伪造证券交割')
        if event['kind']=='OPTION_CASH_SETTLEMENT' and contract.settlement!='CASH':
            raise QuantError('INVALID_OPTION_EVENT','实物交割不能当作现金结算')
        if event['kind'] in {'OPTION_EXPIRY','OPTION_CASH_SETTLEMENT'} and utc(event['effective_at'])<utc(contract.exercise_cutoff_at):
            raise QuantError('INVALID_OPTION_EVENT','不能在行权截止前提前认定到期或最终结算')
        if contract.style=='EUROPEAN' and event['kind'] in {'OPTION_EXERCISE','OPTION_ASSIGNMENT'} and utc(event['effective_at']).date()!=utc(contract.exercise_cutoff_at).date():
            raise QuantError('INVALID_OPTION_EVENT','欧式合约不能提前行权')
        if event['kind']!='OPTION_CASH_SETTLEMENT' and D(event['amount']):
            raise QuantError('INVALID_OPTION_EVENT','实物交割现金由合约确定；不得重复录入内在价值')
    return event


def apply_option_event(event,instant,positions,option_positions,contracts,anomalies):
    contract=OptionContract.from_dict(event['contract']);symbol=contract.contract_id
    quantity,price,fee=D(event['quantity']),D(event['price']),D(event['fee'])
    existing=option_positions.get(symbol,D(0));kind=event['kind']
    if symbol in contracts and contracts[symbol].version_hash!=contract.version_hash and existing:
        raise QuantError('UNPROCESSED_OPTION_ACTION','持仓期间合约单位改变，需公司行动凭据处理')
    contracts[symbol]=contract
    if kind=='OPTION_TRADE':
        sign=1 if event['trade_side']=='BUY' else -1
        if event['action']=='CLOSE' and (existing*sign>=0 or quantity>abs(existing)):
            anomalies.append('期权平仓超过或不对应当前持仓：'+event['event_id'])
        if event['action']=='OPEN' and existing*sign<0:
            anomalies.append('开仓方向与当前期权持仓相反：'+event['event_id'])
        option_positions[symbol]=existing+sign*quantity
        cash_delta=-sign*quantity*price*contract.quote_multiplier-fee
    else:
        sign=1 if event['position_side']=='LONG' else -1
        if existing*sign<=0 or quantity>abs(existing):anomalies.append('生命周期事件超过或不对应当前期权持仓：'+event['event_id'])
        option_positions[symbol]=existing-sign*quantity
        cash_delta=-fee
        if kind in {'OPTION_EXERCISE','OPTION_ASSIGNMENT'}:
            stock_direction=sign*(1 if contract.right=='CALL' else -1)
            positions[contract.underlying]=positions.get(contract.underlying,D(0))+stock_direction*quantity*contract.deliverable_shares
            cash_delta-=stock_direction*quantity*contract.exercise_cash
        elif kind=='OPTION_CASH_SETTLEMENT':cash_delta+=sign*D(event['amount'])
    settled=event['settlement_at'] is not None and utc(event['settlement_at'])<=instant
    if event['settlement_at'] is None:anomalies.append('期权结算时点未知：'+event['event_id'])
    return (cash_delta,D(0),D(0)) if settled else (D(0),max(cash_delta,D(0)),max(-cash_delta,D(0)))


def collateral(positions,option_positions,contracts):
    cash=D(0);shares={};checks=[]
    long_calls={key:quantity for key,quantity in option_positions.items() if quantity>0 and contracts[key].right=='CALL'}
    for symbol,quantity in sorted(option_positions.items()):
        if quantity>=0:continue
        contract=contracts[symbol]
        if contract.right=='PUT':cash+=-quantity*contract.exercise_cash
        else:
            remaining=-quantity
            # A standard same-expiry long call protects one short
            # call once. Reserve its entire exercise cash conservatively; a
            # terminal loss bound alone is not intraday buying power.
            for key in sorted(long_calls,key=lambda key:(contracts[key].strike,key)):
                long=contracts[key]
                if long_calls[key]<=0 or long.underlying!=contract.underlying or long.expiry!=contract.expiry or long.style!=contract.style or long.settlement!=contract.settlement or long.currency!=contract.currency or long.quote_multiplier!=contract.quote_multiplier or long.deliverable_shares!=contract.deliverable_shares or utc(long.exercise_cutoff_at)<utc(contract.exercise_cutoff_at):continue
                protected=min(remaining,long_calls[key]);remaining-=protected;long_calls[key]-=protected
                cash+=protected*long.exercise_cash
                if not remaining:break
            if remaining:shares[contract.underlying]=shares.get(contract.underlying,D(0))+remaining*contract.deliverable_shares
    for symbol,required in shares.items():
        if positions.get(symbol,D(0))<required:checks.append('期权Call覆盖证券不足：'+symbol)
    return cash,shares,checks


def import_facts(ledger,account_id,rows,*,expected_sequence):
    """Supported facts are atomic; unsupported receipts stay visible and block."""
    if ledger.connection.execute('SELECT version FROM schema_version').fetchone()[0]<5:
        raise QuantError('V19_NOT_ENABLED','期权凭据需要v1.9')
    ledger._require_account(account_id);supported=[];pending=[]
    for raw in rows:
        try:normalize_option_event(ledger,raw,account_id);supported.append(raw)
        except QuantError as exc:
            if not all(raw.get(key) for key in ('event_id','source','effective_at','evidence_type')):
                raise QuantError('INVALID_OPTION_RECEIPT','无法保留缺身份/来源/时间的凭据') from exc
            utc(raw['effective_at'])
            if ledger.environment=='real' and raw['evidence_type']!='actual':raise QuantError('ENVIRONMENT_MISMATCH','真实账户不接收合成凭据')
            pending.append((raw,exc.code+': '+str(exc)))
    with ledger.transaction():
        if ledger.sequence(account_id)!=expected_sequence:raise QuantError('STALE_PREVIEW','账户改变，需重新核对')
        for raw in supported:
            if ledger.connection.execute('SELECT 1 FROM pending_option_events WHERE account_id=? AND event_id=?',
                                         (account_id,raw['event_id'])).fetchone():
                raise QuantError('PENDING_OPTION_RECEIPT','同事件仍有待核实原凭据，须通过显式解决请求处理')
        for raw,reason in pending:
            if ledger.connection.execute('SELECT 1 FROM events WHERE account_id=? AND event_id=?',
                                         (account_id,raw['event_id'])).fetchone():
                raise QuantError('EVENT_CONFLICT','待核实凭据ID与已入账事实冲突')
            old=ledger.connection.execute('SELECT payload FROM pending_option_events WHERE account_id=? AND event_id=?',(account_id,raw['event_id'])).fetchone()
            if old and digest(json.loads(old[0]))!=digest(raw):raise QuantError('EVENT_CONFLICT','待核实期权凭据ID内容冲突')
            ledger.connection.execute('INSERT OR IGNORE INTO pending_option_events VALUES(?,?,?,?,?)',
                (raw['event_id'],account_id,canonical(raw),reason,now_utc()))
        result=ledger.import_events(account_id,supported,expected_sequence) if supported else {'added':0,'duplicates':0,'ledger_seq':expected_sequence}
    return {**result,'status':'RECONCILIATION_REQUIRED' if pending else 'SUCCESS','pending_events':[raw['event_id'] for raw,_ in pending]}
