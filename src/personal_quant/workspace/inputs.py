"""Immutable historical inputs, bound to a run instead of mutable series heads."""
import json
from ..common import QuantError, canonical, digest
from ..data.store import DataStore
from ..data.selection import factor_snapshot


def capture(store):
    roles = {}
    for role in ('signal', 'execution', 'valuation'):
        _, meta, calendar = store.load_role(role)
        roles[role] = {'snapshot_id': meta['snapshot_id'], 'calendar_hash': calendar.hash,
                       'data_type': meta['data_type'], 'price_basis': meta['price_basis']}
    return {'schema_version': 1, 'run_mode': 'frozen_replay', 'roles': roles,
            'factor_snapshot_id': factor_snapshot(store)}


def bind(book, store, run_id):
    key = 'simulation-inputs:' + run_id
    row = book.connection.execute('SELECT details FROM tasks WHERE task_id=?', (key,)).fetchone()
    if row:
        return require(book, store, run_id)
    if book.connection.execute('SELECT 1 FROM simulation_checkpoints WHERE run_id=?', (run_id,)).fetchone():
        raise QuantError('LEGACY_INPUTS_UNVERIFIED', '旧运行缺少完整输入登记；保留原报告并建立新实验')
    body = capture(store)
    body['input_bundle_id'] = digest(body)
    book.record_task(key, 'SUCCESS', body)
    return body


def require(book, store, run_id):
    row = book.connection.execute('SELECT details FROM tasks WHERE task_id=?', ('simulation-inputs:' + run_id,)).fetchone()
    if not row:
        raise QuantError('LEGACY_INPUTS_UNVERIFIED', '运行缺少冻结输入登记，不从当前latest猜测原始依据')
    try:
        body = json.loads(row[0])
        if (body['schema_version'] != 1 or body['run_mode'] != 'frozen_replay'
                or digest({k: v for k, v in body.items() if k != 'input_bundle_id'}) != body['input_bundle_id']
                or set(body['roles']) != {'signal', 'execution', 'valuation'}):
            raise ValueError('identity')
        for role, ref in body['roles'].items():
            _, meta, calendar = store.load(ref['snapshot_id'])
            if calendar.hash != ref['calendar_hash'] or meta['data_type'] != ref['data_type'] or meta['price_basis'] != ref['price_basis']:
                raise ValueError(role)
        return body
    except (KeyError, TypeError, ValueError) as exc:
        raise QuantError('CORRUPT_SIMULATION_INPUTS', '冻结输入登记或快照不完整，不能继续或比较') from exc


def pinned(store, body):
    result = DataStore(store.root)
    result.frozen_inputs = body
    return result


def verify_checkpoints(book, run_id, body):
    expected = body['roles']['signal']['snapshot_id']
    for row in book.connection.execute('SELECT details FROM simulation_checkpoints WHERE run_id=?', (run_id,)):
        detail = json.loads(row[0])
        if (detail.get('input_bundle_id') != body['input_bundle_id']
                or detail.get('data', {}).get('snapshot_id') != expected):
            raise QuantError('LEGACY_INPUTS_UNVERIFIED', '日检查点与冻结输入不同；不以初始快照冒充实际输入')
