"""Atomic financial receipts and independently checked stock-stage evidence."""
import json
from ..common import QuantError,canonical,digest,decimal as D,utc
from .stage_gate import validate_record
from .archive import load

PREFIX='hedge-stock-simulation:'


def save(book,account_id,plan_id,events,before,after,assessment,processing_at,state_at,*,action):
    key=PREFIX+digest(dict(account_id=account_id,plan_id=plan_id,before_sequence=before))
    result=dict(schema_version=1,account_id=account_id,plan_id=plan_id,before_sequence=before,after_sequence=after,
        events=events,stage_assessment=assessment,stage_request=assessment['stage_request'],
        processing_at=processing_at,state_at=state_at,action=action,evidence_type='simulated',environment=book.environment)
    result['record_hash']=digest(result)
    existing=book.connection.execute('SELECT details FROM tasks WHERE task_id=?',(key,)).fetchone()
    if existing and json.loads(existing[0])!=result:raise QuantError('HEDGE_STOCK_SIMULATION_CONFLICT','原财务前缀已有不同阶段模拟审计')
    book.record_task(key,'SUCCESS',result)
    validate_references(book)


def validate_references(book):
    try:
        for row in book.connection.execute('SELECT task_id,details FROM tasks WHERE task_id LIKE ?',(PREFIX+'%',)):
            audit=json.loads(row['details']);stage=audit['stage_assessment']
            if (audit['record_hash']!=digest({k:v for k,v in audit.items() if k!='record_hash'})
                    or row['task_id']!=PREFIX+digest(dict(account_id=audit['account_id'],plan_id=audit['plan_id'],before_sequence=audit['before_sequence']))
                    or audit['before_sequence']!=stage['ledger_seq'] or audit['environment']!=book.environment
                    or audit['evidence_type']!='simulated' or audit['action'] not in {'OPEN','CLOSE'} or not audit['events']):raise ValueError('identity')
            validate_record(book,audit['account_id'],audit['plan_id'],audit['action'],audit['stage_request'],stage)
            risk=load(book.path.parent/'hedging/exposures',stage['exposure_id'])
            from .groups import _plan
            from ..config import Config
            _,body,lines=_plan(book,audit['account_id'],'stock',audit['plan_id'])
            config=Config.from_dict(body['execution_config']);config.validate();config.require_execution()
            if config.hash!=body['execution_config_hash']:raise ValueError('execution assumptions')
            expected={(l['symbol'],l['side']):D(stage['remaining_quantities'][str((l['symbol'],None,l['side']))]) for l in lines}
            expected={k:q for k,q in expected.items() if q>0};supplied={}
            sequences=[]
            for event in audit['events']:
                raw=book.connection.execute('SELECT seq,payload FROM events WHERE account_id=? AND event_id=?',
                    (audit['account_id'],event['event_id'])).fetchone()
                if raw is None:raise ValueError('receipt')
                fact=json.loads(raw['payload']);sequences.append(raw['seq'])
                key=(event['symbol'],event['kind'])
                if key in supplied or key not in expected or D(event['quantity'])!=expected[key]:raise ValueError('frozen remaining quantity')
                supplied[key]=D(event['quantity'])
                fee=D(event['quantity'])*D(event['price'])*(D(config.commission_bps)+D(config.slippage_bps))/10000+D(config.fixed_fee)
                if D(event['fee'])!=fee:raise ValueError('independent fee')
                for key in ('kind','symbol','plan_id','source','evidence_type','environment'):
                    if fact[key]!=event[key]:raise ValueError('receipt identity')
                for key in ('quantity','price','fee'):
                    if D(fact[key])!=D(event[key]):raise ValueError('receipt money')
                for key in ('effective_at','settlement_at'):
                    if utc(fact[key])!=utc(event[key]):raise ValueError('receipt time')
                if (event['plan_id']!=audit['plan_id'] or D(event['price'])!=D(risk['valuation']['prices'][event['symbol']])
                        or utc(event['effective_at'])>utc(audit['state_at'])
                        or utc(audit['state_at'])>utc(audit['processing_at'])):raise ValueError('frozen prices/time')
            if supplied!=expected or sorted(sequences)!=list(range(audit['before_sequence']+1,audit['after_sequence']+1)):
                raise ValueError('financial sequence')
    except (KeyError,ValueError,TypeError) as exc:
        raise QuantError('CORRUPT_HEDGE_STOCK_SIMULATION','阶段模拟审计或原财务凭据改变') from exc
