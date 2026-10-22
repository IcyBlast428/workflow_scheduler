# -*- coding: utf-8 -*-

from sqlalchemy.engine import URL

from app.common.db.sqlalchemy_adapter import SQLAlchemyAdapter


class OracleAdapter(SQLAlchemyAdapter):
    dialect = 'oracle'

    def build_url(self):
        c = self.config
        return URL.create('oracle+oracledb', username=c['user'], password=c['password'], host=c['host'],
                          port=int(c.get('port') or 1521), query={'service_name': c['database']})

    def connection_options(self):
        options = {'tcp_connect_timeout': 5}
        if self.config.get('tls') == 'verify_identity':
            import ssl
            options.update(protocol='tcps', ssl_server_dn_match=True,
                           ssl_context=ssl.create_default_context(cafile=self.config['ssl_ca']))
        return options
