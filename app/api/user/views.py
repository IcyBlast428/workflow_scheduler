import secrets

from flask import current_app, request, session
from flask_restful import Resource
from werkzeug.security import check_password_hash
from app.bootstrap.auth_sessions import create_session, revoke_session
from app.bootstrap.permissions import user_record, check_login_limit, record_login_failure, identity
from app.bootstrap.operations import audit

from app.bootstrap.global_vars import error_msg, success_msg
from app.settings import APP_AVATAR_URL, AUTH_ADMIN_PASSWORD_HASH, AUTH_ADMIN_USERNAME


class TabrResource(Resource):
    def options(self):
        return {}, 204


class login(Resource):
    def post(self):
        logininfo = request.get_json(silent=True)
        if not isinstance(logininfo, dict):
            return error_msg('invalid login request'), 400
        username = str(logininfo.get("username") or '')[:100]
        password = logininfo.get("password")

        if not check_login_limit(username, request.remote_addr or ''):
            return error_msg('登录尝试过多，请在 15 分钟后重试。'), 429
        record = user_record(username)
        if record and record['enabled'] and record['password_hash'] and isinstance(password, str) and len(password) <= 1024 and check_password_hash(record['password_hash'], password):
            revoke_session(session.get('sid'))
            session_id = create_session(current_app.permanent_session_lifetime)
            session.clear()
            session.permanent = True
            session['sid'] = session_id
            session['username'] = username
            session['csrf_token'] = secrets.token_urlsafe(32)
            data = {
                'csrf_token': session['csrf_token'],
                'name': username,
            }
            audit(username, 'login', username)
            return success_msg(data)
        record_login_failure(username, request.remote_addr or '')
        audit(username, 'login', username, 'failed', 'invalid credentials')
        return error_msg("用户名或密码错误"), 401


class logout(Resource):
    def post(self):
        audit(session.get('username', AUTH_ADMIN_USERNAME), 'logout', '')
        revoke_session(session.get('sid'))
        session.clear()
        return success_msg({'message': 'logout success'})


class info(Resource):
    def get(self):
        data = {
            'project': current_app.config.get('APP_NAME'),
            'avatar': APP_AVATAR_URL,
            'introduction': "I am a super administrator",
            'name': identity()['username'],
            'roles': [identity()['role']],
            'csrf_token': session.get('csrf_token'),
        }
        return success_msg(data)


class health(Resource):
    def get(self):
        return success_msg({
            'status': 'ok',
            'project': current_app.config.get('APP_NAME'),
        })


class ready(Resource):
    def get(self):
        import shutil
        import datetime
        import os
        import requests
        from app.bootstrap.database import GaussDB
        from app.bootstrap.operations import service_state
        from app.bootstrap.global_vars import DATA_DIR
        from app.settings import WFS_ENABLE_SCHEDULER, WFS_SCHEDULER_CONTROL_URL
        try:
            with GaussDB() as db:
                for table in ('wfs_task_config','wfs_executions','wfs_auth_sessions','wfs_config_application'):
                    db.execute_query_sql(f'SELECT 1 FROM {table} LIMIT 0')
            if shutil.disk_usage(DATA_DIR).free < int(os.environ.get('WFS_MIN_FREE_MB', '100')) * 1024 * 1024:
                raise RuntimeError('data directory free space below configured minimum')
            if WFS_ENABLE_SCHEDULER:
                from app.extensions import scheduler
                state = service_state()
                if not scheduler.running or not state['ready'] or not state['heartbeat']:
                    raise RuntimeError('scheduler initialization incomplete')
                if (datetime.datetime.now() - datetime.datetime.fromisoformat(state['heartbeat'])).total_seconds() > 120:
                    raise RuntimeError('scheduler heartbeat stale')
            elif WFS_SCHEDULER_CONTROL_URL:
                response = requests.get(WFS_SCHEDULER_CONTROL_URL.rstrip('/') + '/api/user/ready', timeout=5)
                if response.status_code != 200:
                    raise RuntimeError('scheduler not ready')
            return success_msg({'ready':True, 'database':True, 'scheduler':True})
        except Exception as exc:
            current_app.logger.warning('readiness unavailable: %s', exc)
            return error_msg('服务尚未就绪，请查看运行日志。'), 503


class test(Resource):
    def get(self):
        return success_msg({'message': 'user api is reachable'})
