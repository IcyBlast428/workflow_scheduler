"""Driver-specific URLs and options; lifetime belongs to SQLAlchemyAdapter."""
from sqlalchemy.engine import URL
from app.common.db.sqlalchemy_adapter import SQLAlchemyAdapter


class PostgreSQLAdapter(SQLAlchemyAdapter):
    def build_url(self):
        c = self.config
        return URL.create('postgresql+psycopg', username=c['user'], password=c['password'], host=c['host'],
                          port=int(c.get('port') or 5432), database=c['database'])

    def connection_options(self):
        options = {'connect_timeout': 5, 'options': '-c statement_timeout=30000'}
        if self.config.get('tls') == 'verify_identity':
            options.update(sslmode='verify-full', sslrootcert=self.config['ssl_ca'])
        else:
            options['sslmode'] = 'disable'
        return options


class GaussDBAdapter(SQLAlchemyAdapter):
    def build_url(self):
        from sqlalchemy.dialects import registry
        registry.register('wfs_dws.pyodbc', 'app.common.db.dws_dialect', 'DWSDialect')
        c = self.config
        return URL.create('wfs_dws+pyodbc', username=c['user'], password=c['password'],
                          host=c['host'], port=int(c.get('port') or 8000), database=c['database'],
                          query={'driver': c.get('driver') or 'DWS',
                                 'sslmode': 'require' if c.get('tls') == 'require' else 'disable'})
