# -*- coding: utf-8 -*-

from sqlalchemy.engine import URL

from app.common.db.sqlalchemy_adapter import SQLAlchemyAdapter


class ClickHouseAdapter(SQLAlchemyAdapter):
    dialect = 'clickhouse'

    def build_url(self):
        # Explicit dialect avoids collisions with clickhouse-sqlalchemy.
        import clickhouse_connect.cc_sqlalchemy  # noqa: F401
        c = self.config
        return URL.create('clickhousedb+connect', username=c['user'], password=c['password'], host=c['host'],
                          port=int(c.get('port') or 8123), database=c['database'])

    def connection_options(self):
        options = {'connect_timeout': 5, 'send_receive_timeout': 30,
                   'secure': self.config.get('tls') == 'verify_identity'}
        if options['secure']:
            options.update(verify=True, ca_cert=self.config['ssl_ca'])
        return options

    def get_ck_engine(self):
        self._check_owner()
        if getattr(self, '_ck_conn', None) is not None:
            return self._ck_conn
        clickhouse_driver = _import_optional('clickhouse_driver')
        self._ck_conn = clickhouse_driver.Client(
            settings={'use_client_time_zone': True},
            host=self.config.get('host') or '',
            port=int(self.config.get('native_port') or 9000),
            user=self.config.get('user') or '',
            password=self.config.get('password') or '',
            database=self.config.get('database') or '',
        )
        return self._ck_conn

    def close(self):
        self._check_owner()
        try:
            if getattr(self, '_ck_conn', None) is not None:
                self._ck_conn.disconnect()
                self._ck_conn = None
        finally:
            super().close()

    def ck_insert_many(self, sql, data):
        if not hasattr(self, '_ck_conn') or self._ck_conn is None:
            self.get_ck_engine()
        return self._ck_conn.execute(sql, data)


def _import_optional(module_name):
    try:
        return __import__(module_name)
    except ImportError as exc:
        raise RuntimeError('缺少可选数据库驱动 {}，请在对应任务环境中安装'.format(module_name)) from exc
