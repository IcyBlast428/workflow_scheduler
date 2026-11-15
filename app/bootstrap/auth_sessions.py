"""Shared login sessions so expiry and logout apply to every Web worker."""

import datetime
import hashlib
import secrets

from app.bootstrap.database import GaussDB


def _digest(session_id):
    return hashlib.sha256(session_id.encode('utf-8')).hexdigest()


def create_session(lifetime):
    # 会话标识使用随机令牌，数据库仅存其摘要；共享表让退出在多个 Web 进程间一致生效。
    session_id = secrets.token_urlsafe(32)
    # 会话时间统一使用无时区 UTC 写入 SQL；它不采用任务的业务时区。
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    with GaussDB() as db:
        db.execute_sql('DELETE FROM wfs_auth_sessions WHERE expires_at <= ?', params=(now,))
        db.execute_sql(
            'INSERT INTO wfs_auth_sessions (sid_hash, created_at, expires_at) VALUES (?, ?, ?)',
            params=(_digest(session_id), now, now + lifetime),
        )
    return session_id


def is_session_active(session_id):
    """每次请求检查共享撤销/过期状态；仅有有效签名的 Cookie 还不足以放行。"""
    if not isinstance(session_id, str) or not session_id:
        return False
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    with GaussDB() as db:
        rows = db.execute_query_sql(
            'SELECT 1 FROM wfs_auth_sessions WHERE sid_hash = ? AND expires_at > ?',
            params=(_digest(session_id), now),
        )
    return bool(rows)


def revoke_session(session_id):
    if isinstance(session_id, str) and session_id:
        with GaussDB() as db:
            db.execute_sql('DELETE FROM wfs_auth_sessions WHERE sid_hash = ?', params=(_digest(session_id),))
