"""Option quote-source evidence, separate from labels, engine tests and stock evidence."""
import hashlib
import json
from pathlib import Path

from ..common import QuantError, digest, utc, now_utc
from ..data.qualification import archive_qualification

FIELDS = {'schema_version','asset_type','series_id','source','market','currency','timezone',
          'price_basis','scope_contract_versions','quote_convention','time_convention',
          'corporate_actions','license_terms','reviewed_at','valid_until','decision',
          'reviewer','reason','evidence_type','evidence_files'}


def series_id(source):
    return 'option-quotes:'+digest({'source':source,'market':'OPRA','currency':'USD',
                                   'price_basis':'premium_per_quote_unit'})


def register_source(book, body, evidence_directory):
    if book.connection.execute('SELECT version FROM schema_version').fetchone()[0] < 5:
        raise QuantError('V19_NOT_ENABLED','期权来源核验需要显式启用v1.9')
    if not isinstance(body,dict) or set(body)!=FIELDS:
        raise QuantError('INVALID_OPTION_SOURCE','期权来源核验字段缺失或未知')
    scalar = FIELDS-{'schema_version','scope_contract_versions','evidence_files'}
    if any(not isinstance(body[k],str) or not body[k].strip() for k in scalar):
        raise QuantError('INVALID_OPTION_SOURCE','来源、报价/时间/行动/许可及核验说明不能为空')
    versions=body['scope_contract_versions']
    if (body['schema_version']!=2 or body['asset_type']!='OPTION_QUOTES' or body['market']!='OPRA'
            or body['currency']!='USD' or body['timezone']!='America/New_York'
            or body['price_basis']!='premium_per_quote_unit' or body['series_id']!=series_id(body['source'])
            or body['decision'] not in {'QUALIFIED','REJECTED','UNVERIFIED'}
            or body['evidence_type'] not in {'actual','test'}
            or not isinstance(versions,list) or not versions
            or any(not isinstance(v,str) or len(v)!=64 or any(c not in '0123456789abcdef' for c in v) for v in versions)
            or len(set(versions))!=len(versions)
            or not isinstance(body['evidence_files'],dict) or not body['evidence_files']):
        raise QuantError('INVALID_OPTION_SOURCE','必须提供独立期权来源身份、确切合约版本范围及证据文件')
    if utc(body['reviewed_at'])>utc(now_utc()) or utc(body['valid_until'])<=utc(body['reviewed_at']):
        raise QuantError('INVALID_OPTION_SOURCE','来源核验时间/有效期无效')
    if book.environment!='demo' and body['evidence_type']!='actual':
        raise QuantError('TEST_EVIDENCE_FORBIDDEN','合成测试凭据不能授予真实或前向来源资格')
    return archive_qualification(book,body,evidence_directory)


def assess_source(book, metadata, contracts, as_of):
    if metadata['data_type']=='synthetic':
        return {'status':'SYNTHETIC_DEMO' if book.environment=='demo' else 'UNQUALIFIED',
                'actual_source_qualified':False,'qualification_id':None,
                'checks':[] if book.environment=='demo' else ['SYNTHETIC_OPTION_QUOTES_FORBIDDEN']}
    identity=series_id(metadata['source']);known=[]
    for row in book.connection.execute('SELECT qualification_id,payload,created_at FROM source_qualifications WHERE series_id=? ORDER BY created_at DESC,rowid DESC',(identity,)):
        body=json.loads(row['payload'])
        if not isinstance(body,dict) or set(body)!=FIELDS:
            raise QuantError('CORRUPT_OPTION_SOURCE_EVIDENCE','来源记录不是完整期权核验契约')
        if utc(body['reviewed_at'])<=utc(as_of) and (book.environment=='demo' or utc(row['created_at'])<=utc(as_of)):
            known.append((row,body))
    if not known:
        return {'status':'UNQUALIFIED','actual_source_qualified':False,'qualification_id':None,
                'checks':['OPTION_SOURCE_QUALIFICATION_REQUIRED']}
    row,body=known[0];checks=[];qualified=row['qualification_id']
    if (set(body)!=FIELDS or body.get('schema_version')!=2 or body.get('asset_type')!='OPTION_QUOTES'
            or digest(body)!=qualified or body['source']!=metadata['source']
            or body['market']!='OPRA' or body['currency']!='USD' or body['timezone']!='America/New_York'
            or body['price_basis']!='premium_per_quote_unit' or body['series_id']!=identity
            or body['decision']!='QUALIFIED' or body['evidence_type']!='actual'
            or utc(body['valid_until'])<=utc(as_of)):
        checks.append('OPTION_SOURCE_NOT_QUALIFIED')
    if not {c.version_hash for c in contracts}<=set(body.get('scope_contract_versions',[])):
        checks.append('OPTION_SOURCE_SCOPE_MISMATCH')
    from .ledger import verify_contract_evidence
    for contract in contracts:
        try:verify_contract_evidence(book.path.parent,contract)
        except QuantError:checks.append('OPTION_CONTRACT_EVIDENCE_REQUIRED')
    root=book.path.parent/'qualifications'/qualified
    try:
        if json.loads((root/'qualification.json').read_text())!=body:checks.append('CORRUPT_OPTION_SOURCE_EVIDENCE')
        for name,expected in body['evidence_files'].items():
            file=root/name
            if (not file.resolve().is_relative_to(root.resolve()) or file.is_symlink() or not file.is_file()
                    or hashlib.sha256(file.read_bytes()).hexdigest()!=expected):
                checks.append('CORRUPT_OPTION_SOURCE_EVIDENCE')
    except (OSError,ValueError,KeyError):checks.append('CORRUPT_OPTION_SOURCE_EVIDENCE')
    return {'status':'UNQUALIFIED' if checks else 'QUALIFIED','qualification_id':qualified,
            'actual_source_qualified':not checks,'checks':sorted(set(checks))}
