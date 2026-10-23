from flask_restful import Api

from app.api.task.urls import task_api
from app.api.user.urls import user_api


# 初始化api接口 类似include() prefix为父级地址 子集地址参数参阅flask_restful文档
def init_api(app):
    # 如果以api开始的路由将验证登录状态
    # 用户主接口
    user_api(Api(app=app, prefix='/api/user'))
    # 调度主接口
    task_api(Api(app=app, prefix='/api/taskinfo'))
    from app.api.operations import blueprint
    app.register_blueprint(blueprint)
    from app.api.task_packages import blueprint as packages_blueprint
    app.register_blueprint(packages_blueprint)
    from app.api.database_connections import blueprint as connections_blueprint
    app.register_blueprint(connections_blueprint)
    from app.api.task_publishing import blueprint as publishing_blueprint
    app.register_blueprint(publishing_blueprint)
    from app.api.task_artifacts import blueprint as artifacts_blueprint
    app.register_blueprint(artifacts_blueprint)
