# -*- coding: utf-8 -*-
"""项目本体数据库连接工具。

平台本体固定使用高斯数据库，任务侧如需访问数据库也优先复用这个实现。
当前采用“短生命周期连接 + ODBC 驱动层复用”的模式：每次业务操作打开连接，
操作结束关闭连接，避免在 Flask/Gunicorn 多线程环境里共享全局 connection。
"""

import os
import base64
try:
    import pyodbc
except ImportError:
    pyodbc = None
from configobj import ConfigObj
from app.common.pyDes import do_decrypt as _p
from app.common.nacos import Nacos
from app.bootstrap.helpers import get_runtime_env
from app.bootstrap.global_vars import CONFIG_DIR


DEFAULT_DB_ID = 'sysimemedb_wfs'
GAUSS_DRIVER = 'DWS'


def _split_db_id(db_id):
    """db_id 约定为 <database>_<schema>，例如 sysimemedb_wfs。"""
    parts = str(db_id or DEFAULT_DB_ID).split('_', 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError('GaussDB db_id must use <database>_<schema>, for example sysimemedb_wfs')
    return parts[0], parts[1]


class GaussDB:
    """WFS 平台本体使用的高斯数据库封装。"""

    def __init__(self, db_id=DEFAULT_DB_ID):
        self.current_env = get_runtime_env()
        db_name, schema = _split_db_id(db_id)
        self.__conf_dic = self.__get_db_config(db_name, schema)
        self.__host = self.__conf_dic["host"]
        self.__port = self.__conf_dic["port"]
        self.__db = self.__conf_dic["db"]
        self.__schema = self.__conf_dic["schema"]
        self.__user = self.__conf_dic["user"]
        self.__password = self.__conf_dic["password"]
        self.__driver = GAUSS_DRIVER

        if self.__password and self.current_env == 'production':
            self.__password = base64.b64decode(self.__password).decode("utf-8")

        if pyodbc is None:
            raise RuntimeError("pyodbc is not installed; please run pip install -r requirements.txt and configure the DWS ODBC driver")

        conn_str = (
            f'DRIVER={self.__driver};'
            f'SERVER={self.__host};'
            f'DATABASE={self.__db};'
            f'UID={self.__user};'
            f'PWD={self.__password};'
            f'PORT={self.__port}'
        )
        # 高斯 DWS ODBC 驱动自带连接复用能力，Python 层不维护跨线程长连接。
        self.conn = pyodbc.connect(conn_str, autocommit = True)
        self.cursor = self.conn.cursor()
        # 表名统一写成不带 schema 的形式，连接建立后先切换到平台 schema。
        self.cursor.execute(f"set schema '{self.__schema}';")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()
    
    # 当前默认 autocommit=True；预留给需要显式事务的场景。
    def set_commit(self):
        self.conn.commit()
    
    # 当前默认 autocommit=True；预留给需要显式事务的场景。
    def set_rollback(self):
        self.conn.rollback()

    def get_connection(self):
        return self.conn
    
    def get_cursor(self):
        return self.cursor
    
    def close(self):
        try:
            self.cursor.close()
        except Exception:
            pass
        try:
            self.conn.close()
        except Exception:
            pass

    def execute_query_sql(self, sql, return_json = False, params=None):
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
    
    def execute_sql(self, sql, params = None):
        try:
            if params is None:
                self.cursor.execute(sql)
            else:
                self.cursor.execute(sql, params)
        except Exception as e:
            raise Exception(e)

    def __get_db_config(self, db_name, schema):
        conf_dic = dict()
        if self.current_env == 'production':
            # 生产环境从 Nacos 读取，命名保持 gauss.<database>.<schema>.json。
            conf_dic = Nacos().get_nacos_configs(data_id=f"gauss.{db_name}.{schema}.json", group="gauss")
            if not conf_dic:
                raise RuntimeError("missing GaussDB nacos config: gauss.{}.{}.json".format(db_name, schema))
        else:
            # 本地环境优先使用历史配置 [gauss_immpdb]，也支持更明确的 [gauss_<database>_<schema>]。
            ini = os.path.join(CONFIG_DIR, 'database', 'development' + '.ini')
            config_base = ConfigObj(ini, encoding='utf-8')
            config = config_base.get("gauss_immpdb") or config_base.get("gauss_{}_{}".format(db_name, schema))
            if not config:
                raise RuntimeError("missing database config section [gauss_immpdb] in {}".format(ini))
            conf_dic["user"] = config.get("user") or ""
            conf_dic["password"] = _p(config.get("password")) or ""
            conf_dic["host"] = config.get("host") or ""
            conf_dic["port"] = config.get("port") or ""
            conf_dic["db"] = db_name
            conf_dic["schema"] = schema

        return conf_dic


# 语义化别名：平台本体库建议在新代码里写 WfsDB，旧代码继续使用 GaussDB。
WfsDB = GaussDB
