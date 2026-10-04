"""Bounded history queries and verified, transactional archival."""
from app.bootstrap.timebase import business_now

import base64
import datetime as dt
import hashlib
import json

from app.bootstrap.database import GaussDB
from app.bootstrap.execution_state import is_failure

RUN_COLUMNS = 'id,pid,taskname,dirname,group_name,folder_name,state,tasklog,start_time,end_time'
SUMMARY = """id,pid,taskname,dirname,group_name,folder_name,
CASE WHEN state=0 THEN '成功' WHEN state=-15 THEN '已停止' WHEN state=-1 THEN '重启中断' WHEN state=-9 THEN '超时/终止' WHEN state=-10001 THEN '并发跳过' WHEN state=-10002 THEN '错过调度' ELSE '失败' END,
end_time,start_time,extract(epoch from (end_time - start_time))::bigint"""


def date_range(values):
    today = business_now().date()
    if not values:
        return [dt.datetime.combine(today-dt.timedelta(days=6), dt.time()),
                dt.datetime.combine(today, dt.time(23,59,59,999999))]
    if len(values) != 2:
        raise ValueError('请同时填写开始和结束日期。')
    try:
        start, end = [dt.datetime.fromisoformat(value) for value in values]
        if len(values[1]) == 10:
            end = dt.datetime.combine(end.date(), dt.time(23,59,59,999999))
    except (TypeError, ValueError):
        raise ValueError('日期格式无效。')
    if start.tzinfo or end.tzinfo or end < start or end-start > dt.timedelta(days=93):
        raise ValueError('每次查询的日期范围须在 93 天以内，结束日期不能早于开始日期。')
    return [start, end]


def page(clauses, params, size, scope, cursor, binding):
    tables = {'online': ['wfs_run_history'], 'archive': ['wfs_run_history_archive'],
              'all': ['wfs_run_history', 'wfs_run_history_archive']}.get(scope)
    if not tables:
        raise ValueError('日志查询范围无效。')
    signature = hashlib.sha256(json.dumps(binding, ensure_ascii=False, default=str).encode()).hexdigest()
    if cursor:
        try:
            if len(cursor) > 2048:
                raise ValueError()
            decoded = json.loads(base64.urlsafe_b64decode(cursor.encode()))
            if decoded['binding'] != signature or not isinstance(decoded['id'], str) or len(decoded['id']) > 50:
                raise ValueError()
            timestamp = dt.datetime.fromisoformat(decoded['time'])
            if timestamp.tzinfo:
                raise ValueError()
        except (ValueError, KeyError, TypeError, UnicodeError):
            raise ValueError('分页位置已失效，请重新搜索。')
        # The direct time bound lets PostgreSQL/GaussDB seek into the index;
        # the OR alone can scan every newer row before applying the cursor.
        clauses = [*clauses, 'end_time <= ?', '(end_time < ? OR (end_time = ? AND id < ?))']
        params = [*params, timestamp, timestamp, timestamp, decoded['id']]
    where = ' AND '.join(clauses) or '1=1'
    rows = []
    with GaussDB() as db:
        for table in tables:
            rows.extend(db.execute_query_sql(f'SELECT {SUMMARY} FROM {table} WHERE {where} ORDER BY end_time DESC,id DESC LIMIT ?', params=tuple([*params, size+1])))
    # Each branch already fetched at most size+1 rows; never sort the full archive.
    rows.sort(key=lambda row: (str(row[7]), row[0]), reverse=True)
    has_more = len(rows) > size
    rows = rows[:size]
    next_cursor = ''
    if rows and has_more:
        next_cursor = base64.urlsafe_b64encode(json.dumps({'binding':signature, 'time':str(rows[-1][7]), 'id':rows[-1][0]}).encode()).decode()
    return rows, has_more, next_cursor


def archive_batch(cutoff, size=200):
    """Copy and compare every row before deleting it, in one transaction."""
    if not 1 <= size <= 1000:
        raise ValueError('batch size must be between 1 and 1000')
    if cutoff.tzinfo or cutoff > business_now()-dt.timedelta(days=90):
        raise ValueError('retain at least 90 days online')
    with GaussDB() as db:
        db.begin_transaction()
        try:
            locking = '' if db._local_sqlite else ' FOR UPDATE'
            rows = db.execute_query_sql(f'SELECT {RUN_COLUMNS} FROM wfs_run_history WHERE end_time < ? ORDER BY end_time,id LIMIT ?{locking}', params=(cutoff,size))
            for row in rows:
                key = (row[0], row[9])
                existing = db.execute_query_sql(f'SELECT {RUN_COLUMNS} FROM wfs_run_history_archive WHERE id=? AND end_time=?', params=key)
                if not existing:
                    db.execute_sql(f'INSERT INTO wfs_run_history_archive({RUN_COLUMNS}) VALUES(?,?,?,?,?,?,?,?,?,?)', params=tuple(row))
                    existing = db.execute_query_sql(f'SELECT {RUN_COLUMNS} FROM wfs_run_history_archive WHERE id=? AND end_time=?', params=key)
                if not existing or tuple(existing[0]) != tuple(row):
                    raise RuntimeError('archive verification failed; source history retained')
                if is_failure(row[6]):
                    if not db.execute_query_sql('SELECT 1 FROM wfs_history_rollup WHERE pid=?', params=(row[1],)):
                        db.execute_sql('INSERT INTO wfs_history_rollup(pid,archived_failures) VALUES(?,0)', params=(row[1],))
                    db.execute_sql('UPDATE wfs_history_rollup SET archived_failures=archived_failures+1 WHERE pid=?', params=(row[1],))
                db.execute_sql('DELETE FROM wfs_run_history WHERE id=? AND end_time=?', params=key)
            db.set_commit()
            return len(rows)
        except Exception:
            db.set_rollback()
            raise
