from apscheduler.schedulers.background import BackgroundScheduler
from flask_apscheduler import APScheduler

from app.settings import WFS_ENABLE_SCHEDULER
from app.bootstrap.scheduled_executor import ScheduledExecutor


scheduler = APScheduler(BackgroundScheduler(timezone="Asia/Shanghai"))


def ext_init(app):
    if WFS_ENABLE_SCHEDULER:
        scheduler.init_app(app=app)
        if 'default' in scheduler._scheduler._executors:
            scheduler._scheduler.remove_executor('default')
        scheduler._scheduler.add_executor(ScheduledExecutor(max_workers=20),'default')
        scheduler.start()
