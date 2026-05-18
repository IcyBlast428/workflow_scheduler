# -*- coding: utf-8 -*-

from urllib.parse import quote_plus

from app.common.db.sqlalchemy_adapter import SQLAlchemyAdapter


class OracleAdapter(SQLAlchemyAdapter):
    dialect = 'oracle'

    def build_url(self):
        password = quote_plus(self.config.get('password') or '')
        return (
            'oracle+cx_oracle://{user}:{password}@{host}:{port}/?service_name={database}'
            .format(
                user=self.config.get('user') or '',
                password=password,
                host=self.config.get('host') or '',
                port=self.config.get('port') or '1521',
                database=self.config.get('database') or '',
            )
        )
