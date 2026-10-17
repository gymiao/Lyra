"""Immutable option-chain CSV snapshots, with explicit PIT and quote quality."""
from pathlib import Path
import json
import os
import shutil
from uuid import uuid4
import pandas as pd
from ..common import QuantError, decimal, digest, now_utc, utc, write_json
from ..locks import publication_lock
from .contracts import OptionContract

QUOTE_FIELDS = {'contract_id','contract_version','exchange_timestamp','available_at','received_at','bid','ask',
                'bid_size','ask_size','last','last_timestamp','volume','open_interest','open_interest_available_at',
                'underlying_price','underlying_timestamp','source'}
NUMBERS = {'bid','ask','bid_size','ask_size','last','volume','open_interest','underlying_price'}
TIMES = {'exchange_timestamp','available_at','received_at','last_timestamp','open_interest_available_at','underlying_timestamp'}


def normalize_quotes(frame, contracts):
    if set(frame.columns) != QUOTE_FIELDS or frame.empty:
        raise QuantError('INVALID_OPTION_QUOTES','期权报价CSV字段缺失/未知，或没有记录')
    result = []
    identities = {}
    for record in frame.to_dict('records'):
        try:
            contract = contracts[record['contract_id']]
            if record['contract_version'] != contract.version_hash:
                raise QuantError('OPTION_UNIT_CONFLICT','报价未引用确切的合约单位版本')
            for key in NUMBERS:
                if pd.isna(record[key]) or record[key] == '':
                    if key in {'last','volume','open_interest'}:record[key] = None;continue
                    raise QuantError('INVALID_OPTION_QUOTES','必需报价/数量/标的价格不能缺失')
                value = decimal(record[key])
                if value < 0:raise QuantError('INVALID_OPTION_QUOTES','报价/数量不能为负')
                if key in {'bid_size','ask_size','volume','open_interest'} and value != value.to_integral_value():
                    raise QuantError('INVALID_OPTION_QUOTES','报价张数、成交量和持仓量须为整数')
                record[key] = str(value)
            for key in TIMES:
                if pd.isna(record[key]) or record[key] == '':
                    if key in {'last_timestamp','open_interest_available_at'}:record[key] = None;continue
                    raise QuantError('INVALID_OPTION_QUOTES','必需时间不能缺失')
                record[key] = utc(record[key]).isoformat()
            if utc(record['exchange_timestamp']) > utc(record['available_at']) or utc(record['available_at']) > utc(record['received_at']):
                raise QuantError('INVALID_OPTION_QUOTES','报价所属/可用/收到时间次序无效')
            if not isinstance(record['source'],str) or not record['source'].strip():
                raise QuantError('INVALID_OPTION_QUOTES','数据来源缺失')
            identity = (record['contract_id'],record['exchange_timestamp'])
            content = digest(record)
            if identity in identities:
                if identities[identity] != content:raise QuantError('CONFLICTING_OPTION_QUOTE','相同合约和报价时点内容冲突')
                continue
            identities[identity] = content
            result.append(record)
        except (KeyError,TypeError,ValueError) as exc:
            if isinstance(exc,QuantError):raise
            raise QuantError('INVALID_OPTION_QUOTES','报价字段、时间或合约引用无效') from exc
    return sorted(result,key=lambda r:(r['exchange_timestamp'],r['contract_id']))


def quality(record, contract, as_of, *, max_age_seconds, max_underlying_skew_seconds, max_spread_fraction,
            knowledge_cutoff=None):
    # Decisions use a single clock. A frozen historical simulation may process
    # an actual execution-time quote later, without moving its price timestamp
    # or pretending the delayed receipt was known at decision time.
    clock=utc(as_of);knowledge=utc(knowledge_cutoff) if knowledge_cutoff is not None else clock;issues=[]
    if knowledge<clock:raise QuantError('INVALID_OPTION_QUALITY','处理知识截止不能早于价格检查时点')
    contract.require_standard_vanilla()
    if not utc(contract.listed_at)<=clock<utc(contract.last_trade_at):issues.append('CONTRACT_NOT_TRADABLE_AT_DECISION')
    if utc(record['available_at'])>knowledge or utc(record['received_at'])>knowledge or utc(record['exchange_timestamp'])>clock:
        issues.append('QUOTE_NOT_YET_AVAILABLE')
    if (clock-utc(record['exchange_timestamp'])).total_seconds()>max_age_seconds:issues.append('STALE_QUOTE')
    if abs((utc(record['exchange_timestamp'])-utc(record['underlying_timestamp'])).total_seconds())>max_underlying_skew_seconds:
        issues.append('UNDERLYING_TIME_MISMATCH')
    bid,ask=decimal(record['bid']),decimal(record['ask'])
    if bid<=0 or ask<=0 or ask<bid:issues.append('INVALID_BID_ASK')
    elif (ask-bid)/((ask+bid)/2)>decimal(max_spread_fraction):issues.append('WIDE_SPREAD')
    if decimal(record['bid_size'])<=0 or decimal(record['ask_size'])<=0:issues.append('NO_QUOTED_SIZE')
    if bid%contract.tick_size or ask%contract.tick_size:issues.append('INVALID_QUOTE_TICK')
    if decimal(record['underlying_price'])<=0:issues.append('INVALID_UNDERLYING_PRICE')
    return issues


class OptionDataStore:
    def __init__(self, root):self.root=Path(root)

    def save(self, contracts, quotes, metadata):
        allowed={'schema_version','source','data_type','license_terms','unit_evidence','available_time_basis'}
        if set(metadata)!=allowed or metadata['schema_version']!=1 or metadata['data_type'] not in {'synthetic','real_market'}:
            raise QuantError('INVALID_OPTION_METADATA','期权数据需明确来源、用途、单位证据和可用时间口径')
        if any(not isinstance(metadata[k],str) or not metadata[k].strip() for k in allowed-{'schema_version'}):
            raise QuantError('INVALID_OPTION_METADATA','来源说明不能为空')
        contracts=[OptionContract.from_dict(c) if isinstance(c,dict) else OptionContract.from_dict(c.content()) for c in contracts]
        mapping={c.contract_id:c for c in contracts}
        if len(mapping)!=len(contracts):raise QuantError('DUPLICATE_OPTION_CONTRACT','同一快照的合约ID不可重复')
        records=normalize_quotes(quotes,mapping)
        if any(record['source']!=metadata['source'] for record in records):raise QuantError('OPTION_SOURCE_CONFLICT','行来源与快照来源不一致')
        body={'contracts':[mapping[k].content() for k in sorted(mapping)],'quotes':records,'metadata':metadata}
        identity=digest(body);destination=self.root/identity
        with publication_lock(self.root):
            if destination.exists():self.load(identity);return {'snapshot_id':identity,'status':'EXISTING','data_type':metadata['data_type']}
            pending=self.root/('.pending-'+uuid4().hex);pending.mkdir(parents=True)
            try:
                write_json(pending/'chain.json',body)
                write_json(pending/'manifest.json',{'snapshot_id':identity,'created_at':now_utc(),
                    'data_type':metadata['data_type'],'qualification':'UNVERIFIED','rows':len(records)})
                os.rename(pending,destination)
            finally:
                if pending.exists():shutil.rmtree(pending)
        return {'snapshot_id':identity,'status':'SUCCESS','data_type':metadata['data_type'],'qualification':'UNVERIFIED'}

    def load(self, identity):
        if not isinstance(identity,str) or len(identity)!=64 or any(c not in '0123456789abcdef' for c in identity):
            raise QuantError('INVALID_OPTION_SNAPSHOT','快照ID须为内容哈希')
        path=self.root/identity
        if path.is_symlink():raise QuantError('INVALID_OPTION_SNAPSHOT','快照不接受链接')
        try:
            body=json.loads((path/'chain.json').read_text());manifest=json.loads((path/'manifest.json').read_text())
            if digest(body)!=identity or manifest['snapshot_id']!=identity or manifest['data_type']!=body['metadata']['data_type']:
                raise QuantError('CORRUPT_OPTION_SNAPSHOT','期权快照内容或清单改变')
            contracts={c['contract_id']:OptionContract.from_dict(c) for c in body['contracts']}
            normalize_quotes(pd.DataFrame(body['quotes']),contracts)
            return contracts,body['quotes'],body['metadata'],manifest
        except (OSError,ValueError,KeyError,TypeError) as exc:
            if isinstance(exc,QuantError):raise
            raise QuantError('CORRUPT_OPTION_SNAPSHOT','期权快照缺失或结构错误') from exc

    def check(self,identity,as_of,*,max_age_seconds=900,max_underlying_skew_seconds=60,max_spread_fraction=.25):
        if max_age_seconds<0 or max_underlying_skew_seconds<0 or not 0<=decimal(max_spread_fraction)<=1:
            raise QuantError('INVALID_OPTION_QUALITY','报价检查阈值无效')
        contracts,records,metadata,_=self.load(identity)
        result=[]
        for record in records:
            try:issues=quality(record,contracts[record['contract_id']],as_of,max_age_seconds=max_age_seconds,
                max_underlying_skew_seconds=max_underlying_skew_seconds,max_spread_fraction=max_spread_fraction)
            except QuantError as exc:issues=[exc.code]
            result.append({'contract_id':record['contract_id'],'exchange_timestamp':record['exchange_timestamp'],
                           'status':'PASSED' if not issues else 'BLOCKED','issues':issues})
        return {'snapshot_id':identity,'as_of':as_of,'data_type':metadata['data_type'],'checks':result,
                'source_qualification':'UNVERIFIED','executable':False,
                'reason':'报价质量检查不等于来源/账户权限资格，当前仅用于数据诊断和情景研究'}
