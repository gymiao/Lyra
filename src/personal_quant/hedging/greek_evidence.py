"""Frozen provider Delta observations used for read-only qualification checks.

An archived file and a reviewer decision are evidence supplied by the operator,
not an API entitlement or an assertion that a broker will accept an order.
"""
import json
from pathlib import Path

from ..common import QuantError, digest, now_utc, utc
from ..data.qualification import archive_qualification, load_evidence
from ..options.contracts import OptionContract
from .exposure import normalize_delta


FIELDS = {'schema_version','asset_type','series_id','contract','observation','reviewed_at',
          'valid_until','decision','reviewer','reason','evidence_type','evidence_files'}
OBSERVATION_FIELDS = {'contract_version','unit','value','signed_contracts','source','data_type',
                      'as_of','available_at','received_at','model_inputs'}


def series_id(source, contract_version):
    return 'option-greek:'+digest({'source':source,'contract_version':contract_version})


def model_series_id(source, contract_version):
    return 'option-model-greek:'+digest({'source':source,'contract_version':contract_version})


def _series(item,contract):
    function=model_series_id if item['data_type']=='model' else series_id
    return function(item['source'],contract.version_hash)


def _item(item):
    if not isinstance(item,dict) or set(item) not in (OBSERVATION_FIELDS, OBSERVATION_FIELDS|{'qualification_id'}):
        raise QuantError('INVALID_GREEK_EVIDENCE','Delta观察值字段缺失或未知')
    plain={k:item[k] for k in OBSERVATION_FIELDS}
    if item.get('qualification_id') is not None and (not isinstance(item['qualification_id'],str)
            or len(item['qualification_id'])!=64):
        raise QuantError('INVALID_GREEK_EVIDENCE','Delta凭据引用须为确切内容哈希')
    return plain


def _validate(body):
    if (not isinstance(body,dict) or set(body)!=FIELDS or type(body['schema_version']) is not int
            or body['schema_version']!=2 or body['asset_type'] not in {'OPTION_GREEK_OBSERVATION','OPTION_MODEL_GREEK_OBSERVATION'}
            or body['decision'] not in {'QUALIFIED','REJECTED','UNVERIFIED'}
            or body['evidence_type'] not in {'actual','test'}
            or any(not isinstance(body[k],str) or not body[k].strip()
                   for k in ('reviewed_at','valid_until','reviewer','reason'))
            or not isinstance(body['evidence_files'],dict) or len(body['evidence_files'])<2
            or 'observation.json' not in body['evidence_files']):
        raise QuantError('INVALID_GREEK_EVIDENCE','Greek需确切合约、逐笔观察值、原始资料及人工核验')
    contract=OptionContract.from_dict(body['contract']);item=_item(body['observation'])
    model=body['asset_type']=='OPTION_MODEL_GREEK_OBSERVATION'
    if ('qualification_id' in body['observation'] or item['data_type']!=('model' if model else 'provider')
            or not isinstance(item['source'],str) or not item['source'].strip()
            or item['contract_version']!=contract.version_hash
            or body['series_id']!=_series(item,contract)):
        raise QuantError('INVALID_GREEK_EVIDENCE','Greek类型、确切合约或独立资格命名空间不匹配')
    normalize_delta(item,contract,item['signed_contracts'],item['as_of'],item['received_at'],0)
    if model:
        from .model_greek import validate
        validate(item,contract,evidence_type=body['evidence_type'],evidence_files=body['evidence_files'])
    if (utc(body['reviewed_at'])<utc(item['received_at']) or utc(body['reviewed_at'])>utc(now_utc())
            or utc(body['valid_until'])<=utc(body['reviewed_at'])):
        raise QuantError('INVALID_GREEK_EVIDENCE','核验不得早于收到观察值或晚于当前时间，有效期须明确')
    return contract,item


def register(book,body,evidence_directory):
    if book.connection.execute('SELECT version FROM schema_version').fetchone()[0]<5:
        raise QuantError('V19_NOT_ENABLED','Greek凭据需要显式启用v1.9')
    _,item=_validate(body)
    root=Path(evidence_directory)
    if set(body['evidence_files'])=={'observation.json'}:
        raise QuantError('INVALID_GREEK_EVIDENCE','除规范观察值外还需独立原始供应商资料')
    try:
        if json.loads((root/'observation.json').read_text())!=item:
            raise QuantError('GREEK_OBSERVATION_MISMATCH','归档观察值与逐笔规范文件不同')
        if item['data_type']=='model' and json.loads((root/'model-inputs.json').read_text())!=item['model_inputs']:
            raise QuantError('MODEL_INPUT_FILE_MISMATCH','模型规范输入与归档文件不同')
    except (OSError,ValueError,TypeError) as exc:
        if isinstance(exc,QuantError):raise
        raise QuantError('INVALID_GREEK_EVIDENCE','逐笔观察值文件无法读取') from exc
    if book.environment!='demo' and body['evidence_type']!='actual':
        raise QuantError('TEST_EVIDENCE_FORBIDDEN','测试Greek不能授予真实/前向账户资格')
    return archive_qualification(book,body,evidence_directory)


def assess(book,item,contract,knowledge_cutoff):
    """Require the latest known archived decision and the exact observation bytes."""
    contract=OptionContract.from_dict(contract) if isinstance(contract,dict) else contract
    if not isinstance(contract,OptionContract):
        raise QuantError('INVALID_OPTION_CONTRACT','Greek核验需确切期权条款')
    plain=_item(item);known=utc(knowledge_cutoff);checks=[];proof=None
    if book.environment!='demo':
        from ..options.ledger import verify_contract_evidence
        try:verify_contract_evidence(book.path.parent,contract)
        except QuantError as exc:checks.append(exc.code)
    if item.get('data_type') not in {'provider','model'}:checks.append('GREEK_PROVIDER_EVIDENCE_REQUIRED')
    identity=item.get('qualification_id')
    if identity is None:checks.append('GREEK_QUALIFICATION_REQUIRED')
    if identity is not None:
        try:
            proof=load_evidence(book.connection,book.path.parent,identity,knowledge_cutoff)
            body=proof['payload'];frozen_contract,frozen_item=_validate(body)
            if (frozen_contract.version_hash!=contract.version_hash or frozen_item!=plain
                    or body['series_id']!=_series(plain,contract)):
                checks.append('GREEK_OBSERVATION_MISMATCH')
            if (body['decision']!='QUALIFIED' or body['evidence_type']!='actual'
                    or utc(body['valid_until'])<=known):
                checks.append('GREEK_NOT_QUALIFIED')
            latest=next((row for row in book.connection.execute(
                'SELECT qualification_id,created_at FROM source_qualifications WHERE series_id=? ORDER BY created_at DESC,rowid DESC',
                (body['series_id'],)) if utc(row['created_at'])<=known),None)
            if latest is None or latest['qualification_id']!=identity:checks.append('GREEK_SUPERSEDED')
            directory=book.path.parent/'qualifications'/identity
            if json.loads((directory/'observation.json').read_text())!=plain:
                checks.append('GREEK_OBSERVATION_MISMATCH')
            if plain['data_type']=='model' and json.loads((directory/'model-inputs.json').read_text())!=plain['model_inputs']:
                checks.append('MODEL_INPUT_FILE_MISMATCH')
        except QuantError as exc:checks.append(exc.code)
        except (OSError,ValueError,TypeError,KeyError) as exc:
            checks.append('CORRUPT_GREEK_EVIDENCE')
    return {'status':'UNQUALIFIED' if checks else 'QUALIFIED','qualification_id':identity,
            'contract_version':contract.version_hash,'source':plain['source'],'as_of':plain['as_of'],
            'knowledge_cutoff':known.isoformat(),'checks':sorted(set(checks)),'executable':False,
            'meaning':('完整输入与已锁QuantLib模型重算Delta资格，模型输出保持理论性质' if plain['data_type']=='model' else
                       '逐笔供应商Delta凭据核验，不把供应商观察值或理论价格视作可成交报价')}


def assess_candidate(book,candidate,knowledge_cutoff):
    """Check every selected leg whose Delta determined a beta-target candidate."""
    if candidate.get('spec',{}).get('mode')!='beta_target' or not candidate.get('selection'):
        return {}
    items=candidate.get('candidate_inputs',{}).get('greeks',[])
    if not isinstance(items,list) or any(not isinstance(item,dict) for item in items):
        raise QuantError('INVALID_GREEK_EVIDENCE','候选逐腿Delta必须完整保留')
    by_version={item.get('contract_version'):item for item in items}
    if len(by_version)!=len(items):raise QuantError('INVALID_GREEK_EVIDENCE','候选Delta合约版本不得重复')
    result={}
    for leg in candidate['selection']['legs']:
        contract=OptionContract.from_dict(leg['contract'])
        item=by_version.get(contract.version_hash)
        if item is None:raise QuantError('GREEK_QUALIFICATION_REQUIRED','Beta目标候选缺少逐腿Delta')
        result[contract.version_hash]=assess(book,item,contract,knowledge_cutoff)
    return result
