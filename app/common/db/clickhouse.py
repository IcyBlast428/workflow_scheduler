# -*- coding: utf-8 -*-

from urllib.parse import quote_plus

from app.common.db.sqlalchemy_adapter import SQLAlchemyAdapter


class ClickHouseAdapter(SQLAlchemyAdapter):
    dialect = 'clickhouse'

    def build_url(self):
        password = quote_plus(self.config.get('password') or '')
        return (
            'clickhouse://{user}:{password}@{host}:{port}/{database}'
            .format(
                user=self.config.get('user') or '',
                password=password,
                host=self.config.get('host') or '',
                port=self.config.get('port') or '8123',
                database=self.config.get('database') or '',
            )
        )

    def get_ck_engine(self):
        clickhouse_driver = _import_optional('clickhouse_driver')
        self._ck_conn = clickhouse_driver.Client(
            settings={'use_client_time_zone': True},
            host=self.config.get('host') or '',
            port=9000,
            user=self.config.get('user') or '',
            password=self.config.get('password') or '',
            database=self.config.get('database') or '',
        )
        return self._ck_conn

    def ck_insert_many(self, sql, data):
        if not hasattr(self, '_ck_conn') or self._ck_conn is None:
            self.get_ck_engine()
        return self._ck_conn.execute(sql, data)


def _import_optional(module_name):
    try:
        return __import__(module_name)
    except ImportError as exc:
        raise RuntimeError('缺少可选数据库驱动 {}，请在对应任务环境中安装'.format(module_name)) from exc
