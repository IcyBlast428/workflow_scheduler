# -*- coding: utf-8 -*-
"""项目本体数据库连接工具。

平台仅使用 GaussDB/DWS；本机协议验收显式使用 PostgreSQL。
平台连接由有界的进程内连接池管理，每个句柄独占连接和事务；
归还时回滚未完成事务，线程及进程之间不共享正在使用的连接。
"""

import os
import base64
import re
import time
from functools import wraps

try:
    import pyodbc
    # QueuePool owns reuse and capacity. A second driver-manager pool would
    # keep retired/overflow physical connections alive after close().
    pyodbc.pooling = False
except ImportError:
    pyodbc = None
from configobj import ConfigObj
from app.common.nacos import Nacos
from app.bootstrap.helpers import get_runtime_env
from app.bootstrap.global_vars import CONFIG_DIR


DEFAULT_DB_ID = os.environ.get("WFS_DB_ID", "wfsscheduler_wfs")
GAUSS_DRIVER = os.environ.get("WFS_DB_DRIVER", "DWS")


def measured(name):
    def decorate(function):
        @wraps(function)
        def wrapper(*args, **kwargs):
            started = time.perf_counter()
            try:
                return function(*args, **kwargs)
            finally:
                from app.bootstrap.runtime_metrics import record

                record(name, 1000 * (time.perf_counter() - started))

        return wrapper

    return decorate


def qmark_parameters(sql):
    # The native PostgreSQL test driver uses %-style parameters. Escape percents and replace
    # question-mark parameters only outside literals/comments/identifiers.
    result, quote, index = [], "", 0
    while index < len(sql):
        char = sql[index]
        if quote:
            result.append("%%" if char == "%" else char)
            if char == "\\" and index + 1 < len(sql):
                index += 1
                result.append("%%" if sql[index] == "%" else sql[index])
            elif char == quote:
                if index + 1 < len(sql) and sql[index + 1] == quote:
                    result.append(quote)
                    index += 1
                else:
                    quote = ""
        elif char in "'\"`":
            quote = char
            result.append(char)
        elif sql.startswith("--", index) or char == "#" or sql.startswith("/*", index):
            end = (
                sql.find("*/", index + 2) + 2 if char == "/" else sql.find("\n", index)
            )
            if end < index + 1:
                end = len(sql)
            result.append(sql[index:end].replace("%", "%%"))
            index = end - 1
        else:
            result.append("%s" if char == "?" else "%%" if char == "%" else char)
        index += 1
    return "".join(result)


def _split_db_id(db_id):
    """db_id 约定为 <database>_<schema>，例如 sysimemedb_wfs。"""
    parts = str(db_id or DEFAULT_DB_ID).split("_", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(
            "GaussDB db_id must use <database>_<schema>, for example sysimemedb_wfs"
        )
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", parts[1]):
        raise ValueError("invalid database schema identifier")
    return parts[0], parts[1]


class GaussDB:
    """Single platform database; each handle owns its connection and transaction."""

    @property
    def dialect(self):
        return (
            "PostgreSQL"
            if os.environ.get("WFS_POSTGRES_TEST") == "true"
            else "GaussDB/DWS"
        )

    def __init__(self, db_id=None, *, config_override=None, pooled=True):
        from app.bootstrap import platform_config
        options = dict(config_override) if config_override is not None else platform_config.active()
        self._in_transaction = False
        self._lease = None
        self.conn = self.cursor = None
        self.current_env = get_runtime_env()
        native_test = os.environ.get("WFS_POSTGRES_TEST") == "true" and config_override is None
        direct = options['source'] == 'direct' and not native_test and db_id is None
        if direct:
            schema = options['schema']
            config = dict(host=options['host'], port=options['port'], db=options['database'],
                          schema=schema, user=options['user'], password=options['password'])
        else:
            identifier = db_id or (os.environ.get('WFS_DB_ID', DEFAULT_DB_ID) if native_test else options['db_id'])
            db_name, schema = _split_db_id(identifier)
            config = self.__get_db_config(db_name, schema)
            if config.get('password') and self.current_env == 'production':
                config['password'] = base64.b64decode(config['password']).decode('utf-8')
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', schema):
            raise ValueError('invalid database schema identifier')
        driver = os.environ.get('WFS_DB_DRIVER', GAUSS_DRIVER) if native_test else options['driver']
        timeout = int(options['query_timeout'])
        if not 1 <= timeout <= 3600:
            raise ValueError('WFS_DB_QUERY_TIMEOUT_SECONDS must be between 1 and 3600')
        if driver == 'psycopg' and native_test:
            if config['db'] != 'wfstest' or config['host'] not in ('127.0.0.1', 'localhost'):
                raise RuntimeError('Native PostgreSQL acceptance is restricted to localhost/wfstest')
            from app.bootstrap.postgres_native import Connection
            def connect():
                return Connection(host=config['host'], port=int(config['port']), dbname=config['db'],
                                  user=config['user'], password=config['password'])
        else:
            if pyodbc is None:
                raise RuntimeError('pyodbc is not installed; configure the DWS ODBC driver')
            def odbc_value(value):
                text = str(value)
                return '{' + text.replace('}', '}}') + '}' if any(c in text for c in ';{}') else text
            server_key = 'SERVERNAME' if driver.startswith('PostgreSQL') else 'SERVER'
            connection_string = ';'.join(f'{key}={odbc_value(value)}' for key, value in (
                ('DRIVER', driver), (server_key, config['host']), ('DATABASE', config['db']),
                ('UID', config['user']), ('PWD', config['password']), ('PORT', config['port'])))
            def connect():
                return pyodbc.connect(connection_string, autocommit=True, timeout=options['connect_timeout'])
        if pooled:
            from app.bootstrap.platform_pool import acquire
            self._lease = acquire([driver, config], connect, options)
            self.conn = self._lease.raw
        else:
            self.conn = connect()
        try:
            self.conn.autocommit = True
            self.cursor = self.conn.cursor()
            self.cursor.execute(f'SET statement_timeout = {timeout * 1000}')
            self.cursor.execute(f'SET search_path TO {schema}')
        except BaseException:
            self.close(broken=True)
            raise

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def set_commit(self):
        self.conn.commit()
        self._in_transaction = False
        self.conn.autocommit = True

    def set_rollback(self):
        self.conn.rollback()
        self._in_transaction = False
        self.conn.autocommit = True

    def begin_transaction(self):
        if self._in_transaction:
            raise RuntimeError("Nested platform transactions are not supported")
        self.conn.autocommit = False
        self._in_transaction = True

    def get_connection(self):
        return self.conn

    def get_cursor(self):
        return self.cursor

    def close(self, broken=False):
        connection, cursor, lease = self.conn, self.cursor, self._lease
        self.conn = self.cursor = self._lease = None
        if connection is None:
            return
        try:
            if cursor is not None:
                cursor.close()
            if not connection.autocommit:
                connection.rollback()
                connection.autocommit = True
        except Exception:
            broken = True
        finally:
            if lease is not None:
                lease.close(broken=broken)
            else:
                connection.close()

    @measured("database:query")
    def execute_query_sql(self, sql, return_json=False, params=None):
        """执行查询；return_json=True 时转换为前端/API 更容易消费的字典列表。"""
        if params is None:
            self.cursor.execute(sql)
        else:
            self.cursor.execute(sql, params)
        result = self.cursor.fetchall()
        if return_json:
            columns = [i[0] for i in self.cursor.description]
            return [dict(zip(columns, row)) for row in result]
        return result

    @measured("database:write")
    def execute_sql(self, sql, params=None):
        try:
            if params is None:
                self.cursor.execute(sql)
            else:
                self.cursor.execute(sql, params)
        except Exception as e:
            raise Exception(e)

    @measured("database:config")
    def __get_db_config(self, db_name, schema):
        conf_dic = dict()
        if self.current_env == "production":
            # 生产环境从 Nacos 读取，命名保持 gauss.<database>.<schema>.json。
            conf_dic = Nacos().get_nacos_configs(
                data_id=f"gauss.{db_name}.{schema}.json", group="gauss"
            )
            if not conf_dic:
                raise RuntimeError(
                    "missing GaussDB nacos config: gauss.{}.{}.json".format(
                        db_name, schema
                    )
                )
        else:
            # 本机验收配置使用明确的数据库与 schema 名称。
            ini = os.environ.get("WFS_DB_CONFIG_FILE") or os.path.join(
                CONFIG_DIR, "database", "development.ini"
            )
            config_base = ConfigObj(ini, encoding="utf-8")
            config = config_base.get("gauss_{}_{}".format(db_name, schema))
            if not config:
                raise RuntimeError(
                    "missing configured GaussDB section in {}".format(ini)
                )
            conf_dic["user"] = config.get("user") or ""
            password = config.get("password")
            conf_dic["password"] = os.environ.get("WFS_DB_PASSWORD") or (password or "")
            conf_dic["host"] = config.get("host") or ""
            conf_dic["port"] = config.get("port") or ""
            conf_dic["db"] = db_name
            conf_dic["schema"] = schema

        return conf_dic


WfsDB = GaussDB
