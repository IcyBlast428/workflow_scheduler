# coding=utf-8
import sys
sys.path.append(".")
import os
from flask import Flask, send_from_directory
from app.bootstrap import global_vars
from flask_compress import Compress
from app.bootstrap.global_vars import BASE_DIR, CONFIG_DIR
from app.extensions import ext_init
from app.loggings import init_log
from app.middleware import init_middleware
from app.settings import env, FLASK_ENV
from app.urls import init_api
from app.bootstrap.global_vars import error_msg


def create_app():
    '''
    初始化app
    :param env_name: 使用的环境名称
    :return: app实例
    '''
    print(" * current platform: {}".format("Windows" if os.name == "nt" else "Linux"))
    current_env = os.environ.setdefault('WFS_ENV', FLASK_ENV)

    if current_env == 'production':
        print('\033[32m * reminder: current env is production, please use wsgi server\033[0m')
    else:
        print('\033[31m * warning: current env is development\033[0m')
    app = Flask(__name__, static_folder='./dist/static', template_folder='./dist')
    app.config['COMPRESS_REGISTER'] = True  # 为true时对所有返回的数据进行压缩，不希望如此可将它设为False
    Compress(app)
    app.config.from_object(env.get(current_env))
    # 日志初始化
    init_log()
    # 中间件/拦截器
    init_middleware(app=app)
    # 请求接口
    init_api(app=app)
    # 第三方扩展调度
    ext_init(app=app)

    # 初始化时添加index路由
    @app.route('/', defaults={'path': ''})
    @app.route('/<path:path>')
    def index(path):
        if path.startswith('api/'):
            msg = error_msg('api not found')
            msg['code'] = 404
            return msg, 404
        return send_from_directory(os.path.join(app.root_path, 'dist'), 'index.html')

    return app
