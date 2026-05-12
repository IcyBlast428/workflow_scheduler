from flask import request, make_response

from app.bootstrap.global_vars import error_msg
from app.settings import AUTH_ADMIN_TOKEN


PUBLIC_API_PATHS = {
    '/api/user/login',
    '/api/user/health',
}


def init_middleware(app):
    '''
    中间件或拦截器
    :param app: 实例化对象
    :return:
    '''

    @app.before_request
    def print_request_info():
        if request.method != 'OPTIONS' and request.path.startswith('/api') and 'favicon.ico' not in request.full_path:
            if request.path in PUBLIC_API_PATHS:
                return None
            token = request.headers.get("X-Token") or request.args.get("token")
            if not AUTH_ADMIN_TOKEN or token != AUTH_ADMIN_TOKEN:
                loginerr = error_msg()
                loginerr['code'] = 50008
                loginerr['message'] = 'invalid or missing token'
                return loginerr
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
        resp.headers['Access-Control-Allow-Origin'] = '*'
        resp.headers['Access-Control-Allow-Methods'] = 'HEAD, OPTIONS, GET, POST, DELETE, PUT'
        resp.headers[
            'Access-Control-Allow-Headers'] = 'Content-Type, Content-Length, Authorization, Accept, X-Requested-With , X-Token'
        return resp
