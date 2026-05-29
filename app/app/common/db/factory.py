# -*- coding: utf-8 -*-

from app.common.db.config import load_database_config
from app.common.db.mysql import MySQLAdapter
from app.common.db.oracle import OracleAdapter
from app.common.db.clickhouse import ClickHouseAdapter


ADAPTERS = {
    'mysql': MySQLAdapter,
    'oracle': OracleAdapter,
    'clickhouse': ClickHouseAdapter,
}


class NewDB:
    """非高斯业务数据库连接入口。

    这个类保留历史 API，供任务和 common 公共函数继续使用。平台本体高斯库请使用
    `app.bootstrap.database.GaussDB`，不要通过 NewDB 混用。
    """

    def __init__(self, db_id):
        self.db_id = db_id
        self.config = load_database_config(db_id)
        self.dialect = self.config.get('dialect')
        self._adapter = self._create_adapter()

    def _create_adapter(self):
        adapter_cls = ADAPTERS.get(self.dialect)
        if not adapter_cls:
            raise NotImplementedError('暂不支持数据库类型：{}'.format(self.dialect))
        return adapter_cls(self.config)

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
