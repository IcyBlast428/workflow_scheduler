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
    'sqlserver': {'label': 'SQL Server', 'port': 1433, 'module': 'pyodbc', 'package': 'pyodbc', 'tls': True, 'transactions': True,
                  'odbc_driver': True, 'default_driver': 'ODBC Driver 18 for SQL Server', 'ca_file': False,
                  'tls_note': '校验证书模式使用服务器的系统信任库；须为 Web 和任务运行环境安装受信任 CA。'},
    'oracle': {'label': 'Oracle', 'port': 1521, 'module': 'oracledb', 'package': 'oracledb', 'tls': True, 'transactions': True,
               'database_label': '服务名（Service Name）', 'tls_note': '使用 python-oracledb Thin 模式与 Service Name，旧版数据库请先验证驱动兼容性。'},
    'clickhouse': {'label': 'ClickHouse', 'port': 8123, 'module': 'clickhouse_connect', 'package': 'clickhouse-connect[sqlalchemy]', 'tls': True, 'transactions': False},
}
ALIASES = {'polardb': 'mysql', 'mariadb': 'mysql', 'postgres': 'postgresql',
           'dws': 'gaussdb', 'gauss': 'gaussdb', 'mssql': 'sqlserver'}


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
