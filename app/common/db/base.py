# -*- coding: utf-8 -*-


class DatabaseAdapter:
    """数据库适配器基类，约束公共方法，避免任务代码直接依赖具体驱动细节。"""

    def get_engine(self, *args, **kwargs):
        raise NotImplementedError

    def get_connection(self):
        raise NotImplementedError

    def close(self):
        raise NotImplementedError

    def close_connection(self):
        self.close()

    def execute_single_sql(self, sql, params=None):
        raise NotImplementedError

    def execute_query_sql(self, sql, return_json=False, params=None):
        raise NotImplementedError

    def insert_many(self, sql, args):
        raise NotImplementedError

    def insert_with_rollback(self, sql, args):
        raise NotImplementedError

    def __enter__(self):
        self.get_engine()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()
