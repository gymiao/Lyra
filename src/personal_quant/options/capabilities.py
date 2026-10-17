"""Independent template/rule/input/engine gates, never broker permission."""
from pathlib import Path
from ..common import QuantError,now_utc
from ..strategies.archive import source_fingerprint
from .catalog import MONTHLY_RESEARCH
from .selection import rule_identity
from .qualification import assess_engine


def describe(template_id,engine_evidence,input_bundle):
    if template_id not in MONTHLY_RESEARCH:raise QuantError('UNKNOWN_OPTION_TEMPLATE','模板尚未实现月度选约')
    checks=[];engine=None;bundle=None
    if engine_evidence:
        engine=assess_engine(engine_evidence,template_id)
        if engine['status']!='PASSED':checks.append('ENGINE_LIFECYCLE_UNQUALIFIED')
    else:checks.append('ENGINE_EVIDENCE_REQUIRED')
    if input_bundle:
        from ..workspace.packages import verify
        try:
            bundle=verify(input_bundle)
            if bundle['checks']:checks+=bundle['checks']
            if not bundle['option_snapshots']:checks.append('OPTION_CHAIN_REQUIRED')
            from .data import OptionDataStore
            if any(OptionDataStore(Path(input_bundle)/'chains').load(identity)[2]['data_type']!='synthetic' for identity in bundle['option_snapshots']):checks.append('QUALIFIED_REAL_OPTION_SOURCE_REQUIRED')
        except QuantError as exc:checks.append(exc.code)
    else:checks.append('INPUT_PACKAGE_REQUIRED')
    return {'status':'CHECKED','template_id':template_id,'source_hash':source_fingerprint(),'rule':rule_identity(),
            'scenario':'SUPPORTED','monthly_selection':'SUPPORTED','engine':engine,
            'input_bundle_id':bundle['input_bundle_id'] if bundle else None,'checks':checks,
            'simulated_plan_preconditions':'PASSED' if not checks else 'BLOCKED','real_source':'UNVERIFIED',
            'broker_permissions':'UNVERIFIED','executable':False,'financial_events_added':0,'checked_at':now_utc(),
            'meaning':'模板与当前源码/输入/引擎的分项状态；生成模拟计划仍需账户、时点、资金、覆盖、对账与报价检查'}
