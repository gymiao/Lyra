"""Explicit source evidence, separate from CSV labels and data quality."""
import hashlib
import json
from pathlib import Path
import shutil
from uuid import uuid4
from ..common import QuantError, canonical, digest, now_utc, utc, write_json
from ..locks import publication_lock

FIELDS={'schema_version','series_id','sources','market','currency','timezone','price_basis','units_description',
        'adjustment_method','actions_description','scope_symbols','reviewed_at','valid_until','decision',
        'reviewer','reason','evidence_type','evidence_files'}


def register(ledger,body,evidence_directory):
    if ledger.connection.execute('SELECT version FROM schema_version').fetchone()[0]<5:
        raise QuantError('V19_NOT_ENABLED','来源凭据需要v1.9')
    if not isinstance(body,dict) or set(body)!=FIELDS or body['schema_version']!=1:
        raise QuantError('INVALID_SOURCE_QUALIFICATION','来源资格字段缺失/未知')
    if body['decision'] not in {'QUALIFIED','REJECTED','UNVERIFIED'} or body['evidence_type'] not in {'actual','test'}:
        raise QuantError('INVALID_SOURCE_QUALIFICATION','资格结论和证据类型无效')
    if not isinstance(body['evidence_files'],dict) or not body['evidence_files'] or any(not isinstance(body[k],list) or not body[k] or any(not isinstance(v,str) or not v for v in body[k]) for k in ('scope_symbols','sources')):
        raise QuantError('INVALID_SOURCE_QUALIFICATION','必须有范围、来源及实际证据文件哈希')
    if any(not isinstance(body[k],str) or not body[k].strip() for k in FIELDS-{'schema_version','sources','scope_symbols','evidence_files'}):
        raise QuantError('INVALID_SOURCE_QUALIFICATION','来源说明及核验结论字段不可为空')
    if body['market']!='XNYS' or body['currency']!='USD' or body['timezone']!='America/New_York' or body['price_basis']!='unadjusted':
        raise QuantError('INVALID_SOURCE_QUALIFICATION','当前证券单位资格仅支持XNYS/USD实际原价')
    if utc(body['reviewed_at'])>utc(now_utc()) or utc(body['valid_until'])<=utc(body['reviewed_at']):
        raise QuantError('INVALID_SOURCE_QUALIFICATION','核验时间/有效期无效')
    if ledger.environment!='demo' and body['evidence_type']!='actual':raise QuantError('TEST_EVIDENCE_FORBIDDEN','测试证明不能用于前向/真实资格')
    return archive_qualification(ledger,body,evidence_directory)


def archive_qualification(ledger,body,evidence_directory):
    """Shared immutable evidence publication after asset-specific validation."""
    source=Path(evidence_directory);files={}
    for relative,expected in body['evidence_files'].items():
        if (not isinstance(relative,str) or not isinstance(expected,str) or len(expected)!=64
                or any(c not in '0123456789abcdef' for c in expected)):
            raise QuantError('INVALID_SOURCE_QUALIFICATION','证据需相对文件名及SHA256')
        path=Path(relative)
        if path.is_absolute() or '..' in path.parts or '\\' in relative or path.as_posix()!=relative or relative=='qualification.json':
            raise QuantError('UNSAFE_SOURCE_EVIDENCE','来源证据路径越界')
        target=source/path
        if target.is_symlink() or not target.is_file() or not target.resolve().is_relative_to(source.resolve()):
            raise QuantError('UNSAFE_SOURCE_EVIDENCE','凭据必须是目录内普通文件')
        if hashlib.sha256(target.read_bytes()).hexdigest()!=expected:
            raise QuantError('CORRUPT_SOURCE_EVIDENCE','证明文件与声明哈希不一致')
        files[relative]=target
    identity=digest(body);root=ledger.path.parent/'qualifications';destination=root/identity
    with publication_lock(ledger.path.parent):
        if not destination.exists():
            pending=root/('.pending-'+uuid4().hex);pending.mkdir(parents=True)
            try:
                for relative,path in files.items():
                    copy=pending/relative;copy.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,copy)
                write_json(pending/'qualification.json',body)
                pending.rename(destination)
            finally:
                if pending.exists():shutil.rmtree(pending)
        if (destination.is_symlink() or json.loads((destination/'qualification.json').read_text())!=body
                or any((destination/relative).is_symlink() or not (destination/relative).is_file()
                       or hashlib.sha256((destination/relative).read_bytes()).hexdigest()!=expected
                       for relative,expected in body['evidence_files'].items())):
            raise QuantError('CORRUPT_SOURCE_EVIDENCE','已冻结的来源凭据缺失或改变，不能覆盖历史归档')
        with ledger.transaction():
            ledger.connection.execute('INSERT OR IGNORE INTO source_qualifications VALUES(?,?,?,?)',
                (identity,body['series_id'],canonical(body),now_utc()))
    return {'qualification_id':identity,'decision':body['decision'],'evidence_type':body['evidence_type']}


def load_evidence(connection,root,identity,knowledge_cutoff):
    """Resolve a frozen reference, including its registration clock and original files."""
    if not isinstance(identity,str) or len(identity)!=64 or any(c not in '0123456789abcdef' for c in identity):
        raise QuantError('INVALID_SOURCE_REFERENCE','来源引用须为确切资格内容哈希')
    row=connection.execute('SELECT payload,created_at FROM source_qualifications WHERE qualification_id=?',(identity,)).fetchone()
    if row is None:raise QuantError('SOURCE_EVIDENCE_MISSING','来源引用没有已登记凭据')
    try:
        body=json.loads(row['payload'] if hasattr(row,'keys') else row[0])
        created=row['created_at'] if hasattr(row,'keys') else row[1]
        if not isinstance(body,dict) or not isinstance(body.get('evidence_files'),dict):
            raise ValueError('invalid source evidence shape')
        if digest(body)!=identity:raise QuantError('CORRUPT_SOURCE_EVIDENCE','来源资格内容与身份不一致')
        if utc(created)>utc(knowledge_cutoff) or utc(body['reviewed_at'])>utc(knowledge_cutoff):
            raise QuantError('SOURCE_NOT_KNOWN','知识截止时该资格尚未核验或登记')
    except QuantError:
        raise
    except (ValueError,TypeError,KeyError,AttributeError) as exc:
        raise QuantError('CORRUPT_SOURCE_EVIDENCE','来源资格登记内容无法核验') from exc
    directory=Path(root)/'qualifications'/identity
    try:
        if any(p.is_symlink() for p in (directory.parent,directory,directory/'qualification.json')):
            raise QuantError('CORRUPT_SOURCE_EVIDENCE','来源凭据目录不能引用链接')
        if json.loads((directory/'qualification.json').read_text())!=body:
            raise QuantError('CORRUPT_SOURCE_EVIDENCE','本地资格归档与登记内容不一致')
        for relative,expected in body['evidence_files'].items():
            path=directory/relative
            if (Path(relative).is_absolute() or '..' in Path(relative).parts or path.is_symlink()
                    or not path.resolve().is_relative_to(directory.resolve()) or not path.is_file()
                    or hashlib.sha256(path.read_bytes()).hexdigest()!=expected):
                raise QuantError('CORRUPT_SOURCE_EVIDENCE','本地来源凭据缺失或改变')
    except (OSError,ValueError,KeyError,TypeError) as exc:
        if isinstance(exc,QuantError):raise
        raise QuantError('CORRUPT_SOURCE_EVIDENCE','来源凭据归档无法核验') from exc
    return {'qualification_id':identity,'payload':body,'created_at':created}


def require_qualification(connection,root,metadata,series_id,as_of,*,knowledge_cutoff=None):
    if knowledge_cutoff is None:
        row=connection.execute('SELECT qualification_id,payload FROM source_qualifications WHERE series_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1',(series_id,)).fetchone()
    else:
        rows=connection.execute('SELECT qualification_id,payload,created_at FROM source_qualifications WHERE series_id=? ORDER BY created_at DESC,rowid DESC',(series_id,)).fetchall()
        row=next((r for r in rows if utc(r[2])<=utc(knowledge_cutoff)),None)
    if not row:raise QuantError('SOURCE_EVIDENCE_MISSING','原价标签未取得来源单位证明，不能执行/估值')
    identity,encoded=row[0],row[1];body=json.loads(encoded)
    if digest(body)!=identity:raise QuantError('CORRUPT_SOURCE_EVIDENCE','来源资格内容与身份不一致')
    if body.get('schema_version')!=1 or set(body)!=FIELDS:
        raise QuantError('SOURCE_SCOPE_MISMATCH','证券原价必须引用证券单位资格，不能借用其他资产凭据')
    if body['decision']!='QUALIFIED' or body['evidence_type']!='actual' or utc(body['reviewed_at'])>utc(as_of) or utc(body['valid_until'])<=utc(as_of):
        raise QuantError('SOURCE_NOT_QUALIFIED','来源证据未通过实际核验或不在有效期')
    if set(body['sources'])!=set(metadata['source']) or not set(metadata['symbols'])<=set(body['scope_symbols']):
        raise QuantError('SOURCE_SCOPE_MISMATCH','行情来源/篮子超出核验范围')
    load_evidence(connection,root,identity,knowledge_cutoff or now_utc())
    return {'qualification_id':identity,'decision':'QUALIFIED','valid_until':body['valid_until']}
