"""Small, read-only status metadata; no Parquet scan or engine/dependency runs."""
import json
from ..common import QuantError
from ..portfolio import Ledger
from .service import read_workspace


def describe(directory):
    root,identity,config,_=read_workspace(directory);runtime=root/config.runtime_dir
    book=Ledger.read_only(runtime/'account.sqlite','demo');rows=[]
    try:
        if identity['kind']=='options':
            rows=[{'用途':role,'状态':'不需要','原因':'当前为期权原生模拟，使用冻结合成请求；不需要ETF用途绑定'} for role in ['signal','execution','valuation']]
            rows.append({'用途':'期权Greeks行情','状态':'不需要','原因':'本月度价格/权利金规则不使用行情Greeks；理论风险工具另标情景，不提升来源资格'})
            setups=list((runtime/'simulation/setups').glob('*/setup-manifest.json'))
            rows.append({'用途':'期权配置','状态':'已冻结合成输入' if setups else '待准备输入','数量':len(setups),
                '原因':'配置只冻结输入，执行前仍复核；不是实际行情或账户权限'})
            exists=book.connection.execute("SELECT 1 FROM sqlite_master WHERE name='simulation_runs'").fetchone()
            run=book.connection.execute('SELECT * FROM simulation_runs ORDER BY updated_at DESC LIMIT 1').fetchone() if exists else None
            if run:
                details=json.loads(run['details']);settings=json.loads((runtime/'simulation/options'/run['run_id']/'settings.json').read_text())
                if not isinstance(details,dict) or not isinstance(settings,dict):
                    raise QuantError('CORRUPT_STATUS_METADATA','期权状态元数据必须为对象，未执行引擎或修复')
                rows.append({'用途':'期权运行','状态':run['status'],'数据类型':'合成历史前缀',
                    '当前推进日':run['through_session'] or '尚未推进','估值时点':details.get('as_of','尚未推进'),
                    '模式':'公共计划（执行时复核）' if settings.get('plan_policy_hash') else '仅研究调度',
                    '原因':'不是实盘/实时行情；查看状态不重跑引擎'})
            else:rows.append({'用途':'期权运行','状态':'尚未建立','原因':'准备并选择配置后显式建立运行'})
            return rows
        heads=runtime/'data/series-heads.json';published=json.loads(heads.read_text()) if heads.exists() else {}
        if not isinstance(published,dict):raise QuantError('CORRUPT_STATUS_METADATA','用途登记元数据必须为对象')
        for role in ['signal','execution','valuation']:
            try:
                row=book.connection.execute('SELECT r.series_id,s.head_snapshot_id FROM data_roles r JOIN data_series s ON s.series_id=r.series_id WHERE role=?',(role,)).fetchone()
                if not row:raise QuantError('UNASSIGNED_DATA_ROLE','尚未绑定该用途')
                snapshot=published.get(row[0],{}).get('snapshot_id') or row[1]
                if len(snapshot)!=64 or any(c not in '0123456789abcdef' for c in snapshot):raise QuantError('INVALID_SNAPSHOT','快照身份无效')
                folder=runtime/'data'/snapshot;meta=json.loads((folder/'manifest.json').read_text())
                if meta['snapshot_id']!=snapshot or not (folder/'prices.parquet').is_file():raise QuantError('CORRUPT_SNAPSHOT','登记快照或价格文件缺失')
                basis=','.join(meta['price_basis']);valid=role=='signal' or set(meta['price_basis'])=={'unadjusted'}
                rows.append({'用途':role,'状态':'已登记，未重验原始文件' if valid else '价格口径不符','数据类型':meta['data_type'],
                    '登记截至':meta['end'],'价格口径':basis,'原因':'只读元数据；新鲜度/内容及真实资格由执行前完整检查判定'})
            except (QuantError,OSError,ValueError,KeyError,TypeError) as exc:rows.append({'用途':role,'状态':'缺少所需输入','原因':str(exc)})
        return rows
    finally:book.close()
