"""Shared connection lifetime, transactions and portable parameter binding."""
from contextlib import contextmanager
import os
import threading
import time
import re
from sqlalchemy.exc import TimeoutError as PoolTimeout
from app.common.db.engine_pool import record_wait
from sqlalchemy import text
from app.common.db.base import DatabaseAdapter
from app.common.db.engine_pool import engine_for


def _rewrite(sql, replacement, dialect=None, protect_literals=False):
    """Replace bind tokens outside dialect-specific literals and identifiers."""
    result, index, quote = [], 0, ''
    def literal(value):
        # SQLAlchemy text() recognizes colon binds even inside SQL literals.
        # Its compiler removes this escape before sending SQL to the driver.
        return re.sub(r'(?<!\\):(?=\w)', r'\\:', value) if protect_literals else value
    backslash = False
    while index < len(sql):
        char = sql[index]
        if quote:
            if protect_literals and char == ':' and (index == 0 or sql[index - 1] != '\\'):
                result.append('\\')
            result.append(char)
            if backslash and char == '\\' and index + 1 < len(sql):
                index += 1
                result.append(sql[index])
            elif char == quote:
                if index + 1 < len(sql) and sql[index + 1] == quote:
                    result.append(quote)
                    index += 1
                else:
                    quote = ''
        elif dialect in {'postgresql', 'gaussdb'} and char == '$' and (tag := re.match(r'\$(?:[A-Za-z_]\w*)?\$', sql[index:])):
            marker = tag.group()
            end = sql.find(marker, index + len(marker))
            end = len(sql) if end < 0 else end + len(marker)
            result.append(literal(sql[index:end]))
            index = end - 1
        elif char in "'\"`":
            quote = char
            backslash = dialect in {None, 'mysql', 'clickhouse'} or (
                dialect in {'postgresql', 'gaussdb'} and char == "'" and index > 0 and sql[index - 1] in 'eE')
            result.append(char)
        elif sql.startswith('--', index) or sql.startswith('/*', index) or (char == '#' and dialect in {None, 'mysql', 'clickhouse'}):
            end = sql.find('*/', index + 2) + 2 if char == '/' else sql.find('\n', index)
            if end <= index:
                end = len(sql)
            result.append(literal(sql[index:end]))
            index = end - 1
        else:
            token, consumed = replacement(sql, index)
            result.append(token)
            index += consumed - 1
        index += 1
    return ''.join(result)


class SQLAlchemyAdapter(DatabaseAdapter):
    """引擎可在进程内复用，但本适配器句柄只能归创建它的线程/进程使用。"""
    def __init__(self, config):
        self.config = config
        self._engine = self._connection = self._transaction = None
        self._owner = (os.getpid(), threading.get_ident())

    def _check_owner(self):
        if self._owner != (os.getpid(), threading.get_ident()):
            raise RuntimeError('NewDB 实例不能跨线程或进程使用，请在当前线程/进程重新创建实例。')

    def build_url(self):
        raise NotImplementedError

    def connection_options(self):
        return {}

    def get_engine(self, poolSize=None, poolRecycle=None, poolTimeout=None):
        self._check_owner()
        if self._engine is None:
            options = {key: value for key, value in dict(poolSize=poolSize, poolRecycle=poolRecycle, poolTimeout=poolTimeout).items() if value is not None}
            self._engine = engine_for(self.config, self.build_url(), self.connection_options(), options)
        return self._engine

    def get_connection(self):
        self._check_owner()
        if self._connection is None or self._connection.closed:
            self._connection = self._checkout()
        return self._connection

    def _checkout(self):
        engine = self.get_engine()
        started = time.monotonic()
        timed_out = False
        try:
            return engine.connect()
        except PoolTimeout:
            timed_out = True
            raise
        finally:
            record_wait(engine, (time.monotonic() - started) * 1000, timed_out)

    def close(self):
        self._check_owner()
        try:
            if self._connection is not None:
                self._connection.close()
        finally:
            self._connection = self._engine = self._transaction = None

    @contextmanager
    def _borrow(self):
        # 显式连接/事务持有同一连接；无显式持有时每次操作短暂借用并归还。
        self._check_owner()
        if self._connection is not None and not self._connection.closed:
            try:
                yield self._connection
            except BaseException:
                if self._transaction is None:
                    self._connection.rollback()
                raise
        else:
            with self._checkout() as connection:
                yield connection

    @contextmanager
    def transaction(self):
        """只关闭本上下文新借的连接；调用者先前显式取得的连接继续由其管理。"""
        if self.config['dialect'] == 'clickhouse':
            raise NotImplementedError('ClickHouse 不支持本接口的事务回滚。')
        had_connection = self._connection is not None and not self._connection.closed
        connection = self.get_connection()
        if self._transaction is not None or connection.in_transaction():
            raise RuntimeError('当前连接已有事务，请先提交或回滚；不支持嵌套事务。')
        try:
            with connection.begin() as transaction:
                self._transaction = transaction
                yield self
        finally:
            self._transaction = None
            if not had_connection:
                self.close()

    def _execute(self, connection, sql, params):
        statement, values, native = self._prepare_statement(sql, params, self.config.get('dialect'))
        return connection.exec_driver_sql(statement, values) if native else connection.execute(text(statement), values)

    def execute_single_sql(self, sql, params=None):
        with self._borrow() as connection:
            result = self._execute(connection, sql, params)
            count = result.rowcount
            result.close()
            # 默认写入逐次提交；transaction() 内由最外层上下文统一提交或回滚。
            if self._transaction is None:
                connection.commit()
            return count

    def execute_query_sql(self, sql, return_json=False, params=None):
        with self._borrow() as connection:
            with self._execute(connection, sql, params) as result:
                return [dict(row) for row in result.mappings()] if return_json else [tuple(row) for row in result]

    def insert_many(self, sql, args):
        rows = list(args)
        return self.execute_single_sql(sql, rows) if rows else 0

    def insert_with_rollback(self, sql, args):
        if self._transaction is not None:
            return self.insert_many(sql, args)
        with self.transaction():
            return self.insert_many(sql, args)

    @staticmethod
    def _prepare_statement(sql, params, dialect=None):
        """只统一绑定参数，不翻译 SQL 方言；值始终由驱动绑定，不拼接进 SQL。"""
        if params is None:
            return sql, None, True
        many = isinstance(params, list) and bool(params) and isinstance(params[0], (dict, tuple, list))
        first = params[0] if many else params
        if isinstance(first, dict):
            import re
            def named(source, index):
                match = re.match(r'%\(([A-Za-z_]\w*)\)s', source[index:])
                return (':'+match[1], len(match[0])) if match else (source[index], 1)
            return _rewrite(sql, named, dialect, protect_literals=True), params, False
        if not isinstance(first, (list, tuple)):
            raise ValueError('参数请使用字典或元组；批量写入请传入字典/元组列表。')
        positions = []
        def positional(source, index):
            if source[index] == '?':
                name = 'wfs_bind_' + str(len(positions)); positions.append(name)
                return ':'+name, 1
            return source[index], 1
        statement = _rewrite(sql, positional, dialect)
        if positions:
            rows = params if many else [params]
            if any(len(row) != len(positions) for row in rows):
                raise ValueError('SQL 参数数量与占位符不一致。')
            values = [dict(zip(positions, row)) for row in rows]
            statement = _rewrite(statement, lambda source, index: (source[index], 1), dialect, protect_literals=True)
            return statement, values if many else values[0], False
        return sql, params, True
