"""Template-specific engine evidence audit. Passing never grants account permission."""
import hashlib
import json
from pathlib import Path
from ..common import QuantError,decimal as D,digest,now_utc
from .engine import LEAN_COMMIT

REQUIRED_CASES={
    'cash_secured_put':['cash_secured_put','cash_put_assignment','cash_put_worthless_expiry'],
    'covered_call':['covered_call','covered_call_assignment','covered_call_worthless_expiry'],
    'protective_put':['protective_put','protective_put_exercise','protective_put_worthless_expiry'],
    'long_call':['long_call','long_call_exercise','long_call_worthless_expiry'],
    'long_put':['long_put','long_put_itm_exit','long_put_worthless_expiry'],
    'collar':['collar','collar_call_assignment','collar_put_exercise','collar_worthless_expiry'],
    'bull_call_debit_spread':['bull_call_debit_spread','bull_call_partial_assignment','bull_call_worthless_expiry'],
    'bear_put_debit_spread':['bear_put_debit_spread','bear_put_partial_assignment','bear_put_worthless_expiry'],
    'bull_put_credit_spread':['bull_put_credit_spread','bull_put_credit_spread_partial_assignment','bull_put_credit_spread_worthless_expiry'],
    'bear_call_credit_spread':['bear_call_credit_spread','bear_call_credit_spread_partial_assignment','bear_call_credit_spread_worthless_expiry'],
    'long_straddle':['long_straddle','long_straddle_call_exercise','long_straddle_put_itm_exit','long_straddle_worthless_expiry'],
    'long_strangle':['long_strangle','long_strangle_call_exercise','long_strangle_put_itm_exit','long_strangle_worthless_expiry']}
for _name in ('iron_condor','iron_butterfly'):
    REQUIRED_CASES[_name]=[_name,_name+'_put_assignment',_name+'_call_assignment',_name+'_worthless_expiry']
ENGINE_TEMPLATES=frozenset(REQUIRED_CASES)


def assess_engine(file,template_id,*,project=None):
    if template_id not in REQUIRED_CASES:raise QuantError('UNKNOWN_OPTION_TEMPLATE','未定义该模板的生命周期验收范围')
    file=Path(file);checks=[];validated=[]
    def block(code,detail):checks.append({'code':code,'detail':detail})
    try:
        proof=json.loads(file.read_text());root=file.parent
        if proof.get('status')!='PASSED' or proof.get('data_type')!='synthetic_mechanical_fixture' or proof.get('engine_commit')!=LEAN_COMMIT or proof.get('sdk')!='10.0.100':
            block('ENGINE_SCOPE_OR_VERSION','需要固定版本的LyraX合成生命周期报告；官方冒烟或月度终值不能替代')
        from .adapter_resources import source_hashes
        current=source_hashes(Path(project)/'engines/lean' if project is not None else None)
        if current!=proof.get('adapter_source'):block('ENGINE_SOURCE_CHANGED','引擎适配源码与报告不一致，须按当前源码重新验证')
        dll=root/'adapter-bin/LyraX.Options.dll'
        if not dll.is_file() or hashlib.sha256(dll.read_bytes()).hexdigest()!=proof.get('adapter_dll_sha256'):
            block('ENGINE_BINARY_CHANGED','已验证程序集缺失或改变')
        for name in REQUIRED_CASES[template_id]:
            case=proof.get('cases',{}).get(name)
            if not case:block('MISSING_LIFECYCLE_CASE',name);continue
            try:
                directory=root/name;input_body=json.loads((directory/'input.json').read_text())
                manifest=json.loads((directory/'data-files.json').read_text())
                if case.get('status')!='PASSED' or digest(input_body)!=case['input_hash'] or digest(manifest)!=case['data_manifest_hash']:
                    raise QuantError('CORRUPT_ENGINE_CASE','输入或数据清单身份不一致')
                if abs(D(case['actual_equity'])-D(case['expected_equity']))>D('.01'):raise QuantError('CORRUPT_ENGINE_CASE','引擎与独立资金预期不一致')
                summaries=list(directory.glob('*-summary.json'))
                if len(summaries)!=1:raise QuantError('CORRUPT_ENGINE_CASE','引擎终态报告缺失或重复')
                summary=json.loads(summaries[0].read_text())
                if summary['state']['Status']!='Completed' or summary['state'].get('RuntimeError') or D(summary['statistics']['End Equity'].replace(',','').replace('$',''))!=D(case['actual_equity']):
                    raise QuantError('CORRUPT_ENGINE_CASE','引擎终态或统计与验收记录不一致')
                events=json.loads((directory/'engine-events.json').read_text())
                if not events:raise QuantError('CORRUPT_ENGINE_CASE','缺少引擎实际成交事件')
                if name.endswith('worthless_expiry'):
                    expired=[e for e in events if e['order_type']=='OptionExercise' and e['symbol']==e['order_symbol']]
                    count=len(input_body['legs'])
                    if len(expired)!=count or len({e['order_symbol'] for e in expired})!=count or any(e['in_the_money'] for e in expired):raise QuantError('CORRUPT_ENGINE_CASE','缺少逐腿官方无价值到期事件')
                data=directory/'data' if (directory/'data').is_dir() else root/'data'
                for relative,expected in manifest.items():
                    item=data/relative
                    if not item.resolve().is_relative_to(data.resolve()) or not item.is_file() or hashlib.sha256(item.read_bytes()).hexdigest()!=expected:
                        raise QuantError('CORRUPT_ENGINE_CASE','冻结执行数据缺失或改变')
                if name!=template_id:
                    bridge=json.loads((directory/'ledger-bridge.json').read_text())
                    if bridge!=case['ledger_bridge'] or D(bridge['equity'])!=D(case['expected_equity']):
                        raise QuantError('CORRUPT_ENGINE_CASE','生命周期统一账本桥接不一致')
                validated.append(name)
            except (OSError,ValueError,KeyError,TypeError) as exc:block('CORRUPT_ENGINE_CASE',name+': '+str(exc))
    except (OSError,ValueError,KeyError,TypeError) as exc:
        block('ENGINE_EVIDENCE_UNAVAILABLE',str(exc));proof={}
    return {'status':'BLOCKED' if checks else 'PASSED','scope':'synthetic_engine_lifecycle_only',
        'profile_version':'option-lifecycle/1.0.0',
        'profile_hash':digest({'required_cases':REQUIRED_CASES[template_id],
            'source_hash':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}),
        'template_id':template_id,'required_cases':REQUIRED_CASES[template_id],'validated_cases':validated,'checks':checks,
        'evidence_hash':digest(proof),'assessed_at':now_utc(),'executable':False,'source_qualified':False,
        'remaining_gates':['月度/账户/资金/行情资格及当前报价','对账、权限及资源激活事务']}
