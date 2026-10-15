import secrets

from app.bootstrap.timebase import business_now

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
            'timezone': 'Asia/Shanghai',
            'project': current_app.config.get('APP_NAME'),
        })


class ready(Resource):
    def get(self):
        from app.bootstrap.readiness import snapshot
        data = snapshot()
        return success_msg(data), 200 if data['ready'] else 503


class test(Resource):
    def get(self):
        return success_msg({'message': 'user api is reachable'})
