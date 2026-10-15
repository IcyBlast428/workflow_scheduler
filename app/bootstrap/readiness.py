"""Public, bounded readiness checks without credentials or internal addresses."""
import datetime as dt
import logging
import os
import shutil

from app.bootstrap.timebase import business_now

logger = logging.getLogger(__name__)


def snapshot():
    from app.bootstrap.database import GaussDB
    from app.bootstrap.global_vars import DATA_DIR
    from app.bootstrap.operations import service_state
    from app.settings import WFS_ENABLE_SCHEDULER, WFS_SCHEDULER_CONTROL_URL
    components = {'api': {'status': 'ready', 'message': '接口正常'}}
    try:
        with GaussDB() as db:
            for table in ('wfs_task_config', 'wfs_executions', 'wfs_auth_sessions', 'wfs_config_application',
                          'wfs_run_summary', 'wfs_notifications', 'wfs_package_tasks', 'wfs_task_releases'):
                db.execute_query_sql(f'SELECT 1 FROM {table} LIMIT 0')
        components['database'] = {'status': 'ready', 'message': '数据库正常'}
    except Exception:
        logger.warning('database readiness unavailable', exc_info=True)
        components['database'] = {'status': 'unavailable', 'message': '数据库不可用或迁移未完成'}
    try:
        sufficient = shutil.disk_usage(DATA_DIR).free >= int(os.environ.get('WFS_MIN_FREE_MB', '100'))*1024*1024
        components['storage'] = {'status': 'ready' if sufficient else 'unavailable',
                                 'message': '数据空间正常' if sufficient else '数据空间不足'}
    except OSError:
        components['storage'] = {'status': 'unavailable', 'message': '数据目录不可用'}
    if WFS_ENABLE_SCHEDULER:
        from app.extensions import scheduler
        state = service_state()
        try:
            age = (business_now()-dt.datetime.fromisoformat(state['heartbeat'])).total_seconds()
            healthy = bool(scheduler.running and state['ready'] and 0 <= age <= 120)
        except (ValueError, KeyError, TypeError):
            healthy = False
        components['scheduler'] = {'status': 'ready' if healthy else 'unavailable',
                                   'message': '调度器正常' if healthy else '调度器未就绪或心跳过期'}
    elif WFS_SCHEDULER_CONTROL_URL:
        import requests
        try:
            response = requests.get(WFS_SCHEDULER_CONTROL_URL.rstrip('/')+'/api/user/ready', timeout=5)
            healthy = response.status_code == 200 and response.json().get('data', {}).get('ready') is True
        except (requests.RequestException, ValueError):
            healthy = False
        components['scheduler'] = {'status': 'ready' if healthy else 'unavailable',
                                   'message': '调度器正常' if healthy else '调度服务不可用'}
    else:
        components['scheduler'] = {'status': 'disabled', 'message': '未启用调度器'}
    return {'ready': all(item['status'] != 'unavailable' for item in components.values()),
            'database': components['database']['status'] == 'ready',
            'scheduler': components['scheduler']['status'] == 'ready',
            'timezone': 'Asia/Shanghai', 'components': components}
