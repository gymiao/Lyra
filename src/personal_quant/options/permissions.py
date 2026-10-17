"""Archived, operation-specific account evidence; never a broker login or order permission."""
import json
from ..common import QuantError,decimal as D,digest,utc,now_utc
from ..data.qualification import archive_qualification,load_evidence
from .qualification import ENGINE_TEMPLATES

FIELDS={'schema_version','asset_type','series_id','account_id','environment','broker','market','currency',
        'scope_templates','scope_operations','settlement_policy','exercise_policy','maximum_contracts',
        'maximum_physical_cash','minimum_exit_days','reviewed_at','valid_until','decision','reviewer','reason',
        'evidence_type','evidence_files'}
OPERATIONS={'OPEN','CLOSE','EXERCISE','ASSIGNMENT'}


def series_id(account_id,environment):
    return 'account-option-permissions:'+digest({'account_id':account_id,'environment':environment})


def normalize(book,body):
    if not isinstance(body,dict) or set(body)!=FIELDS or type(body['schema_version']) is not int or body['schema_version']!=2:
        raise QuantError('INVALID_OPTION_PERMISSIONS','账户权限需完整显式字段和独立证据范围')
    if any(not isinstance(body[k],str) or not body[k].strip() for k in FIELDS-{
            'schema_version','scope_templates','scope_operations','maximum_contracts','maximum_physical_cash',
            'minimum_exit_days','evidence_files'}):
        raise QuantError('INVALID_OPTION_PERMISSIONS','账户、券商和核验说明不得为空')
    book._require_account(body['account_id'])
    if (body['asset_type']!='ACCOUNT_OPTION_PERMISSIONS' or body['environment']!=book.environment
            or body['series_id']!=series_id(body['account_id'],body['environment'])
            or body['market']!='OPRA' or body['currency']!='USD'
            or body['settlement_policy']!='cash_account_no_margin'
            or body['exercise_policy'] not in {'close_before_expiry','manual_confirmed_delivery'}
            or body['decision'] not in {'QUALIFIED','REJECTED','UNVERIFIED'} or body['evidence_type'] not in {'actual','test'}
            or type(body['maximum_contracts']) is not int or not 1<=body['maximum_contracts']<=100
            or D(body['maximum_physical_cash'])<0 or type(body['minimum_exit_days']) is not int or body['minimum_exit_days']<1):
        raise QuantError('INVALID_OPTION_PERMISSIONS','仅核验指定账户美国标准期权、现金无保证金及显式操作/交割限制')
    for key,allowed in [('scope_templates',set(ENGINE_TEMPLATES)),('scope_operations',OPERATIONS)]:
        values=body[key]
        if not isinstance(values,list) or not values or any(not isinstance(x,str) for x in values) or len(set(values))!=len(values) or not set(values)<=allowed:
            raise QuantError('INVALID_OPTION_PERMISSIONS','权限须限定已验证模板和逐项操作，不承诺其他策略或自动下单')
    if utc(body['reviewed_at'])>utc(now_utc()) or utc(body['valid_until'])<=utc(body['reviewed_at']) or not isinstance(body['evidence_files'],dict) or not body['evidence_files']:
        raise QuantError('INVALID_OPTION_PERMISSIONS','权限核验时点/有效期和证据文件无效')
    if book.environment!='demo' and body['evidence_type']!='actual':
        raise QuantError('TEST_EVIDENCE_FORBIDDEN','测试账单或声明不能授予真实/前向账户资格')
    return body


def register(book,body,evidence_directory):
    if book.connection.execute('SELECT version FROM schema_version').fetchone()[0]<5:
        raise QuantError('V19_NOT_ENABLED','期权权限登记需要显式启用v1.9')
    return archive_qualification(book,normalize(book,body),evidence_directory)


def assess(book,account_id,template_id,operation,as_of,*,contract_count=0,physical_cash=0,exit_days=None):
    book._require_account(account_id)
    if template_id not in ENGINE_TEMPLATES or operation not in OPERATIONS or type(contract_count) is not int or contract_count<0 or D(physical_cash)<0:
        raise QuantError('INVALID_OPTION_PERMISSION_REQUEST','需确切已验证模板/操作及非负数量和交割资金')
    known=utc(as_of);selected=None
    if known>utc(now_utc()):raise QuantError('FUTURE_PERMISSION_REVIEW','不能把未来账户权限当作已核验事实')
    if book.connection.execute('SELECT version FROM schema_version').fetchone()[0]<5:
        raise QuantError('V19_NOT_ENABLED','权限核验需要显式启用v1.9')
    for row in book.connection.execute('SELECT qualification_id,payload,created_at FROM source_qualifications WHERE series_id=? ORDER BY created_at DESC,rowid DESC',
            (series_id(account_id,book.environment),)):
        if utc(row['created_at'])<=known: selected=row;break
    checks=[];proof=None
    if selected is None:checks.append('ACCOUNT_OPTION_PERMISSIONS_REQUIRED')
    else:
        try:
            proof=load_evidence(book.connection,book.path.parent,selected['qualification_id'],as_of)
            body=normalize(book,proof['payload'])
            if body['decision']!='QUALIFIED' or body['evidence_type']!='actual' or utc(body['valid_until'])<=known:
                checks.append('ACCOUNT_OPTION_PERMISSIONS_NOT_QUALIFIED')
            if template_id not in body['scope_templates'] or operation not in body['scope_operations']:
                checks.append('ACCOUNT_OPTION_OPERATION_NOT_PERMITTED')
            if contract_count>body['maximum_contracts'] or D(physical_cash)>D(body['maximum_physical_cash']):
                checks.append('ACCOUNT_OPTION_LIMIT_EXCEEDED')
            if operation=='OPEN' and (type(exit_days) is not int or exit_days<body['minimum_exit_days']):
                checks.append('ACCOUNT_OPTION_DISPOSITION_REQUIRED')
        except QuantError as exc:checks.append(exc.code)
    return {'status':'UNQUALIFIED' if checks else 'QUALIFIED','qualification_id':selected['qualification_id'] if selected else None,
            'account_id':account_id,'environment':book.environment,'template_id':template_id,'operation':operation,
            'as_of':as_of,'contract_count':contract_count,'physical_cash':str(D(physical_cash)),'exit_days':exit_days,
            'checks':sorted(set(checks)),'executable':False,
            'meaning':'已归档资料的范围/操作核验；不授权券商自动下单，不替代行情/账务/前向信号门禁'}
