"""Bound native replay clocks; delayed observations never move execution time."""
import json
from ..common import QuantError,utc,digest

FIELDS={'plan_kind','plan_id','execution_at','processing_at'}


def validate(book,account_id,request,clock,known):
    if (not isinstance(request,dict) or set(request) not in (FIELDS,FIELDS|{'exit_id'})
            or any(not isinstance(v,str) or not v for v in request.values())
            or request['plan_kind'] not in {'stock','option'}
            or ('exit_id' in request and request['plan_kind']!='option')
            or utc(request['execution_at'])!=clock or utc(request['processing_at'])!=known or known<clock):
        raise QuantError('INVALID_HEDGE_EXECUTION_REPLAY','迟到风险须绑定原生冻结计划、原成交时点及实际处理知识截止')
    if request['plan_kind']=='option':
        exists=book.connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='option_plans'").fetchone()
        row=book.connection.execute('SELECT payload FROM option_plans WHERE plan_id=? AND account_id=?',(request['plan_id'],account_id)).fetchone() if exists else None
        if row is None:raise QuantError('UNKNOWN_OPTION_PLAN','冻结期权计划不属于该账户')
        body=json.loads(row['payload']);activation=body.get('activation')
        if 'exit_id' in request:
            from ..options.exit_tasks import _task
            frozen=_task(book,'option-exit-freeze:'+request['exit_id'])
            if frozen is None:raise QuantError('UNKNOWN_OPTION_EXIT','迟到退出须事先显式冻结')
            p=frozen['proposal'];source=frozen['request']
            if (_task(book,'option-exit-cancel:'+request['exit_id']) is not None
                    or p['plan_id']!=request['plan_id'] or p['account_id']!=account_id
                    or p['exit_id']!=request['exit_id'] or utc(p['execution_at'])!=clock
                    or utc(p['as_of'])>=clock or frozen['status']!='FROZEN'):
                raise QuantError('UNFROZEN_HEDGE_EXECUTION','期权CLOSE须属于本账户且在原成交前冻结，未被取消')
            if (frozen['request_hash']!=digest(source) or p['request']!=source
                    or p['request_hash']!=digest(source)
                    or p['preview_hash']!=digest({k:v for k,v in p.items() if k!='preview_hash'})
                    or source['expected_sequence']!=p['ledger_seq']
                    or source['review']['plan_id']!=request['plan_id']
                    or utc(source['review']['as_of'])!=utc(p['as_of'])
                    or utc(source['execution_at'])!=clock):
                raise QuantError('CORRUPT_OPTION_AUDIT','原退出决定、时间或财务前缀改变')
            from .stage_gate import validate_cached
            validate_cached(book,frozen,'CLOSE',proposal=True)
            if p.get('hedge_stage_check',{}).get('status')!='CHECKED':
                raise QuantError('UNBOUND_HEDGE_EXECUTION','期权退出重放仅限已绑定原执行阶段')
            if (utc(p['hedge_stage_check']['as_of'])!=utc(p['as_of'])
                    or p['hedge_stage_check']['ledger_seq']!=p['ledger_seq']
                    or p['review']['plan_id']!=request['plan_id']
                    or utc(p['review']['as_of'])!=utc(p['as_of'])
                    or p['review']['ledger_seq']!=p['ledger_seq']
                    or p['review']['request']!=source['review']
                    or p['review']['request_hash']!=digest(source['review'])
                    or p['status']!='CHECKED' or p['checks']):
                raise QuantError('CORRUPT_OPTION_AUDIT','原退出review/阶段压力时间与财务前缀不一致')
            from ..data.calendar import Calendar
            from datetime import timedelta
            from zoneinfo import ZoneInfo
            session=clock.astimezone(ZoneInfo('America/New_York')).date()
            if Calendar.market(str(session),str(session+timedelta(days=1))).close(session).to_pydatetime()!=clock:
                raise QuantError('HEDGE_REPLAY_CALENDAR_MISMATCH','退出成交时点须为原市场收盘')
            return str(session)
        if (not activation or utc(activation['valid_until'])!=clock or utc(activation['as_of'])>=clock
                or utc(body['selection']['decision_at'])>=clock):
            raise QuantError('UNFROZEN_HEDGE_EXECUTION','期权OPEN须已在原成交前显式激活')
        audits=[json.loads(r[0]) for r in book.connection.execute("SELECT details FROM tasks WHERE task_id LIKE 'option-activation:%'")]
        original=[a for a in audits if a['status']=='ACTIVATED' and a['request']['plan_id']==request['plan_id']]
        if len(original)!=1:raise QuantError('CORRUPT_OPTION_AUDIT','期权重放须唯一原激活审计')
        source=original[0]['request']
        from ..options.monthly import validate_frozen
        monthly=validate_frozen(source['monthly_signal'])
        if (original[0]['request_hash']!=digest(source) or source['expected_sequence']!=activation['basis_sequence']
                or utc(source['as_of'])!=utc(activation['as_of']) or utc(source['valid_until'])!=clock
                or monthly['monthly_signal_id']!=activation['monthly_signal_id']
                or monthly['selection']['decision_hash']!=body['selection']['decision_hash']):
            raise QuantError('CORRUPT_OPTION_AUDIT','原期权月度/激活时钟或财务前缀改变')
        from .stage_gate import validate_cached
        validate_cached(book,original[0],'OPEN')
        stage=original[0].get('hedge_stage_check',{})
        if stage.get('status')!='CHECKED':raise QuantError('UNBOUND_HEDGE_EXECUTION','期权风险重放仅限已绑定执行组的原激活计划')
        if body['activation']!=original[0]['result']['activation']:
            raise QuantError('CORRUPT_OPTION_AUDIT','原期权激活条件改变')
        return monthly['applicable_session']
    row=book.connection.execute('SELECT payload FROM plans WHERE plan_id=? AND account_id=?',(request['plan_id'],account_id)).fetchone()
    if row is None:raise QuantError('UNKNOWN_PLAN','冻结股票计划不属于该账户')
    body=json.loads(row['payload'])
    if (body.get('purpose')!='hedge_stage' or not body.get('hedge_activation_task')
            or utc(body['execution_deadline'])!=clock or utc(body['as_of'])>=clock
            or (book.environment!='demo' and utc(body['created_at'])>=clock)):
        raise QuantError('UNFROZEN_HEDGE_EXECUTION','只能重放在原成交前已明确激活的独立股票计划')
    from .stock_plans import validate_references as validate_drafts
    from .stock_activation import validate_references as validate_activations
    validate_drafts(book);validate_activations(book)
    return body['execution_session']
