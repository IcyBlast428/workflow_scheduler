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
