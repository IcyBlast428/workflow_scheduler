from app.api.user.views import *


def user_api(api):
    api.add_resource(test, '/test')
    api.add_resource(health, '/health')
    api.add_resource(info, '/info')
    api.add_resource(login, '/login')
    api.add_resource(logout, '/logout')
