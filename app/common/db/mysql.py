# -*- coding: utf-8 -*-

from urllib.parse import quote_plus

from app.common.db.sqlalchemy_adapter import SQLAlchemyAdapter


class MySQLAdapter(SQLAlchemyAdapter):
    dialect = 'mysql'

    def build_url(self):
        password = quote_plus(self.config.get('password') or '')
        return (
            'mysql+pymysql://{user}:{password}@{host}:{port}/{database}?charset={charset}'
            .format(
                user=self.config.get('user') or '',
                password=password,
                host=self.config.get('host') or '',
                port=self.config.get('port') or '3306',
                database=self.config.get('database') or '',
                charset=self.config.get('charset') or 'utf8',
            )
        )
