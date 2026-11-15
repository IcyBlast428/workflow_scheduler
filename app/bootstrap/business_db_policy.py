"""Static publication rule: business database access goes through NewDB.

This is a maintainability/credential governance check for reviewed Python code,
not a sandbox. Dynamic code, arbitrary network clients and third-party packages
still require review and operating-system/network controls when untrusted.
"""
import ast
from pathlib import Path

POLICY_VERSION = 1
DRIVERS = frozenset({'pymysql', 'psycopg', 'psycopg2', 'pyodbc', 'pymssql', 'oracledb',
                     'cx_Oracle', 'clickhouse_connect', 'clickhouse_driver', 'asyncpg',
                     'aiomysql', 'aiosqlite', 'sqlite3', 'pg8000', 'mariadb', 'duckdb'})
FACTORIES = frozenset({'create_engine', 'create_async_engine', 'engine_from_config',
                       'async_engine_from_config', 'create_pool_from_url'})


def _forbidden_module(name):
    return (name.split('.')[0] in DRIVERS or name.startswith(('mysql.connector', 'snowflake.connector',
            'app.bootstrap.database', 'app.common.db.adapters', 'app.common.db.mysql',
            'app.common.db.clickhouse', 'app.common.db.engine_pool', 'app.common.db.dws_dialect')))


def inspect_source(source, path='main.py'):
    tree = ast.parse(source, filename=path)
    aliases, findings = {}, {}

    def report(node, name):
        findings[node.lineno, name] = {'path': path, 'line': node.lineno, 'symbol': name,
            'message': '业务数据库必须通过 NewDB(连接标识) 访问；请先在数据库连接页面配置并授权该连接。'}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                aliases[alias.asname or alias.name.split('.')[0]] = alias.name if alias.asname else alias.name.split('.')[0]
                if _forbidden_module(alias.name):
                    report(node, alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ''
            for alias in node.names:
                name = module + '.' + alias.name
                aliases[alias.asname or alias.name] = name
                if (_forbidden_module(module) or _forbidden_module(name)
                        or name in {'app.common.database.GaussDB', 'app.common.db.factory.adapter_for'}
                        or module.startswith('sqlalchemy') and alias.name in FACTORIES):
                    report(node, name)

    def qualified(node):
        if isinstance(node, ast.Name):
            return aliases.get(node.id, node.id)
        if isinstance(node, ast.Attribute):
            base = qualified(node.value)
            return base + '.' + node.attr if base else ''
        return ''

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = qualified(node.func)
        if (_forbidden_module(name) or name.startswith('sqlalchemy.') and name.rsplit('.', 1)[-1] in FACTORIES
                or name in {'app.common.database.GaussDB', 'app.common.db.factory.adapter_for'}):
            report(node, name)
        if name in {'__import__', 'importlib.import_module'} and node.args:
            argument = node.args[0]
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str) and _forbidden_module(argument.value):
                report(node, argument.value)
    return [findings[key] for key in sorted(findings)]


def inspect_tree(root):
    root = Path(root)
    if not root.is_dir() or root.is_symlink():
        raise ValueError('任务代码目录不存在或包含符号链接。')
    findings = []
    for path in sorted(root.rglob('*.py')):
        if path.is_symlink():
            raise ValueError('任务代码不能包含符号链接。')
        findings.extend(inspect_source(path.read_bytes(), path.relative_to(root).as_posix()))
        if len(findings) >= 100:
            break
    return {'version': POLICY_VERSION, 'entry': 'NewDB', 'passed': not findings,
            'violations': findings[:100], 'scope': 'static_source_check'}


def enforce(root):
    report = inspect_tree(root)
    if report['violations']:
        locations = '；'.join(f"{item['path']}:{item['line']}（{item['symbol']}）" for item in report['violations'][:6])
        raise ValueError('数据库访问规范检查未通过：' + locations + '。业务连接请统一使用 from app.common.database import NewDB，再用 NewDB("连接标识")；原生驱动由 NewDB 内部管理。')
    return report
