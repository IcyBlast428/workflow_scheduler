"""Text-SQL DWS ODBC dialect used by NewDB; no ORM/schema reflection promises.

Use SQLAlchemy's normal parameter compiler, transaction lifecycle and QueuePool
with the vendor DBAPI. PostgreSQL initialization queries are deliberately not
used: DWS is not assumed to implement PostgreSQL server-version semantics.
"""
from sqlalchemy.engine.default import DefaultDialect


def odbc_value(value):
    return '{' + str(value).replace('}', '}}') + '}'


class DWSDialect(DefaultDialect):
    name = 'wfs_dws'
    driver = 'pyodbc'
    default_paramstyle = 'qmark'
    supports_statement_cache = True
    supports_native_boolean = True

    @classmethod
    def import_dbapi(cls):
        import pyodbc
        # Also protect direct SQLAlchemy dialect loading before first connect.
        pyodbc.pooling = False
        return pyodbc

    def create_connect_args(self, url):
        options = [('DRIVER', url.query.get('driver', 'DWS')),
                   ('SERVERNAME', url.host), ('DATABASE', url.database),
                   ('UID', url.username), ('PWD', url.password),
                   ('PORT', url.port or 8000),
                   ('SSLMODE', url.query.get('sslmode', 'disable'))]
        return ([';'.join(key + '=' + odbc_value(value) for key, value in options)],
                {'timeout': 5, 'autocommit': False})

    def is_disconnect(self, error, connection, cursor):
        # ODBC class 08 is connection failure. Do not retry arbitrary SQL errors
        # or an interrupted transaction as if it had never executed.
        state = str(error.args[0]) if getattr(error, 'args', None) else ''
        return state.startswith('08') or state in {'HYT00', 'HYT01'} and connection is None
