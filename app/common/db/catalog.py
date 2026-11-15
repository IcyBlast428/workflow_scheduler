"""Explicit, extensible database capabilities shared by NewDB and the admin UI.

Adding a connection never imports arbitrary code from a profile. A new database
family needs a reviewed adapter here; instances of supported families are data.
"""
import importlib.util

DATABASES = {
    'mysql': {'label': 'MySQL / PolarDB / MariaDB', 'port': 3306, 'module': 'pymysql', 'package': 'PyMySQL', 'tls': True, 'transactions': True},
    'postgresql': {'label': 'PostgreSQL', 'port': 5432, 'module': 'psycopg', 'package': 'psycopg[binary]', 'tls': True, 'transactions': True},
    'gaussdb': {'label': 'GaussDB / DWS（ODBC）', 'port': 8000, 'module': 'pyodbc', 'package': 'pyodbc', 'tls': True, 'transactions': True,
                'odbc_driver': True, 'default_driver': 'DWS', 'tls_modes': ['disabled', 'require'], 'ca_file': False,
                'tls_note': 'DWS ODBC 的主机名校验能力取决于厂商版本；当前仅提供不加密或仅加密模式，不能视为已验证证书。'},
    'clickhouse': {'label': 'ClickHouse', 'port': 8123, 'module': 'clickhouse_connect', 'package': 'clickhouse-connect[sqlalchemy]', 'tls': True, 'transactions': False},
}
ALIASES = {'polardb': 'mysql', 'mariadb': 'mysql', 'postgres': 'postgresql',
           'dws': 'gaussdb', 'gauss': 'gaussdb'}


def normalize(dialect):
    value = str(dialect or 'mysql').lower().strip()
    return ALIASES.get(value, value)


def installed_odbc_drivers():
    try:
        import pyodbc
        return sorted(set(pyodbc.drivers()))
    except (ImportError, OSError, RuntimeError):
        return []


def capabilities():
    """页面能力来自与工厂一致的目录；驱动已安装不等于目标库已连通。"""
    result = []
    installed = installed_odbc_drivers()
    for dialect, spec in DATABASES.items():
        available = importlib.util.find_spec(spec['module']) is not None
        value = {'dialect': dialect, 'database_label': '数据库名称',
                 'tls_modes': ['disabled', 'verify_identity'], 'ca_file': True,
                 **spec, 'available': available}
        if spec.get('odbc_driver'):
            value['installed_drivers'] = installed
            value['driver_ready'] = available and spec['default_driver'] in installed
        else:
            value['driver_ready'] = available
        result.append(value)
    return result
