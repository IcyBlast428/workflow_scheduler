import secrets
import time
from flask import request, make_response, session, g

from app.bootstrap.global_vars import error_msg
from app.bootstrap.auth_sessions import is_session_active
from app.bootstrap.permissions import identity, allowed
from app.bootstrap.operations import audit


PUBLIC_API_PATHS = {
    '/api/user/login',
    '/api/user/health',
    '/api/user/ready',
}


def init_middleware(app):
    '''
    中间件或拦截器
    :param app: 实例化对象
    :return:
    '''

    @app.before_request
    def print_request_info():
        g.request_started = time.monotonic()
        if request.method != 'OPTIONS' and request.path.startswith('/api') and 'favicon.ico' not in request.full_path:
            if request.path in PUBLIC_API_PATHS:
                return None
            try:
                active = is_session_active(session.get('sid'))
            except Exception:
                app.logger.exception('session validation unavailable')
                return error_msg('authentication service unavailable'), 503
            if not active:
                loginerr = error_msg()
                loginerr['code'] = 50008
                loginerr['message'] = 'session expired or missing'
                return loginerr, 401
            g.identity = identity()
            if not g.identity:
                session.clear()
                message = error_msg('账户已停用，请联系管理员。')
                message['code'] = 50008
                return message, 401
            if not allowed(request.path, request.method, g.identity['role']):
                return error_msg('当前账户没有此操作权限。'), 403
            if request.method in {'POST', 'PUT', 'PATCH', 'DELETE'}:
                supplied = request.headers.get('X-CSRF-Token', '')
                expected = session.get('csrf_token', '')
                if not supplied or not expected or not secrets.compare_digest(supplied, expected):
                    return error_msg('invalid CSRF token'), 403
                if request.is_json and not isinstance(request.get_json(silent=True), dict):
                    return error_msg('请求内容必须为对象。'), 400
        # print("拦截器：" + str(request.method) + str(request.path))
        # print("请求方法：" + str(request.method))
        # print("---请求headers--start--")
        # print(str(request.headers).rstrip())
        # print("---请求headers--end----")
        # print("GET参数：" + str(request.args))
        # print("POST参数：" + str(request.form))

    @app.after_request
    def af_request(resp):
        """
         #请求钩子，跨域调用
        :param resp:
        :return:
        """
        resp = make_response(resp)
        if request.path.startswith('/api'):
            from app.bootstrap.runtime_metrics import record
            endpoint = request.url_rule.rule if request.url_rule else '/api/unknown'
            record('api:'+endpoint,1000*(time.monotonic()-getattr(g,'request_started',time.monotonic())))
        if request.path.startswith('/api'):
            resp.headers['Cache-Control'] = 'no-store'
            if request.method in {'POST','PUT','PATCH','DELETE'} and request.path not in PUBLIC_API_PATHS and request.path != '/api/user/logout' and getattr(g, 'identity', None) and not getattr(g, 'audit_forwarded', False):
                payload = resp.get_json(silent=True) or {}
                body = request.get_json(silent=True) or {}
                payload = payload if isinstance(payload, dict) else {}
                body = body if isinstance(body, dict) else {}
                target = request.args.get('id') or request.args.get('pid') or body.get('pid') or body.get('username') or ''
                from app.bootstrap.permissions import READ_POSTS
                if request.path not in READ_POSTS or request.method != 'POST':
                    audit(g.identity['username'], request.path, target, 'success' if payload.get('code') == 20000 else 'failed', payload.get('message',''))
        resp.headers['X-Content-Type-Options'] = 'nosniff'
        resp.headers['Referrer-Policy'] = 'same-origin'
        return resp
