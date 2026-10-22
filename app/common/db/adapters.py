"""Driver-specific URLs and options; lifetime belongs to SQLAlchemyAdapter."""
import os
from pathlib import Path
from sqlalchemy.engine import URL
from app.common.db.sqlalchemy_adapter import SQLAlchemyAdapter
from app.bootstrap.global_vars import DATA_DIR


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


class SQLiteAdapter(SQLAlchemyAdapter):
    def build_url(self):
        database = self.config['database']
        if database == ':memory:':
            return URL.create('sqlite+pysqlite', database=database)
        path = Path(database).expanduser()
        if not path.is_absolute():
            path = Path(os.environ.get('WFS_DATA_DIR', DATA_DIR)) / 'business-databases' / path
        path = path.resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        return URL.create('sqlite+pysqlite', database=str(path))

    def connection_options(self):
        return {'check_same_thread': False, 'timeout': 10}
