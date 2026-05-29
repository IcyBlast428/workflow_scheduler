from apscheduler.schedulers.background import BackgroundScheduler
from flask_apscheduler import APScheduler
from flask_sqlalchemy import SQLAlchemy

from app.settings import WFS_ENABLE_SCHEDULER


scheduler = APScheduler(BackgroundScheduler(timezone="Asia/Shanghai"))
init_database = SQLAlchemy()


def ext_init(app):
    init_database.init_app(app=app)
    if WFS_ENABLE_SCHEDULER:
        scheduler.init_app(app=app)
        scheduler.start()
