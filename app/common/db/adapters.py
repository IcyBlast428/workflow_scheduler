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


class SQLServerAdapter(SQLAlchemyAdapter):
    def build_url(self):
        c = self.config
        return URL.create('mssql+pyodbc', username=c['user'], password=c['password'],
                          host=c['host'], port=int(c.get('port') or 1433), database=c['database'],
                          query={'driver': c.get('driver') or 'ODBC Driver 18 for SQL Server',
                                 'Encrypt': 'yes' if c.get('tls') == 'verify_identity' else 'no',
                                 'TrustServerCertificate': 'no'})

    def connection_options(self):
        return {'timeout': 5}


class OracleAdapter(SQLAlchemyAdapter):
    def build_url(self):
        c = self.config
        return URL.create('oracle+oracledb', username=c['user'], password=c['password'],
                          host=c['host'], port=int(c.get('port') or 1521),
                          query={'service_name': c['database']})

    def connection_options(self):
        c = self.config
        # Explicit structured connect args override the descriptor assembled by
        # SQLAlchemy, so tcps cannot be shadowed by a default tcp descriptor.
        options = {'dsn': None, 'host': c['host'], 'port': int(c.get('port') or 1521),
                   'service_name': c['database'], 'tcp_connect_timeout': 5,
                   'protocol': 'tcp'}
        if c.get('tls') == 'verify_identity':
            import ssl
            options.update(protocol='tcps', ssl_server_dn_match=True,
                           ssl_context=ssl.create_default_context(cafile=c['ssl_ca']))
        return options
