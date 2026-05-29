# -*- coding: utf-8 -*-

import re

from sqlalchemy import create_engine, text

from app.common.db.base import DatabaseAdapter


class SQLAlchemyAdapter(DatabaseAdapter):
    """基于 SQLAlchemy 的同步数据库适配器。

    适合任务里访问 MySQL/Oracle 等业务库。默认只在 `get_engine()` 时创建连接，
    用完后显式 `close()`，由 SQLAlchemy 的 QueuePool 处理连接池复用。
    """

    dialect = ''

    def __init__(self, config):
        self.config = config
        self._engine = None
        self._connection = None

    def build_url(self):
        raise NotImplementedError

    def get_engine(self, poolSize=3, poolRecycle=600, poolTimeout=30):
        if self._engine is None:
            self._engine = create_engine(
                self.build_url(),
                echo=False,
                pool_size=poolSize,
                pool_recycle=poolRecycle,
                pool_timeout=poolTimeout,
            )
        if self._connection is None or self._connection.closed:
            self._connection = self._engine.connect()
        return self._engine

    def get_connection(self):
        self.get_engine()
        return self._connection

    def close(self):
        if self._connection is not None:
            self._connection.close()
            self._connection = None
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None

    def execute_single_sql(self, sql, params=None):
        connection = self.get_connection()
        statement, next_params, use_driver_sql = self._prepare_statement(sql, params)
        if use_driver_sql:
            connection.exec_driver_sql(statement, next_params)
        else:
            connection.execute(text(statement), next_params or {})
        connection.commit()

    def execute_query_sql(self, sql, return_json=False, params=None):
        connection = self.get_connection()
        statement, next_params, use_driver_sql = self._prepare_statement(sql, params)
        if use_driver_sql:
            result_proxy = connection.exec_driver_sql(statement, next_params)
        else:
            result_proxy = connection.execute(text(statement), next_params or {})
        result = result_proxy.all()
        if return_json:
            return [dict(zip(result_proxy.keys(), row)) for row in result]
        return result

    def insert_many(self, sql, args):
        connection = self.get_connection()
        statement, next_args, use_driver_sql = self._prepare_statement(sql, args)
        if use_driver_sql:
            result = connection.exec_driver_sql(statement, next_args)
        else:
            result = connection.execute(text(statement), next_args or {})
        connection.commit()
        return result.rowcount

    def insert_with_rollback(self, sql, args):
        self.get_engine()
        statement, next_args, use_driver_sql = self._prepare_statement(sql, args)
        with self._engine.begin() as connection:
            if use_driver_sql:
                result = connection.exec_driver_sql(statement, next_args)
            else:
                result = connection.execute(text(statement), next_args or {})
            return result.rowcount

    def _prepare_statement(self, sql, params):
        """兼容旧任务中常见的 PyMySQL `%(name)s` 参数写法。"""
        if params is None:
            return sql, {}, False
        if self._is_named_params(params):
            return self._convert_pyformat(sql), params, False
        return sql, params, True

    @staticmethod
    def _is_named_params(params):
        if isinstance(params, dict):
            return True
        if isinstance(params, (list, tuple)) and params:
            return isinstance(params[0], dict)
        return False

    @staticmethod
    def _convert_pyformat(sql):
        return re.sub(r'%\(([^)]+)\)s', r':\1', sql)
