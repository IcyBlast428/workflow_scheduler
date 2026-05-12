# 项目本体数据库连接工具

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

class GaussDB:
    def __init__(self, db_id='sysimemedb_wfs'):
        self.current_env = get_runtime_env()
        # 根据_分割数据库名和模式名, 默认immpdb数据库、immp模式
        db_name, schema = db_id.split('_')
        self.__conf_dic = self.__get_db_config(db_name, schema)
        self.__host = self.__conf_dic["host"]
        self.__port = self.__conf_dic["port"]
        self.__db = self.__conf_dic["db"]
        self.__schema = self.__conf_dic["schema"]
        self.__user = self.__conf_dic["user"]
        self.__password = self.__conf_dic["password"]
        self.__driver = 'DWS'

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
        self.conn = pyodbc.connect(conn_str, autocommit = True)
        self.cursor = self.conn.cursor()
        self.cursor.execute(f"set schema '{self.__schema}';")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()
    
    # 当自动提交为False时需要手动commit
    def set_commit(self):
        self.conn.commit()
    
    # 回退事务
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

    # default return type is set within list like [(),()]
    def execute_query_sql(self, sql, return_json = False, params=None):
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
            conf_dic = Nacos().get_nacos_configs(data_id=f"gauss.{db_name}.{schema}.json", group="gauss")
            if not conf_dic:
                raise RuntimeError("missing GaussDB nacos config: gauss.{}.{}.json".format(db_name, schema))
        else:
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
