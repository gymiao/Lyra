"""Append-only closure of research intents; never cancels orders or releases assets."""
import json

from ..common import QuantError, canonical, digest, now_utc, utc
from ..locks import publication_lock
from .allocation_store import resources

PREFIX = 'hedge-intent-action:'
FIELDS = {'schema_version', 'request_id', 'hedge_id', 'expected_version',
          'expected_resource_hash', 'action', 'reason'}


def history(book, account_id):
    from .intents import records
    parents = {r['version_hash']: r for r in records(book, account_id)}
    result = []
    closed = set()
    for row in book.connection.execute('SELECT task_id,details FROM tasks WHERE task_id LIKE ?', (PREFIX+'%',)):
        try:
            item = json.loads(row['details'])
            if item['account_id'] != account_id:
                continue
            parent = parents[item['parent_version']]
            request = item['request']
            if (item['environment'] != book.environment
                    or item['record_hash'] != digest({k:v for k,v in item.items() if k != 'record_hash'})
                    or item['request_hash'] != digest(request)
                    or row['task_id'] != PREFIX+digest({'account_id':account_id,'request_id':request['request_id']})
                    or item['hedge_id'] != parent['hedge_id']
                    or item['status'] not in {'CANCELLED', 'EXPIRED'}
                    or item['status'] != request['action']
                    or request['expected_version'] != parent['version_hash']
                    or request['hedge_id'] != parent['hedge_id']
                    or item['hedge_id'] in closed
                    or utc(item['generated_at']) < utc(parent['generated_at'])
                    or (item['status'] == 'EXPIRED' and utc(item['generated_at']) < utc(parent['valid_until']))):
                raise ValueError('identity')
            closed.add(item['hedge_id'])
            result.append(item)
        except (KeyError, TypeError, ValueError) as exc:
            raise QuantError('CORRUPT_HEDGE_INTENT_ACTION', '父意图关闭凭据缺失、重复或改变') from exc
    for item in result:
        if any(r['hedge_id'] == item['hedge_id'] and r['revision'] > parents[item['parent_version']]['revision']
               for r in parents.values()):
            raise QuantError('CORRUPT_HEDGE_INTENT_ACTION', '关闭后存在父意图修订')
    return sorted(result, key=lambda r: (r['generated_at'], r['hedge_id']))


def prepare(book, account_id, request):
    from .intents import records
    if (not isinstance(request, dict) or set(request) != FIELDS
            or type(request['schema_version']) is not int or request['schema_version'] != 1
            or any(not isinstance(request[k], str) or not request[k].strip() for k in FIELDS-{'schema_version'})
            or request['action'] not in {'CANCELLED', 'EXPIRED'}):
        raise QuantError('INVALID_HEDGE_INTENT_ACTION', '关闭需明确父版本、资源版本、动作及原因')
    chain = [r for r in records(book, account_id) if r['hedge_id'] == request['hedge_id']]
    if not chain:
        raise QuantError('UNKNOWN_HEDGE_INTENT', '父意图不存在于该账户')
    parent = max(chain, key=lambda r:r['revision'])
    if request['expected_version'] != parent['version_hash']:
        raise QuantError('STALE_HEDGE_INTENT_VERSION', '父意图已改变，请重新预检')
    if any(r['hedge_id'] == parent['hedge_id'] for r in history(book, account_id)):
        raise QuantError('HEDGE_INTENT_CLOSED', '父意图已关闭；不能再次关闭或恢复')
    if request['expected_resource_hash'] != resources(book, account_id):
        raise QuantError('STALE_HEDGE_RESOURCES', '关闭预检资源已变化')
    if parent['execution_groups']:
        raise QuantError('UNRESOLVED_HEDGE_EXECUTION', '尚未核实执行组结束，不能关闭父意图')
    from .groups import history as groups, progress
    from .group_revisions import heads as group_heads
    for group in group_heads(groups(book, account_id)):
        if group['hedge_id'] == parent['hedge_id'] and progress(book, account_id, group, now_utc())['status'] != 'COMPLETE':
            raise QuantError('UNRESOLVED_HEDGE_EXECUTION', '绑定执行组尚未结束；保留原资源及执行事实')
    generated = now_utc()
    if request['action'] == 'EXPIRED' and utc(generated) < utc(parent['valid_until']):
        raise QuantError('HEDGE_INTENT_NOT_EXPIRED', '尚未到父意图有效期末')
    return {'hedge_id':parent['hedge_id'], 'parent_version':parent['version_hash'],
            'status':request['action'], 'generated_at':generated,
            'ledger_seq':book.sequence(account_id), 'executable':False,
            'releases_reservations':False, 'cancels_broker_orders':False,
            'meaning':'关闭父研究决定；保留原决定、保护引用、持仓与预留，不宣称券商订单已撤销'}


def save(book, account_id, request, *, commit=False):
    with publication_lock(book.path.parent), book.transaction():
        book._require_account(account_id)
        key = PREFIX+digest({'account_id':account_id,
                            'request_id':request.get('request_id') if isinstance(request,dict) else None})
        row = book.connection.execute('SELECT details FROM tasks WHERE task_id=?', (key,)).fetchone()
        if row:
            old = json.loads(row[0])
            history(book, account_id)
            if old['request_hash'] != digest(request):
                raise QuantError('HEDGE_INTENT_ACTION_REQUEST_CONFLICT', '关闭请求ID与内容冲突')
            return old
        body = prepare(book, account_id, request)
        if not commit:
            return {**body, 'status':'PREVIEW', 'proposed_status':body['status']}
        item = {'schema_version':1, 'account_id':account_id, 'environment':book.environment,
                'request':request, 'request_hash':digest(request), **body}
        item['record_hash'] = digest(item)
        book.connection.execute('INSERT INTO tasks VALUES(?,?,?,?)',
                                (key, item['status'], canonical(item), item['generated_at']))
        return item

