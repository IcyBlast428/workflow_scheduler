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
        self.conn = pyodbc.connect(conn_str)
        self.cursor = self.conn.cursor()
        self.cursor.execute(f'set schema {self.__schema};')
        self.conn.commit()
    
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
    
    def close_connection(self):
        self.conn.close()
    
    def execute_single_sql(self, sql, params=None):
        try:
            if params is None:
                self.cursor.execute(sql)
            else:
                self.cursor.execute(sql, params)
        except Exception as e:
            raise Exception(e)

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
            self.cursor.execute(sql, params)
        except Exception as e:
            raise Exception(e)

    def execute_query_sql_fetchall(self, sql, params, return_json=False):
        self.cursor.execute(sql, params)
        result = self.cursor.fetchall()
        if return_json:
            columns = [i[0] for i in self.cursor.description]
            return [dict(zip(columns, row)) for row in result]
        return result
    
    #TODO 区分带参数插入单行和多行
    # dict type args is no longer suportted with jaydebeapi
    # insert_sql = "insert into your_table (column1, column2, column3) values (?, ?, ?)"
    # data_dict = {
    #     "column1" : "value1",
    #     "column2" : "value2",
    #     "column3" : "value3",
    # }
    # data_tuple = (data_dict["column1"], data_dict["column2"], data_dict["column3"])
    # tmp_obj.insert_many(insert_sql, data_tuple)
    # data_dict_list = [
    #     {"column_1": 1, "column_2": "congyu1", "column_3": "2024-12-1 12:23:34"},
    #     {"column_1": 2, "column_2": "congyu2", "column_3": "2024-12-2 12:23:34"},
    #     {"column_1": 3, "column_2": "congyu3", "column_3": "2024-12-3 12:23:34"},
    #     {"column_1": 4, "column_2": "congyu4", "column_3": "2024-12-4 12:23:34"},
    #     {"column_1": 5, "column_2": "congyu5", "column_3": "2024-12-5 12:23:34"}
    # ]
    # data_tuple = [(item["column_1"], item["column_2"], item["column_3"]) for item in data_dict_list]
    # tmp_obj.insert_many(insert_sql, data_tuple)
    def insert_many(self, insert_sql, data_tuple):
        self.cursor.executemany(insert_sql, data_tuple)

    def __get_db_config(self, db_name, schema):
        conf_dic = dict()
        if self.current_env == 'production':
            conf_dic = Nacos().get_nacos_configs(data_id=f"gauss.{db_name}.{schema}.json", group="gauss")
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


class NewDB(object):
    """
    使用步骤如下：
    1、实例化类加载配置项：db = NewDB('mysql_xnrl)
    2、创建连接引擎：db.get_engine()
    或者使用异步方式 await db.get_async_engine()
    3、根据需要调用其他方法
    """

    def __init__(self, db_id):
        self.__conf_dic = self.__get_db_config(db_id)
        self.__db_dialect = db_id.split('_')[0]
        self.__db_user = self.__conf_dic["user"]
        self.__db_password = self.__conf_dic["password"]
        self.__db_host = self.__conf_dic["host"]
        self.__db_port = self.__conf_dic["port"]
        self.__db_database = self.__conf_dic["db"]
        self.__database_url = None
        self.__db_engine = None
        self.__db_connection = None
        self.__pool = None
        self.__ck_conn = None

    def get_engine(self, poolSize=3, poolRecycle=600, poolTimeout=30):
        if self.__db_dialect.lower() == "mysql":
            self.__database_url = f"mysql+pymysql://{self.__db_user}:{self.__db_password}@{self.__db_host}:{self.__db_port}/{self.__db_database}?charset=utf8"
        elif self.__db_dialect.lower() == "oracle":
            self.__database_url = f"oracle+cx_oracle://{self.__db_user}:{self.__db_password}@{self.__db_host}:{self.__db_port}/?service_name={self.__db_database}"
        elif self.__db_dialect.lower() == "clickhouse":
            self.__database_url = f"clickhouse://{self.__db_user}:{self.__db_password}@{self.__db_host}:8123/{self.__db_database}"
        else:
            raise Exception(f"does not support {self.__db_dialect}")
        # set db engine and connection
        self.__db_engine = create_engine(self.__database_url, echo=False, pool_size=poolSize, pool_recycle=poolRecycle,
                                         pool_timeout=poolTimeout)
        self.__db_connection = self.__db_engine.connect()

    async def get_async_engine(self):
        aiomysql = _import_optional('aiomysql')
        self.__pool = await aiomysql.create_pool(
            host=self.__db_host,
            port=int(self.__db_port),
            user=self.__db_user,
            password=self.__db_password,
            db=self.__db_database
        )

    def get_ck_engine(self):
        clickhouse_driver = _import_optional('clickhouse_driver')
        self.__ck_conn = clickhouse_driver.Client(
            settings={'use_client_time_zone': True},
            host=self.__db_host,
            port=9000,
            user=self.__db_user,
            password=self.__db_password,
            database=self.__db_database
        )

    def ck_insert_many(self, sql, data):
        # 批量插入数据到clickhouse
        result = self.__ck_conn.execute(sql, data)
        return result

    def get_connection(self):
        return self.__db_connection

    def execute_single_sql(self, sql, params=None):
        try:
            if params is None:
                self.__db_connection.execute(text(sql))
            else:
                self.__db_connection.execute(text(sql), params)
        except Exception as e:
            raise Exception(e)

    # default return type is set within list like [(),()]
    def execute_query_sql(self, sql, return_json=False, params=None):
        if params is None:
            res = self.__db_connection.execute(text(sql))
        else:
            res = self.__db_connection.execute(text(sql), params)
        result = res.all()
        if return_json:
            return [dict(zip(res.keys(), row)) for row in result]
        return result

    def insert_many(self, sql, args):
        result = self.__db_connection.execute(sql, args)
        # result = self.getConnection().execute(sql, args)
        return result.rowcount

    def insert_with_rollback(self, sql, args):
        insert_rows = 0
        with self.__db_connection as conn:
            with conn.begin() as cursor:
                try:
                    res = conn.execute(sql, args)
                    insert_rows = res.rowcount
                except Exception as e:
                    cursor.rollback()
                    print(f"insert many err, transaction rolled back:{e}")
        return insert_rows

    async def async_insert_many(self, sql, args):
        async with self.__pool.acquire() as conn:
            async with conn.cursor() as cur:
                # await conn.begin()
                try:
                    await cur.executemany(sql, args)
                    await conn.commit()
                    return cur.rowcount
                except Exception as e:
                    print('async insert err:', e)
                    if 'container_memory_usage_bytes_rate' in sql and ('inf' in str(e) or 'nan' in str(e)):
                        app_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                        log_path = os.path.join(app_path, 'jobs', 'promDataCollection', 'prom_pod_kpi_collect_per_5min',
                                                'log.txt')
                        if not os.path.exists(log_path):
                            with open(log_path, 'w', encoding='utf-8') as f:
                                f.write(sql + '\n' + str(args))
                    # await conn.rollback()   #  不回滚防止数据丢失
                    return 0

    async def async_execute_single_sql(self, sql):
        async with self.__pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql)
                await conn.commit()

    async def async_query_sql(self, sql):
        async with self.__pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql)
                result = await cur.fetchall()
                return result

    async def async_query_sql_return_json(self, sql):
        aiomysql = _import_optional('aiomysql')
        async with self.__pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(sql)
                result = await cur.fetchall()
                return result

    async def async_close(self):
        self.__pool.close()
        await self.__pool.wait_closed()

    def __get_db_config(self, db_id) -> dict:
        current_env = get_runtime_env()
        conf_dic = {}
        if current_env == 'production':
            # # nacos retuens:
            # # {
            # #     "host": "IMMP-DBS-01.ICBC",
            # #     "port": 3306,
            # #     "db": "immpdb",
            # #     "user": "IMMP",
            # #     "password": "SU1NUCMxMjM=",
            # #     "charset": "utf8"
            # # }
            ini = os.path.join(CONFIG_DIR, 'database', 'production' + '.ini')
            config_base = ConfigObj(ini, encoding='utf-8')
            config = config_base.get(db_id)
            if not config:
                raise RuntimeError("missing database config section [{}] in {}".format(db_id, ini))
            conf_dic["user"] = config.get("user") or ""
            conf_dic["password"] = _p(config.get("password")) or ""
            conf_dic["host"] = config.get("host") or ""
            conf_dic["port"] = config.get("port") or ""
            conf_dic["db"] = config.get("database") or ""
        else:
            ini = os.path.join(CONFIG_DIR, 'database', 'development' + '.ini')
            config_base = ConfigObj(ini, encoding='utf-8')
            config = config_base.get(db_id)
            if not config:
                raise RuntimeError("missing database config section [{}] in {}".format(db_id, ini))
            conf_dic["user"] = config.get("user") or ""
            conf_dic["password"] = _p(config.get("password")) or ""
            conf_dic["host"] = config.get("host") or ""
            conf_dic["port"] = config.get("port") or ""
            conf_dic["db"] = config.get("database") or ""
        return conf_dic
