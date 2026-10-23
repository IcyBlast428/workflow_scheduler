"""Shared identities, role policy and bounded login attempts."""
from app.bootstrap.timebase import business_now

import datetime as dt
import hashlib
from flask import session
from werkzeug.security import check_password_hash

from app.bootstrap.database import GaussDB
from app.settings import AUTH_ADMIN_PASSWORD_HASH, AUTH_ADMIN_USERNAME

ROLES = {'viewer', 'operator', 'admin'}
READ_POSTS = {'/api/user/logout', '/api/taskinfo/taskLogs', '/api/taskinfo/taskLogDetail',
              '/api/taskinfo/systemLogs', '/api/taskinfo/taskids', '/api/taskinfo/groups',
              '/api/taskinfo/systemids', '/api/taskinfo/logview', '/api/taskinfo/schedule'}
VIEWER_GETS = {'/api/user/info', '/api/taskinfo/state', '/api/taskinfo/events',
               '/api/taskinfo/detail', '/api/taskinfo/matrix', '/api/taskinfo/runs',
               '/api/taskinfo/run', '/api/taskinfo/run-download', '/api/taskinfo/schedule'}
VIEWER_GETS.update({'/api/taskinfo/artifacts', '/api/taskinfo/artifact-download'})
VIEWER_POSTS = {'/api/user/logout', '/api/taskinfo/taskLogs', '/api/taskinfo/taskLogDetail',
                '/api/taskinfo/taskids', '/api/taskinfo/groups', '/api/taskinfo/logview'}


def user_record(username):
    if username == AUTH_ADMIN_USERNAME:
        return {'username': username, 'password_hash': AUTH_ADMIN_PASSWORD_HASH, 'role': 'admin', 'enabled': 1}
    with GaussDB() as db:
        rows = db.execute_query_sql('SELECT username,password_hash,role,enabled FROM wfs_users WHERE username=?', params=(username,), return_json=True)
    return rows[0] if rows else None


def identity():
    record = user_record(session.get('username', AUTH_ADMIN_USERNAME))
    if not record or not record['enabled'] or record['role'] not in ROLES:
        return None
    return {'username': record['username'], 'role': record['role']}


def allowed(path, method, role):
    if role == 'admin':
        return True
    # The legacy operator role now follows the same read-only policy. Unknown
    # roles never receive access, and newly added endpoints default to denied.
    if role not in {'viewer', 'operator'}:
        return False
    return (method in {'GET', 'HEAD'} and path in VIEWER_GETS or
            method == 'POST' and path in VIEWER_POSTS)


def login_keys(username, address):
    return [hashlib.sha256(value.encode()).hexdigest() for value in ('ip:' + address, 'user:' + username + ':' + address)]


def check_login_limit(username, address):
    now = business_now()
    with GaussDB() as db:
        for index, key in enumerate(login_keys(username, address)):
            rows = db.execute_query_sql('SELECT failures,window_start FROM wfs_login_limits WHERE key_hash=?', params=(key,))
            if rows:
                started = rows[0][1]
                if isinstance(started, str):
                    started = dt.datetime.fromisoformat(started)
                if now - started < dt.timedelta(minutes=15) and int(rows[0][0]) >= (20 if index == 0 else 5):
                    return False
    return True


def record_login_failure(username, address):
    now = business_now()
    with GaussDB() as db:
        db.begin_transaction()
        try:
            if not db._local_sqlite:
                db.execute_sql('LOCK TABLE wfs_login_limits IN EXCLUSIVE MODE')
            for key in login_keys(username, address):
                rows = db.execute_query_sql('SELECT failures,window_start FROM wfs_login_limits WHERE key_hash=?', params=(key,))
                if not rows:
                    db.execute_sql('INSERT INTO wfs_login_limits(key_hash,failures,window_start) VALUES(?,1,?)', params=(key,now))
                else:
                    started = rows[0][1]
                    if isinstance(started,str):
                        started = dt.datetime.fromisoformat(started)
                    if now - started >= dt.timedelta(minutes=15):
                        db.execute_sql('UPDATE wfs_login_limits SET failures=1,window_start=? WHERE key_hash=?', params=(now,key))
                    else:
                        db.execute_sql('UPDATE wfs_login_limits SET failures=failures+1 WHERE key_hash=?', params=(key,))
            db.set_commit()
        except Exception:
            db.set_rollback()
            raise
