"""One-time offline migration; normal discovery never reads a source directory."""
import argparse
from contextlib import contextmanager
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def legacy_specs(source):
    from app.bootstrap.task_loader import iter_task_directories, load_task_spec, _record_maps
    records = _record_maps()
    result = [load_task_spec(group, folder, path, records)
              for group, folder, path in iter_task_directories(source)]
    ids = [spec['pid'] for spec in result]
    if len(set(ids)) != len(ids):
        raise ValueError('旧任务存在重复编号，请先修正后再迁移。')
    return result


def stage_legacy_task(spec, actor='offline-migration'):
    """Copy a baseline into durable package storage, preserving its original PID."""
    from app.bootstrap import task_packages as packages
    from app.bootstrap.timebase import business_now
    record = packages.registry().get(spec['pid'])
    if record and (record.get('active_version') or record.get('deleted_at')):
        return None
    if spec.get('error') or spec.get('main_file_error'):
        raise ValueError(spec.get('error') or spec.get('main_file_error'))
    if record and not (record.get('legacy') or record.get('origin') == 'migration'):
        raise ValueError('编号已属于上传任务，拒绝覆盖：' + spec['pid'])
    fresh = record is None
    record = record or {
        'pid': spec['pid'], 'group_name': spec['group_name'], 'folder_name': spec['folder_name'],
        'task_name': spec.get('task_name') or spec['folder_name'], 'active_version': None,
        'deleted_at': None, 'created_at': str(business_now()), 'created_by': actor, 'revision': 0,
    }
    record.update(origin='migration', legacy=False)
    data = packages._create(record, source=spec['task_dir'], entry=spec['main_file'],
                            actor=actor, note='一次性迁移旧任务；编号、配置与历史保留')
    record = packages._write_task(record, expected=0 if fresh else record['revision'])
    data['base_revision'] = record['revision']
    return packages._write_release(data)


def migrate_task(spec, actor='offline-migration', timeout=600):
    from app.bootstrap import task_packages as packages
    data = stage_legacy_task(spec, actor)
    if data is None:
        return None
    packages.prepare(data['pid'], data['version'], data['main_file'])
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        prepared = packages.release(data['pid'], data['version'])
        if prepared['status'] != 'preparing':
            if prepared['status'] != 'ready':
                raise ValueError(prepared.get('message') or '依赖检查失败')
            return packages.publish(data['pid'], data['version'], packages.task(data['pid'])['revision'], actor)
        time.sleep(.05)
    raise TimeoutError('迁移等待依赖检查超时；检查发布页后可重试。')


def verify_catalog():
    """Block a platform upgrade from silently dropping previously known tasks."""
    from app.bootstrap import task_packages as packages
    from app.bootstrap.database import GaussDB
    managed = packages.registry()
    with GaussDB() as db:
        existing = db.execute_query_sql('SELECT pid FROM wfs_job_stats')
    missing = [pid for (pid,) in existing if not (
        managed.get(pid, {}).get('active_version') or managed.get(pid, {}).get('deleted_at'))]
    if missing:
        raise ValueError('以下任务尚未迁移为发布版本，停止升级：' + ', '.join(sorted(missing)))
    return len(existing)


@contextmanager
def offline_lease():
    from app.bootstrap.global_vars import DATA_DIR
    directory = Path(DATA_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / '.scheduler.lock').open('a') as lease:
        if os.name != 'nt':
            import fcntl
            try:
                fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError('请先停止 Web 和 Scheduler，再执行迁移。')
        yield


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'app/jobs')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true', help='After backup and service shutdown, prepare and publish baselines')
    mode.add_argument('--verify-only', action='store_true', help='Block deployment if previously known tasks lack published versions')
    args = parser.parse_args(argv)
    if not args.verify_only and not args.source.is_dir():
        parser.error('旧任务目录不存在。')
    # Set before importing settings. Migration itself must never execute business jobs.
    os.environ['WFS_ENABLE_SCHEDULER'] = 'false'
    from app import create_app
    create_app()
    from app.extensions import scheduler
    if scheduler.running:
        raise RuntimeError('迁移进程不能运行 Scheduler。')
    if args.verify_only:
        print('已核对发布目录中的 {} 个已有任务。'.format(verify_catalog()))
        return
    specs = legacy_specs(args.source)
    from app.bootstrap.task_packages import registry
    managed = registry()
    skipped = {pid for pid, record in managed.items() if record.get('active_version') or record.get('deleted_at')}
    errors = [spec for spec in specs if spec['pid'] not in skipped and (spec.get('error') or spec.get('main_file_error'))]
    for spec in specs:
        print('{} | {} | {}'.format(spec['pid'], spec.get('main_file'),
              '已管理或已删除，跳过' if spec['pid'] in skipped else spec.get('error') or spec.get('main_file_error') or '可迁移'))
    if errors:
        raise ValueError('请修正全部入口和任务配置后重试。')
    if not args.apply:
        print('仅检查，未复制或发布任务。备份并停服后追加 --apply 执行。')
        return
    with offline_lease():
        for spec in specs:
            result = migrate_task(spec)
            print('{}: {}'.format(spec['pid'], '已迁移' if result else '已有版本或已删除，跳过'))


if __name__ == '__main__':
    main()
