from app.api.task.views import *


def task_api(api):
    api.add_resource(Dashboard, '/dashboard')
    api.add_resource(State, '/state')
    api.add_resource(Schedule, '/schedule')
    api.add_resource(Events, '/events')
    api.add_resource(Action, '/editTask')
    api.add_resource(TaskLogs, '/taskLogs')
    api.add_resource(TaskLogDetail, '/taskLogDetail')
    api.add_resource(SystemLogs, '/systemLogs')
    api.add_resource(TaskIds, '/taskids')
    api.add_resource(Groups, '/groups')
    api.add_resource(SystemIds, '/systemids')
    api.add_resource(Reload, '/overloading')
    api.add_resource(Code, '/updatecode')
    api.add_resource(DetailLog, '/logview')
    api.add_resource(CallTask, '/call_task')
