"""Connection usage is explicitly declared; never guess dynamic identifiers."""
import json
from app.bootstrap import admission, connection_settings as settings, operational_policy
from app.bootstrap.task_loader import discover_task_specs
from app.bootstrap.timebase import business_now

def _usage_index():
    """Build fresh references once per request, without per-task policy queries."""
    result = {}
    from app.bootstrap.task_packages import registry
    specs = {spec['pid']: spec for spec in discover_task_specs()}
    for pid, record in registry().items():
        if not record.get('deleted_at'):
            specs.setdefault(pid, {'pid': pid, 'task_name': record.get('task_name', '')})
    if not specs:
        return result
    with admission.store() as db:
        policies = dict(db.execute("SELECT key,payload FROM settings WHERE key LIKE 'connections:%' OR key LIKE 'task:%'"))
    for spec in specs.values():
        pid = spec['pid']
        raw_access = policies.get('connections:' + pid)
        access = json.loads(raw_access) if raw_access is not None else {'mode': 'restricted', 'connections': []}
        policy = {**operational_policy.TASK_DEFAULT, **json.loads(policies.get('task:' + pid, '{}'))}
        identifiers = set(access['connections']) | set(policy['declared_connections']) | set(policy['test_connections'].values())
        for identifier in identifiers:
            result.setdefault(identifier, []).append({'pid': pid, 'name': spec.get('task_name') or pid, 'mode': access['mode']})
    return result

def usage(identifier):
    return _usage_index().get(identifier, [])

def summary():
    identifiers = [key for key in settings.profiles() if key != 'platform']
    if not identifiers:
        return []
    references = _usage_index()
    with admission.store() as db:
        tests = dict(db.execute("SELECT key,payload FROM settings WHERE key LIKE 'connection-test:%'"))
    return [{'id': key, 'usage': references.get(key, []),
             'last_test': json.loads(tests.get('connection-test:' + key, '{}'))} for key in identifiers]

def record_test(identifier, revision, ready, elapsed):
    value = {'ready': bool(ready), 'elapsed_ms': round(elapsed, 1), 'at': str(business_now()), 'revision': revision}
    with admission.store() as db:
        db.replace('settings', ('key', 'payload'), ('connection-test:' + identifier, json.dumps(value)))

def change(identifier, action, revision, confirm, actor):
    if identifier == 'platform':
        raise ValueError('平台连接不能通过业务连接生命周期操作修改。')
    with settings._store() as db:
        db.execute('BEGIN')
        row = db.execute('SELECT revision,payload FROM profiles WHERE id=?', (identifier,)).fetchone()
        if not row or row[0] != revision:
            raise RuntimeError('连接已变化，请刷新。')
        value = settings._decode(row[1], identifier)
        references = usage(identifier)
        if action == 'delete':
            if confirm != identifier or references or value.get('enabled', True):
                raise ValueError('请先停用连接、解除全部声明/授权/测试映射，并输入连接标识确认。兼容模式中的动态使用仍需人工核对。')
            db.execute('DELETE FROM profiles WHERE id=?', (identifier,))
        elif action in ('disable', 'enable', 'archive'):
            value['enabled'] = action == 'enable'
            value['archived'] = action == 'archive'
            encrypted = settings._cipher('business').encrypt(json.dumps(value, ensure_ascii=False).encode())
            db.execute('UPDATE profiles SET revision=revision+1,payload=? WHERE id=?', (encrypted, identifier))
        else:
            raise ValueError('未知连接操作。')
    from app.common.db.engine_pool import dispose
    dispose(identifier)
