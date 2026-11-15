"""Bounded thread offload for synchronous business database drivers.

A worker owns its database handle for the complete operation. The permit is
released by the concurrent future, not by the awaiting coroutine: cancelling
an await cannot free capacity while a database statement is still running.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import os
import threading

# These are per task process, independent of each connection's own pool limit.
# Reject excess submissions rather than retaining an unbounded SQL work queue.
MAX_WORKERS = 4
MAX_OUTSTANDING = 16
_state = None
_lock = threading.Lock()


class AsyncDatabaseBusyError(RuntimeError):
    """The process has reached its asynchronous database work budget."""


def _after_fork():
    global _state, _lock
    # Parent threads/locks cannot be reused by the forked process. Do not call
    # shutdown on their executor: only the parent's process owns those workers.
    _state = None
    _lock = threading.Lock()


if hasattr(os, 'register_at_fork'):
    os.register_at_fork(after_in_child=_after_fork)


def _worker_state():
    global _state
    with _lock:
        if _state is None or _state[0] != os.getpid():
            _state = (
                os.getpid(),
                ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix='wfs-db'),
                threading.BoundedSemaphore(MAX_OUTSTANDING),
            )
        return _state


async def run_in_database_worker(work):
    """Run one independent SQL operation without blocking the event loop.

    Cancellation may prevent a queued operation from starting. Once running,
    work continues, including commit/rollback and connection cleanup. It must
    never be retried automatically merely because the caller stopped waiting.
    """
    _, executor, permits = _worker_state()
    if not permits.acquire(blocking=False):
        raise AsyncDatabaseBusyError(
            '异步数据库任务已达进程上限（最多 4 个运行、16 个待完成），'
            '请减少并发并等待已有操作完成。'
        )
    try:
        future = executor.submit(work)
    except BaseException:
        permits.release()
        raise
    future.add_done_callback(lambda _future: permits.release())
    return await asyncio.wrap_future(future)
