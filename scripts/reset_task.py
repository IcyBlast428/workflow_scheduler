"""Offline reset of one task so its unchanged GitLab directory is new again.

Default is a read-only preview. --apply requires stopped systemd services and
holds the platform instance lock. Removed files are quarantined, never erased.
Run with the deployed project's Python; no dependency installation is needed.
"""
import argparse
from contextlib import ExitStack
import datetime as dt
import json
import os
from pathlib import Path
import re
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
PID_TABLES = (
    'wfs_task_releases', 'wfs_task_config', 'wfs_job_stats',
    'wfs_run_history', 'wfs_run_history_archive', 'wfs_schedule_history',
    'wfs_executions', 'wfs_config_versions', 'wfs_config_application',
    'wfs_history_rollup', 'wfs_run_summary', 'wfs_run_totals',
    'wfs_notifications', 'wfs_alert_incidents',
    'wfs_state_admission_receipts', 'wfs_state_admission_work_requests',
    'wfs_state_admission_ddl_history', 'wfs_state_journal_journal',
    'wfs_package_tasks',
)


def rows(db, table, where='', params=()):
    return db.execute_query_sql('SELECT * FROM ' + table + (' WHERE ' + where if where else ''),
                                params=params, return_json=True)


def checked_path(root, relative):
    """Only exact descendants; refuse symlinks in the path being moved."""
    root = Path(root).resolve()
    relative = Path(relative)
    if relative.is_absolute() or not relative.parts or '..' in relative.parts:
        raise ValueError('Unsafe task file path: ' + str(relative))
    path = root
    for part in relative.parts:
        path = path / part
        if path.is_symlink() or getattr(path, 'is_junction', lambda: False)():
            raise ValueError('Task path contains a link: ' + str(path))
    if not path.resolve().is_relative_to(root) or path.resolve() == root:
        raise ValueError('Task path leaves storage root')
    return path


def plan(db, pid, repository_path, data_root, package_root):
    from app.bootstrap import gitlab_tasks, gitlab_updates
    from app.bootstrap.task_packages import IDENTIFIER
    if not IDENTIFIER.fullmatch(pid):
        raise ValueError('Invalid task ID')
    repository_path = gitlab_updates._path(repository_path)
    parts = repository_path.split('/')
    if len(parts) < 3:
        raise ValueError('Supply the full GitLab task directory, including its root')
    group, folder = parts[-2:]
    configuration = rows(db, 'wfs_state_gitlab_configuration', 'id=1')
    if not configuration:
        raise ValueError('Configure GitLab before resetting this task')
    config = json.loads(gitlab_updates._cipher().decrypt(configuration[0]['payload'].encode()))
    config['revision'] = configuration[0]['revision']
    key = gitlab_tasks.project_key(config)
    if not any(gitlab_updates._under(repository_path, root) for root in config['task_roots']):
        raise ValueError('Task directory is outside the configured GitLab scan roots')
    ids = {pid, gitlab_tasks.generated_task_id(config, repository_path)}
    records = [json.loads(r['payload']) for r in rows(db, 'wfs_package_tasks')]
    for record in records:
        same_folder = (record.get('group_name'), record.get('folder_name')) == (group, folder)
        if record['pid'] in ids or same_folder:
            source = record.get('git_source') or {}
            if not same_folder or source and (source.get('project_key') != key or source.get('path') != repository_path):
                raise ValueError('Task identity belongs to a different directory or repository: ' + record['pid'])
            ids.add(record['pid'])
    for binding in config.get('tasks', []):
        if binding['path'] == repository_path:
            ids.add(binding['pid'])
        elif binding['pid'] in ids:
            raise ValueError('Task is bound to a different directory: ' + binding['path'])
    if any(not IDENTIFIER.fullmatch(identifier) for identifier in ids):
        raise ValueError('Stored task ID is invalid')
    # A binding must not introduce an unrelated registry identity.
    for record in records:
        if record['pid'] in ids:
            source = record.get('git_source') or {}
            if (record.get('group_name'), record.get('folder_name')) != (group, folder) or source and (source.get('project_key') != key or source.get('path') != repository_path):
                raise ValueError('Directory binding points to another task')
    ids = sorted(ids)
    where = 'pid IN (' + ','.join('?' for _ in ids) + ')'
    records_by_table = {table: rows(db, table, where, tuple(ids)) for table in PID_TABLES}
    for table in ('wfs_task_config', 'wfs_job_stats'):
        for record in records_by_table[table]:
            if record.get('group_name') and (record['group_name'], record.get('folder_name')) != (group, folder):
                raise ValueError('Stored task configuration belongs to another directory')
    runs = {r['run_id'] for table in ('wfs_executions', 'wfs_state_journal_journal') for r in records_by_table[table]}
    runs.update(r['id'] for table in ('wfs_run_history', 'wfs_run_history_archive') for r in records_by_table[table])
    execution_root = Path(data_root) / 'executions'
    spools = []
    for path in execution_root.glob('*.json'):
        checked_path(execution_root, path.name)
        record = json.loads(path.read_text(encoding='utf-8'))
        if record.get('pid') in ids:
            if path.name != str(record.get('run_id')) + '.json':
                raise ValueError('Unexpected recovery spool name')
            runs.add(record['run_id'])
            spools.append(record)
    notification_ids = [r['id'] for r in records_by_table['wfs_notifications']]
    setting_keys = {prefix + identifier for prefix in ('task:', 'connections:', 'tags:', 'ddl:', 'issue:config-') for identifier in ids}
    setting_keys.update('notification:' + i for i in notification_ids)
    setting_keys.update('issue:run-' + i for i in runs)
    settings = rows(db, 'wfs_state_admission_settings')
    removed_settings = [r for r in settings if r['key'] in setting_keys]
    access_changes = []
    for setting in settings:
        if setting['key'].startswith('access:'):
            value = json.loads(setting['payload'])
            remaining = [i for i in value.get('tasks', []) if i not in ids]
            if remaining != value.get('tasks', []):
                access_changes.append((setting, {**value, 'tasks': remaining, 'revision': value.get('revision', 0) + 1}))
    records_by_table['wfs_state_admission_settings'] = removed_settings + [r for r, _ in access_changes]
    audit_targets = ids + sorted(runs)
    audit = []
    for target in audit_targets:
        audit.extend(rows(db, 'wfs_audit', 'target=?', (target,)))
    records_by_table['wfs_audit'] = audit
    files = set()
    for identifier in ids:
        for root, relative in ((package_root, identifier), (data_root, 'task-data/' + identifier), (data_root, 'trial-data/' + identifier)):
            path = checked_path(root, relative)
            if path.exists():
                files.add(path)
    logs = [r.get('log_path') for r in records_by_table['wfs_state_journal_journal'] + spools]
    for record in records_by_table['wfs_executions']:
        logs.append(json.loads(record['payload']).get('log_path'))
    for run in runs:
        if not re.fullmatch('[a-f0-9]{32}', run):
            raise ValueError('Invalid stored execution ID: ' + run)
        logs.extend((run + '.json', run + '.log'))
        # Include orphaned logs with an exact run ID, never substring matching.
        logs.extend(str(p.relative_to(execution_root)) for p in (execution_root / 'logs').glob('*/' + run[:2] + '/' + run + '.log'))
    for relative in filter(None, logs):
        if Path(relative).name not in {run + suffix for run in runs for suffix in ('.json', '.log')}:
            raise ValueError('Execution log does not match this task run: ' + str(relative))
        path = checked_path(execution_root, relative)
        if path.exists():
            if not path.is_file():
                raise ValueError('Expected an execution log file: ' + str(path))
            files.add(path)
    changed_config = {**config, 'revision': config['revision'] + 1,
                      'tasks': [b for b in config.get('tasks', []) if b['pid'] not in ids and b['path'] != repository_path]}
    return dict(ids=ids, path=repository_path, tables=records_by_table, files=sorted(files),
                config=changed_config, config_before=configuration, access_changes=access_changes,
                remove_settings=removed_settings,
                snapshot_before=rows(db, 'wfs_state_gitlab_snapshot'), lease_before=rows(db, 'wfs_state_gitlab_scan_lease'))


def apply(db, value, backup_root):
    """Caller holds service/deployment locks; transaction rollback restores moved files."""
    from app.bootstrap.gitlab_updates import _cipher
    backup = Path(backup_root) / (dt.datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:8])
    backup.mkdir(parents=True, mode=0o700)
    backup.chmod(0o700)
    moves = [(path, backup / 'files' / str(index)) for index, path in enumerate(value['files'])]
    archive = dict(ids=value['ids'], path=value['path'], tables=value['tables'],
                   gitlab_configuration=value['config_before'], gitlab_snapshot=value['snapshot_before'],
                   gitlab_scan_lease=value['lease_before'], files=[{'from': str(a), 'to': str(b)} for a, b in moves])
    with (backup / 'records.json').open('x', encoding='utf-8') as output:
        json.dump(archive, output, ensure_ascii=False, indent=2, default=str)
        output.flush()
        os.fsync(output.fileno())
    (backup / 'records.json').chmod(0o600)
    moved = []
    db.begin_transaction()
    try:
        where = 'pid IN (' + ','.join('?' for _ in value['ids']) + ')'
        for table in PID_TABLES:
            db.execute_sql('DELETE FROM ' + table + ' WHERE ' + where, params=tuple(value['ids']))
        for record in value['tables']['wfs_audit']:
            db.execute_sql('DELETE FROM wfs_audit WHERE id=?', params=(record['id'],))
        for record in value['remove_settings']:
            db.execute_sql('DELETE FROM wfs_state_admission_settings WHERE key=?', params=(record['key'],))
        for record, updated in value['access_changes']:
            db.execute_sql('UPDATE wfs_state_admission_settings SET payload=? WHERE key=?', params=(json.dumps(updated), record['key']))
        encrypted = _cipher().encrypt(json.dumps(value['config']).encode()).decode()
        db.execute_sql('UPDATE wfs_state_gitlab_configuration SET revision=?,payload=? WHERE id=1',
                       params=(value['config']['revision'], encrypted))
        db.execute_sql('DELETE FROM wfs_state_gitlab_snapshot')
        db.execute_sql('DELETE FROM wfs_state_gitlab_scan_lease')
        for source, destination in moves:
            destination.parent.mkdir(parents=True, exist_ok=True)
            # Rename only; failure (including cross-device moves) rolls back the DB.
            source.rename(destination)
            moved.append((source, destination))
        db.set_commit()
    except BaseException:
        db.set_rollback()
        for source, destination in reversed(moved):
            destination.rename(source)
        raise
    (backup / 'COMPLETED').write_text('Task reset committed. This backup is outside live task storage.\n')
    return backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, default=ROOT)
    parser.add_argument('--pid', required=True)
    parser.add_argument('--path', required=True, help='Full GitLab task directory')
    parser.add_argument('--expect-db-id', required=True, help='Expected database_schema, e.g. immpdb_wfs')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    project = args.project.resolve()
    sys.path.insert(0, str(project))
    from scripts.deploy import production_environment, deployment_lock, assert_stopped
    from scripts.serve import instance_lock
    # Environment must load before app imports.
    environment = production_environment(project)
    os.environ.clear()
    os.environ.update(environment)
    os.umask(0o077)
    from app.bootstrap.database import GaussDB
    from app.bootstrap.task_packages import storage_root
    with ExitStack() as stack:
        stack.enter_context(deployment_lock(project))
        if args.apply:
            assert_stopped()
            stack.enter_context(instance_lock(project / 'data'))
        with GaussDB() as db:
            database, schema = db.execute_query_sql('SELECT current_database(),current_schema()')[0]
            if args.expect_db_id != database + '_' + schema:
                raise ValueError('Database/schema does not match --expect-db-id; no data changed')
            value = plan(db, args.pid, args.path, project / 'data', storage_root())
            print(json.dumps({'database': database, 'schema': schema, 'task_ids': value['ids'], 'path': value['path'],
                              'rows': {table: len(records) for table, records in value['tables'].items()},
                              'files': [str(p) for p in value['files']], 'apply': args.apply}, ensure_ascii=False, indent=2))
            if args.apply:
                import psutil
                for process in psutil.process_iter(['pid']):
                    try:
                        if process.pid != os.getpid() and process.environ().get('WFS_TASK_ID') in value['ids']:
                            raise RuntimeError('Task process still running: ' + str(process.pid))
                    except psutil.NoSuchProcess:
                        pass
                backup = apply(db, value, checked_path(project / 'data', 'task-reset-backups'))
                print('清理完成。隔离备份：', backup)
                print('启动平台后重新检查 GitLab；原目录将按新任务处理，再配置调度。')
            else:
                print('仅预览，未修改数据。停止平台后加 --apply 执行。')


if __name__ == '__main__':
    main()
