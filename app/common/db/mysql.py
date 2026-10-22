# -*- coding: utf-8 -*-

from sqlalchemy.engine import URL

from app.common.db.sqlalchemy_adapter import SQLAlchemyAdapter


class MySQLAdapter(SQLAlchemyAdapter):
    dialect = 'mysql'

    def build_url(self):
        return URL.create('mysql+pymysql', username=self.config.get('user') or '',
                          password=self.config.get('password') or '', host=self.config.get('host') or '',
                          port=int(self.config.get('port') or 3306), database=self.config.get('database') or '',
                          query={'charset': self.config.get('charset') or 'utf8mb4'})

    def connection_options(self):
        options = {'connect_timeout': 5, 'read_timeout': 30, 'write_timeout': 30, 'local_infile': False}
        if self.config.get('tls') == 'verify_identity':
            options.update(ssl_ca=self.config['ssl_ca'], ssl_verify_cert=True, ssl_verify_identity=True)
        elif self.config.get('tls') == 'disabled':
            options['ssl_disabled'] = True
        return options
