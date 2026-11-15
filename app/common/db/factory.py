# -*- coding: utf-8 -*-
"""任务代码的统一业务数据库入口；类型扩展必须同时注册目录与受审适配器。"""

from app.common.db.config import load_database_config
from app.common.db.mysql import MySQLAdapter
from app.common.db.clickhouse import ClickHouseAdapter
from app.common.db.adapters import PostgreSQLAdapter, GaussDBAdapter
from app.common.db.catalog import DATABASES, normalize
from contextlib import contextmanager
from copy import deepcopy
import inspect

from app.common.db.async_worker import run_in_database_worker


ADAPTERS = {
    'mysql': MySQLAdapter,
    'clickhouse': ClickHouseAdapter,
    'postgresql': PostgreSQLAdapter,
    'gaussdb': GaussDBAdapter,
}


def adapter_for(config):
    """仅实例化固定注册表中的四类适配器，不从页面配置导入任意驱动代码。"""
    import importlib.util
    dialect = normalize(config.get('dialect'))
    if dialect not in ADAPTERS:
        raise ValueError('暂不支持数据库类型：'+dialect)
    spec = DATABASES[dialect]
    if importlib.util.find_spec(spec['module']) is None:
        raise RuntimeError('此环境尚未安装数据库驱动：'+spec['package'])
    if spec['module'] == 'pyodbc':
        # QueuePool owns the connection budget. Disable driver-manager pooling
        # before the first ODBC connection in this independent task process.
        import pyodbc
        pyodbc.pooling = False
    return ADAPTERS[dialect]({**config, 'dialect': dialect})


class NewDB:
    """One ID-based business database API; a handle belongs to one thread.

    Engines/pools are shared within this process. close()/context exit returns
    the handle's connection, and rolls back unfinished work, without destroying
    its pool. Use transaction() for atomic multi-statement writes.
    """

    def __init__(self, db_id):
        # 授权解析在建引擎之前完成；任务仅使用连接标识，不接受直传账号密码。
        if db_id == 'platform':
            raise ValueError('platform 是平台内部连接，请为任务配置独立的业务连接标识。')
        self.db_id = db_id
        self.config = load_database_config(db_id)
        self.dialect = normalize(self.config.get('dialect'))
        self.config['dialect'] = self.dialect
        self._adapter = self._create_adapter()
        self._transaction_depth = 0

    @classmethod
    def _from_snapshot(cls, db_id, config):
        """Build only inside a worker, from a previously authorized snapshot."""
        handle = object.__new__(cls)
        handle.db_id = db_id
        handle.config = config
        handle.dialect = config['dialect']
        handle._adapter = handle._create_adapter()
        handle._transaction_depth = 0
        return handle

    def _create_adapter(self):
        return adapter_for(self.config)

    def __enter__(self):
        # with NewDB(...) 管理句柄生命周期，不隐式开启跨多条 SQL 的事务。
        self.get_engine()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()

    def get_engine(self, *args, **kwargs):
        return self._adapter.get_engine(*args, **kwargs)

    async def get_async_engine(self):
        raise NotImplementedError('NewDB 使用独占线程执行同步驱动，不提供原生 AsyncEngine；请使用 async_query/async_execute/async_transaction。')

    def get_ck_engine(self):
        if not hasattr(self._adapter, 'get_ck_engine'):
            raise NotImplementedError('当前数据库类型不支持 get_ck_engine')
        return self._adapter.get_ck_engine()

    def ck_insert_many(self, sql, data):
        if not hasattr(self._adapter, 'ck_insert_many'):
            raise NotImplementedError('当前数据库类型不支持 ck_insert_many')
        return self._adapter.ck_insert_many(sql, data)

    def get_connection(self):
        return self._adapter.get_connection()

    def close(self):
        self._adapter.close()

    def close_connection(self):
        self.close()

    @contextmanager
    def transaction(self):
        """显式将多次写入归为同一事务；支持能力由具体适配器决定。"""
        with self._adapter.transaction():
            self._transaction_depth += 1
            try:
                yield self
            finally:
                self._transaction_depth -= 1

    @staticmethod
    def dispose_pool(db_id=None):
        from app.common.db.engine_pool import dispose
        dispose(db_id)

    def query(self, sql, params=None, *, as_dict=False):
        return self.execute_query_sql(sql, return_json=as_dict, params=params)

    def execute(self, sql, params=None):
        return self.execute_single_sql(sql, params=params)

    def executemany(self, sql, rows):
        return self.insert_many(sql, rows)

    def execute_single_sql(self, sql, params=None):
        return self._adapter.execute_single_sql(sql, params=params)

    def execute_query_sql(self, sql, return_json=False, params=None):
        return self._adapter.execute_query_sql(sql, return_json=return_json, params=params)

    def insert_many(self, sql, args):
        return self._adapter.insert_many(sql, args)

    def insert_with_rollback(self, sql, args):
        return self._adapter.insert_with_rollback(sql, args)

    async def __aenter__(self):
        # Opening a synchronous engine here would unnecessarily touch the event
        # loop thread. Each awaited operation creates its own worker connection.
        self._adapter._check_owner()
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        await self.async_close()

    def _assert_async_allowed(self):
        self._adapter._check_owner()
        connection = self._adapter._connection
        if self._transaction_depth or (
            connection is not None and not connection.closed and connection.in_transaction()
        ):
            raise RuntimeError(
                '同步事务中不能调用异步数据库方法；请用 async_transaction(work) '
                '并在 work 中通过传入的句柄同步执行整段事务。'
            )

    async def _async_work(self, work, *, transactional=False):
        self._assert_async_allowed()
        if not callable(work) or inspect.iscoroutinefunction(work):
            raise TypeError('数据库回调必须是同步函数，不能是 async 函数。')
        config, db_id = deepcopy(self.config), self.db_id

        def run():
            # Do not reload mutable settings or copy the owner-thread adapter.
            # A transaction, its statements and cleanup always share one worker.
            handle = self._from_snapshot(db_id, config)
            try:
                def invoke():
                    result = work(handle)
                    if inspect.isawaitable(result):
                        if inspect.iscoroutine(result):
                            result.close()
                        raise TypeError('数据库回调不能返回 awaitable，请在同步回调中使用 query/execute。')
                    return result
                if transactional:
                    with handle.transaction():
                        return invoke()
                return invoke()
            finally:
                handle.close()

        return await run_in_database_worker(run)

    async def async_query(self, sql, params=None, *, as_dict=False):
        """Fetch materialized rows using an independent worker-owned handle."""
        values = deepcopy(params)
        return await self._async_work(lambda db: db.query(sql, values, as_dict=as_dict))

    async def async_execute(self, sql, params=None):
        """Execute and commit one statement. Cancellation does not undo SQL."""
        values = deepcopy(params)
        return await self._async_work(lambda db: db.execute(sql, values))

    async def async_executemany(self, sql, rows):
        values = deepcopy(list(rows))
        return await self._async_work(lambda db: db.executemany(sql, values))

    async def async_transaction(self, work):
        """Run a synchronous callback atomically in one worker-owned transaction.

        The callback receives its own NewDB and uses synchronous query/execute.
        A normal return commits; an exception rolls back. ClickHouse rejects
        this operation. Cancelling the await does not cancel a running callback.
        """
        return await self._async_work(work, transactional=True)

    async def async_insert_many(self, sql, args):
        return await self.async_executemany(sql, args)

    async def async_execute_single_sql(self, sql, params=None):
        return await self.async_execute(sql, params)

    async def async_query_sql(self, sql, params=None, *, as_dict=False):
        return await self.async_query(sql, params, as_dict=as_dict)

    async def async_query_sql_return_json(self, sql, params=None):
        return await self.async_query(sql, params, as_dict=True)

    async def async_close(self):
        # Worker handles close in their own finally blocks. This closes only the
        # caller's synchronous handle; it does not cancel outstanding SQL work.
        self.close()


def get_db(db_id):
    """根据已授权连接标识返回任意受支持类型的业务数据库。"""
    return NewDB(db_id)
