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
