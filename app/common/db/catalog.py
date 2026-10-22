"""One database capability catalog for NewDB and the administration UI."""
import importlib.util

DATABASES = {
    'mysql': {'label': 'MySQL / PolarDB / MariaDB', 'port': 3306, 'module': 'pymysql', 'package': 'PyMySQL', 'tls': True},
    'postgresql': {'label': 'PostgreSQL / GaussDB', 'port': 5432, 'module': 'psycopg', 'package': 'psycopg[binary]', 'tls': True},
    'clickhouse': {'label': 'ClickHouse', 'port': 8123, 'module': 'clickhouse_connect', 'package': 'clickhouse-connect[sqlalchemy]', 'tls': True},
    'sqlite': {'label': 'SQLite', 'port': None, 'module': 'sqlite3', 'package': 'Python 内置', 'tls': False},
}
ALIASES = {'polardb': 'mysql', 'mariadb': 'mysql', 'postgres': 'postgresql'}


def normalize(dialect):
    value = str(dialect or 'mysql').lower().strip()
    return ALIASES.get(value, value)


def capabilities():
    result = []
    for dialect, spec in DATABASES.items():
        available = importlib.util.find_spec(spec['module']) is not None
        result.append({'dialect': dialect, **spec, 'available': available})
    return result
