"""Same-host read model: Web workers read status without occupying control threads."""
import datetime as dt
import json
import logging
from pathlib import Path
import os
import threading
import time

from app.bootstrap.global_vars import DATA_DIR
from app.bootstrap.timebase import business_now

logger = logging.getLogger(__name__)
_publish_lock = threading.Lock()
_start_lock = threading.Lock()
_started = False
MAX_AGE_SECONDS = 15


def snapshot_path():
    return Path(DATA_DIR) / 'runtime-state.json'


def read_snapshot():
    try:
        value = json.loads(snapshot_path().read_text(encoding='utf-8'))
        age = (business_now() - dt.datetime.fromisoformat(value['published_at'])).total_seconds()
        if value.get('schema') == 1 and 0 <= age <= MAX_AGE_SECONDS and value['service']['ready']:
            return value
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def publish():
    from app.settings import WFS_ENABLE_SCHEDULER
    if not WFS_ENABLE_SCHEDULER or not _publish_lock.acquire(blocking=False):
        return
    try:
        from app.api.task.views import _event_snapshot
        from app.bootstrap.operations import service_state
        from app.bootstrap.system_metrics import recent_task_starts
        value = _event_snapshot()
        starts = recent_task_starts(business_now()-dt.timedelta(minutes=2), include_active=True)
        active = [item for item in starts if not item.get('end_time')]
        completed = [item for item in starts if item.get('end_time')][-1000:]
        value.update(schema=1, published_at=business_now().isoformat(' '), service=service_state(),
                     task_starts=active+completed)
        destination = snapshot_path()
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix('.tmp')
        temporary.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
        os.replace(temporary, destination)
    finally:
        _publish_lock.release()


def start():
    global _started
    from app.settings import WFS_ENABLE_SCHEDULER
    if not WFS_ENABLE_SCHEDULER:
        return
    with _start_lock:
        if _started:
            return
        _started = True
    def loop():
        while True:
            try:
                publish()
            except Exception:
                logger.exception('runtime read model update unavailable')
            time.sleep(2)
    threading.Thread(target=loop, name='wfs-runtime-snapshot', daemon=True).start()
