"""One database capability catalog for NewDB and the administration UI."""
import importlib.util

DATABASES = {
    'mysql': {'label': 'MySQL / PolarDB / MariaDB', 'port': 3306, 'module': 'pymysql', 'package': 'PyMySQL', 'tls': True},
    'postgresql': {'label': 'PostgreSQL', 'port': 5432, 'module': 'psycopg', 'package': 'psycopg[binary]', 'tls': True},
    'oracle': {'label': 'Oracle', 'port': 1521, 'module': 'oracledb', 'package': 'oracledb', 'tls': True},
    'mssql': {'label': 'SQL Server', 'port': 1433, 'module': 'pyodbc', 'package': 'pyodbc + Microsoft ODBC Driver', 'tls': True},
    'clickhouse': {'label': 'ClickHouse', 'port': 8123, 'module': 'clickhouse_connect', 'package': 'clickhouse-connect[sqlalchemy]', 'tls': True},
    'sqlite': {'label': 'SQLite', 'port': None, 'module': 'sqlite3', 'package': 'Python 内置', 'tls': False},
}
ALIASES = {'polardb': 'mysql', 'mariadb': 'mysql', 'postgres': 'postgresql', 'sqlserver': 'mssql'}


def normalize(dialect):
    value = str(dialect or 'mysql').lower().strip()
    return ALIASES.get(value, value)


def capabilities():
    result = []
    for dialect, spec in DATABASES.items():
        available = importlib.util.find_spec(spec['module']) is not None
        drivers = []
        if dialect == 'mssql' and available:
            try:
                import pyodbc
                drivers = [name for name in pyodbc.drivers() if 'SQL Server' in name]
            except (ImportError, OSError):
                drivers = []
            available = bool(drivers)
        result.append({'dialect': dialect, **spec, 'available': available, 'odbc_drivers': drivers})
    return result
