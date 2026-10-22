# -*- coding: utf-8 -*-

from app.common.db.config import load_database_config
from app.common.db.mysql import MySQLAdapter
from app.common.db.oracle import OracleAdapter
from app.common.db.clickhouse import ClickHouseAdapter
from app.common.db.adapters import PostgreSQLAdapter, SQLServerAdapter, SQLiteAdapter
from app.common.db.catalog import DATABASES, normalize
from contextlib import contextmanager


ADAPTERS = {
    'mysql': MySQLAdapter,
    'oracle': OracleAdapter,
    'clickhouse': ClickHouseAdapter,
    'postgresql': PostgreSQLAdapter,
    'mssql': SQLServerAdapter,
    'sqlite': SQLiteAdapter,
}


def adapter_for(config):
    import importlib.util
    dialect = normalize(config.get('dialect'))
    if dialect not in ADAPTERS:
        raise ValueError('暂不支持数据库类型：'+dialect)
    spec = DATABASES[dialect]
    if importlib.util.find_spec(spec['module']) is None:
        raise RuntimeError('此环境尚未安装数据库驱动：'+spec['package'])
    return ADAPTERS[dialect]({**config, 'dialect': dialect})


class NewDB:
    """One ID-based business database API; a handle belongs to one thread.

    Engines/pools are shared within this process. close()/context exit returns
    the handle's connection, and rolls back unfinished work, without destroying
    its pool. Use transaction() for atomic multi-statement writes.
    """

    def __init__(self, db_id):
        if db_id == 'platform':
            raise ValueError('platform 是平台内部连接，请为任务配置独立的业务连接标识。')
        self.db_id = db_id
        self.config = load_database_config(db_id)
        self.dialect = normalize(self.config.get('dialect'))
        self.config['dialect'] = self.dialect
        self._adapter = self._create_adapter()

    def _create_adapter(self):
        return adapter_for(self.config)

    def __enter__(self):
        self.get_engine()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()

    def get_engine(self, *args, **kwargs):
        return self._adapter.get_engine(*args, **kwargs)

    async def get_async_engine(self):
        raise NotImplementedError('异步数据库连接请在任务独立环境中按需实现')

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
        with self._adapter.transaction():
            yield self

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

    async def async_insert_many(self, sql, args):
        raise NotImplementedError('异步数据库连接请在任务独立环境中按需实现')

    async def async_execute_single_sql(self, sql):
        raise NotImplementedError('异步数据库连接请在任务独立环境中按需实现')

    async def async_query_sql(self, sql):
        raise NotImplementedError('异步数据库连接请在任务独立环境中按需实现')

    async def async_query_sql_return_json(self, sql):
        raise NotImplementedError('异步数据库连接请在任务独立环境中按需实现')

    async def async_close(self):
        self.close()


def get_db(db_id):
    """根据 db_id 返回非高斯业务数据库连接。"""
    return NewDB(db_id)
