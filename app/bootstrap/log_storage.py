"""Bounded, explicitly confirmed cleanup of synchronized terminal run logs."""
import datetime as dt
import os
import stat
import time
from pathlib import Path
from itsdangerous import URLSafeTimedSerializer, BadData
from flask import current_app
from app.bootstrap import journal, operations
from app.bootstrap.timebase import business_now


def _signer():
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='execution-log-cleanup-v1')


def _file(record):
    root = Path(operations._directory).resolve()
    relative = Path(record['log_path'])
    if relative.is_absolute() or '..' in relative.parts or relative.suffix != '.log' or relative.stem != record['run_id']:
        raise ValueError('日志路径不安全，未列入清理。')
    path = root / relative
    for item in (path, *path.parents):
        if item == root:
            break
        if item.is_symlink():
            raise ValueError('日志路径包含链接，未列入清理。')
    path.resolve().relative_to(root)
    try:
        info = path.stat()
    except FileNotFoundError:
        return path, [0, 0, 0]
    if not stat.S_ISREG(info.st_mode):
        raise ValueError('日志不是普通文件。')
    return path, [info.st_size, info.st_mtime_ns, info.st_ino]


def _eligible(record, cutoff):
    return (record['status'] in operations.TERMINAL and record.get('db_synced')
            and record.get('history_saved') and not record.get('log_cleaned_at')
            and bool(record.get('end_time')) and record['end_time'] < cutoff)


def preview(days=90):
    if type(days) is not int or not 7 <= days <= 3650:
        raise ValueError('日志保留天数须为 7 至 3650 天。')
    cutoff = (business_now() - dt.timedelta(days=days)).isoformat(' ')
    # Exclude already cleaned logs in the index, retaining execution metadata.
    with journal.connection(operations._directory) as db:
        rows = db.execute("SELECT run_id FROM journal WHERE created_at<? AND pending=0 AND status NOT IN ('running','queued') AND log_path<>'' ORDER BY created_at,run_id LIMIT 5001", (cutoff,)).fetchall()
    candidates, skipped, inspected, used = [], 0, 0, 0
    deadline = time.monotonic() + 3
    for (run_id,) in rows[:5000]:
        if len(candidates) >= 500 or time.monotonic() >= deadline:
            break
        inspected += 1
        record = operations.read_run(run_id)
        if not _eligible(record, cutoff):
            skipped += 1
            continue
        try:
            _, identity = _file(record)
        except (ValueError, OSError):
            skipped += 1
            continue
        used += identity[0]
        candidates.append({'id':run_id, 'file':identity})
    payload = {'days':days, 'cutoff':cutoff, 'candidates':candidates}
    confirm = f'清理 {len(candidates)} 条执行日志'
    return dict(days=days, cutoff=cutoff, count=len(candidates), bytes=used,
                missing=sum(item['file'][0] == 0 for item in candidates), inspected=inspected, skipped=skipped,
                partial=inspected < len(rows), confirm=confirm, token=_signer().dumps(payload),
                automatic_retention_days=max(60, int(os.environ.get('WFS_LOG_RETENTION_DAYS', '90'))))


def execute(form):
    if not isinstance(form, dict) or not isinstance(form.get('token'), str):
        raise ValueError('请先生成日志清理计划。')
    try:
        plan = _signer().loads(form.get('token', ''), max_age=600)
    except BadData:
        raise ValueError('清理计划无效或已超过十分钟，请重新预览。') from None
    if form.get('confirm') != f"清理 {len(plan['candidates'])} 条执行日志":
        raise ValueError('请输入完整清理确认文字。')
    removed, released, skipped = 0, 0, 0
    for item in plan['candidates']:
        run_id = item['id']
        with operations._locks[int(run_id[:2], 16)]:
            try:
                record = operations.read_run(run_id)
            except ValueError:
                skipped += 1
                continue
            if not _eligible(record, plan['cutoff']):
                skipped += 1
                continue
            try:
                path, identity = _file(record)
                if identity != item['file']:
                    skipped += 1
                    continue
                # No active log or history row is deleted. If unlink fails,
                # the file remains a candidate on retry.
                path.unlink(missing_ok=True)
                operations.update_run(run_id, log_cleaned_at=operations.now())
            except (ValueError, OSError):
                skipped += 1
                continue
            removed += 1
            released += identity[0]
    return {'count':removed, 'bytes':released, 'skipped':skipped}
