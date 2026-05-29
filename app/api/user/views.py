import json

from flask import current_app, request
from flask_restful import Resource

from app.bootstrap.global_vars import error_msg, success_msg
from app.common.pyDes import do_decrypt
from app.settings import APP_AVATAR_URL, AUTH_ADMIN_PASSWORD_CIPHER, AUTH_ADMIN_TOKEN, AUTH_ADMIN_USERNAME


class TabrResource(Resource):
    def options(self):
        return {
            'Allow': '*'
        }, 200, {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'HEAD, OPTIONS, GET, POST, DELETE, PUT',
            'Access-Control-Allow-Headers': 'Content-Type, Content-Length, Authorization, Accept, X-Requested-With , X-Token',
        }


class login(Resource):
    def post(self):
        req = str(request.data, encoding="utf8")
        logininfo = json.loads(req or '{}')
        username = logininfo.get("username")
        password = logininfo.get("password")

        if not AUTH_ADMIN_PASSWORD_CIPHER or not AUTH_ADMIN_TOKEN:
            return error_msg("管理员登录未配置")

        decode_pass = do_decrypt(AUTH_ADMIN_PASSWORD_CIPHER)
        if username == AUTH_ADMIN_USERNAME and password == decode_pass:
            data = {
                'token': AUTH_ADMIN_TOKEN,
                'name': '测试用户',
                'age': 18,
                'height': 1.88,
            }
            return success_msg(data)
        return error_msg("用户名或密码错误")


class logout(Resource):
    def post(self):
        return success_msg({'message': 'logout success'})


class info(Resource):
    def get(self):
        data = {
            'project': current_app.config.get('APP_NAME'),
            'avatar': APP_AVATAR_URL,
            'introduction': "I am a super administrator",
            'name': "Super Admin",
            'roles': ["admin"],
        }
        return success_msg(data)


class health(Resource):
    def get(self):
        return success_msg({
            'status': 'ok',
            'project': current_app.config.get('APP_NAME'),
        })


class test(Resource):
    def get(self):
        return success_msg({'message': 'user api is reachable'})
