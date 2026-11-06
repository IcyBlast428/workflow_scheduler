"""Guided root deployment; use `bash deploy.sh` from /data/workflow_scheduler."""
import argparse
from contextlib import contextmanager
import getpass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import subprocess
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.service_config import read_environment, serialize_environment

PROJECT = Path('/data/workflow_scheduler')
UNITS = ('wfs-scheduler.service', 'wfs.service')
DEFAULT_INDEX = 'http://nexus.immp.icbc/repository/pypi-hosted/simple/'


def run(command, **kwargs):
    return subprocess.run([str(arg) for arg in command], check=True, **kwargs)


def assert_stopped():
    for unit in UNITS:
        result = run(['systemctl', 'show', '--property=ActiveState', '--value', unit], capture_output=True, text=True)
        if result.stdout.strip() not in ('', 'inactive', 'failed'):
            raise ValueError('服务仍在运行，请先在页面开启维护并排空任务，再执行 bash deploy.sh stop。')


def assert_units_compatible(project=ROOT, unit_dir=Path('/etc/systemd/system')):
    for name in UNITS:
        target = unit_dir/name
        if target.is_symlink() or target.exists() and target.read_bytes() != (project/'deploy/root-test'/name).read_bytes():
            raise ValueError(f'发现另一套或不同版本的服务定义，请先备份并核对：{target}')


@contextmanager
def deployment_lock(project=ROOT):
    import fcntl
    with (project/'.deploy.lock').open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('已有部署或配置操作在进行，请勿重复执行。') from None
        yield


def verify_package(project=ROOT):
    manifest = project/'PACKAGE-MANIFEST.json'
    if not manifest.exists():
        print('当前为源码目录；部署包中会附带完整文件校验清单。')
        return
    files = json.loads(manifest.read_text(encoding='utf-8'))['files']
    for item in files:
        relative = PurePosixPath(item['path'])
        if relative.is_absolute() or '..' in relative.parts or '\\' in item['path'] or ':' in item['path']:
            raise ValueError('部署包清单包含非法路径')
        path = project.joinpath(*relative.parts)
        if not path.resolve().is_relative_to(project.resolve()) or not path.is_file():
            raise ValueError(f'部署包缺少文件或路径不安全：{relative}')
        if hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
            raise ValueError(f'部署包文件已改变或损坏：{relative}；请从原 ZIP 重新解压代码。')
    print(f'部署包校验通过：{len(files)} 个文件。')


def validate_values(values):
    for key in ('WFS_SECRET_KEY', 'WFS_CONNECTIONS_KEY', 'WFS_ADMIN_PASSWORD_HASH',
                'WFS_NACOS_URL', 'WFS_NACOS_USERNAME', 'WFS_NACOS_PASSWORD', 'WFS_DB_ID'):
        if not values.get(key) or 'CHANGE_ME' in values[key]:
            raise ValueError('请先完成配置：' + key)
    if values.get('WFS_STATE_BACKEND') != 'gauss' or values.get('WFS_DB_DRIVER') != 'DWS':
        raise ValueError('此入口使用 GaussDB/DWS，WFS_STATE_BACKEND=gauss、WFS_DB_DRIVER=DWS。')
    if any(values.get(key) for key in ('WFS_POSTGRES_TEST', 'WFS_LOCAL_DB_PATH', 'WFS_DB_DIALECT')):
        raise ValueError('部署配置不能包含本机测试数据库开关。')
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9]*_[A-Za-z_][A-Za-z0-9_]*', values['WFS_DB_ID']):
        raise ValueError('连接标识使用 数据库名_schema，例如 wfsscheduler_wfs；数据库名不要包含下划线。')
    parsed = urlsplit(values['WFS_NACOS_URL'])
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Nacos 地址应为 http(s)://主机:端口/nacos，不在地址中填写密码。')


def prompt(label, default='', secret=False):
    suffix = '（回车保留）' if secret and default else f' [{default}]' if default else ''
    value = (getpass.getpass if secret else input)(label + suffix + ': ') or default
    if not value or any(ord(char) < 32 for char in value):
        raise ValueError(label + '不能为空或包含控制字符')
    return value


def configure(project=ROOT, edit=False):
    from scripts.install_systemd import atomic_write
    from scripts.setup_root_test import initialize
    config = project/'deploy/root-test/runtime.env'
    if config.is_symlink():
        raise ValueError('runtime.env 不允许为符号链接。')
    if not config.exists():
        password = prompt('设置 admin 登录密码（至少 12 位）', secret=True)
        if len(password) < 12 or password != getpass.getpass('再次输入登录密码: '):
            raise ValueError('两次密码须一致且至少 12 位。')
        initialize(project, password)
    values, unset = read_environment(config)
    if not edit:
        try:
            validate_values(values)
            print('沿用已有配置、管理员密码和加密密钥。')
            return config
        except ValueError:
            pass
    print('连接信息沿用现有 Nacos 方式；无需修改项目源码。')
    for key, label, secret in (
        ('WFS_NACOS_URL', 'Nacos 地址（含 /nacos）', False),
        ('WFS_NACOS_USERNAME', 'Nacos 用户名', False),
        ('WFS_NACOS_PASSWORD', 'Nacos 密码', True),
        ('WFS_DB_ID', '平台数据库标识', False),
    ):
        default = values.get(key, '')
        values[key] = prompt(label, '' if 'CHANGE_ME' in default else default, secret)
    values['WFS_NACOS_URL'] = values['WFS_NACOS_URL'].rstrip('/')
    validate_values(values)
    # Atomic writes and literal quoting preserve spaces, #, $, quotes and backslashes.
    atomic_write(config, serialize_environment(values) + ''.join(f'unset {key}\n' for key in sorted(unset)), 0o600)
    database, schema = values['WFS_DB_ID'].split('_', 1)
    print(f'配置已保存：{config}\n请确认 Nacos 中 group=gauss、dataId=gauss.{database}.{schema}.json 已配置。')
    return config


def production_environment(project=ROOT):
    values, unset = read_environment(project/'deploy/root-test/runtime.env')
    validate_values(values)
    environment = dict(os.environ)
    for key in unset:
        environment.pop(key, None)
    environment.update(values)
    for key in ('WFS_POSTGRES_TEST', 'WFS_LOCAL_DB_PATH', 'WFS_DB_DIALECT', 'GUNICORN_CMD_ARGS', 'GUNICORN_FD', 'WFS_DEV_RUN_ALL'):
        environment.pop(key, None)
    environment.update(WFS_ENV='production', WFS_ENABLE_SCHEDULER='false', WFS_SCHEDULER_CONTROL_URL='',
                       WFS_DATA_DIR=str(project/'data'), WFS_LOG_DIR=str(project/'logs'), PYTHONDONTWRITEBYTECODE='1')
    return environment


def pip_options(index, wheelhouse=None):
    if wheelhouse:
        path = Path(wheelhouse).resolve()
        if not path.is_dir():
            raise ValueError('离线 wheel 目录不存在：' + str(path))
        return ['--no-index', '--find-links', str(path)]
    parsed = urlsplit(index)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('依赖索引须为不含账号密码的 HTTP(S) 地址。认证请使用服务器 pip 配置。')
    result = ['--index-url', index]
    if parsed.scheme == 'http':
        result += ['--trusted-host', parsed.hostname]
    return result


def pip_environment():
    # An inherited extra-index must not silently contact public PyPI or another server.
    environment = {key:value for key, value in os.environ.items()
                   if not key.startswith('PIP_') or key in ('PIP_CERT', 'PIP_CLIENT_CERT')}
    environment.update(PIP_CONFIG_FILE=os.devnull, PIP_DISABLE_PIP_VERSION_CHECK='1')
    return environment


def ensure_venv(project=ROOT):
    python = project/'.venv/bin/python'
    if not python.exists():
        print('[1/5] 创建 Python 虚拟环境', flush=True)
        run([sys.executable, '-m', 'venv', project/'.venv'])
    version = run([python, '-c', 'import sys; print("%s.%s" % sys.version_info[:2])'], capture_output=True, text=True)
    if version.stdout.strip() != '3.12':
        raise ValueError('.venv 必须使用 Python 3.12，请勿覆盖已有环境。')
    return python


def driver_check(environment, python, project=ROOT):
    script = '''import configparser, ctypes, os, pathlib, pyodbc
config=configparser.ConfigParser(interpolation=None)
config.read(pathlib.Path(os.environ['ODBCSYSINI'])/'odbcinst.ini')
driver=config.get('DWS','Driver64',fallback=config.get('DWS','Driver',fallback=''))
if not driver: raise RuntimeError('odbcinst.ini 缺少 [DWS] 驱动路径')
ctypes.CDLL(driver)
if 'DWS' not in pyodbc.drivers(): raise RuntimeError('unixODBC 未识别 DWS 注册名')
print('DWS ODBC 驱动加载通过')
'''
    run([python, '-c', script], env=environment, cwd=project)


def check_database(python, environment, initialize=False, project=ROOT):
    driver_check(environment, python, project)
    if initialize:
        run([python, project/'scripts/init_database.py'], env=environment, cwd=project)
    run([python, project/'scripts/check_gauss_platform.py'], env=environment, cwd=project)


def ready(python, project=ROOT):
    for port in (8009, 8008):
        run([python, project/'scripts/wait_ready.py', '--url', f'http://127.0.0.1:{port}/api/user/ready', '--timeout', '90'])
    print('\n部署完成：浏览器访问 http://<服务器IP>:8008/ ，登录名 admin，密码为刚才设置的密码。')


def install(args):
    verify_package()
    if not (ROOT/'app/dist/index.html').is_file():
        raise ValueError('缺少已构建前端，请使用完整部署 ZIP。')
    python = ensure_venv()
    if not args.skip_dependencies:
        print('[2/5] 从内网索引或离线目录安装锁定依赖', flush=True)
        run([python, '-m', 'pip', '--disable-pip-version-check', 'install', *pip_options(args.index_url, args.wheelhouse), '-r', ROOT/'requirements-linux-py312.lock'], env=pip_environment())
    run([python, '-m', 'pip', 'check'])
    if Path(sys.prefix).resolve() != (ROOT/'.venv').resolve():
        # Resume inside the new environment; do not install or alter system Python.
        # exec closes the non-inheritable lock descriptor before the new process locks.
        os.execv(str(python), [str(python), __file__, 'install', '--skip-dependencies'])
    print('[3/5] 设置管理员与 Nacos / GaussDB 配置', flush=True)
    for folder in ('data', 'logs'):
        (ROOT/folder).mkdir(exist_ok=True, mode=0o700)
    configure()
    environment = production_environment()
    print('[4/5] 检查驱动并初始化空 schema；已有本版表只做校验', flush=True)
    check_database(python, environment, initialize=True)
    print('[5/5] 安装并启动 Web 与单实例 Scheduler', flush=True)
    run([python, ROOT/'scripts/setup_root_test.py', '--install'], env=environment)
    ready(python)
    return


def main():
    parser = argparse.ArgumentParser(description='root + /data/workflow_scheduler + GaussDB 引导部署')
    parser.add_argument('action', nargs='?', default='install', choices=('install', 'configure', 'check', 'start', 'stop', 'status', 'logs', 'verify'))
    parser.add_argument('--index-url', default=DEFAULT_INDEX)
    parser.add_argument('--wheelhouse', help='离线 Linux x86_64 / Python 3.12 wheel 目录')
    parser.add_argument('--skip-dependencies', action='store_true', help='已自行安装锁定依赖时使用，仍执行 pip check')
    args = parser.parse_args()
    if args.action == 'verify':
        verify_package()
        return
    if sys.version_info[:2] != (3, 12) or sys.platform != 'linux' or os.geteuid() != 0 or ROOT != PROJECT:
        parser.error('请在 Linux 上以 root 使用 Python 3.12，从 /data/workflow_scheduler 运行。')
    if platform.machine().lower() not in ('x86_64', 'amd64'):
        parser.error('当前依赖锁和随包驱动面向 x86_64；其他架构需准备对应驱动和依赖。')
    if not shutil.which('systemctl') or not Path('/run/systemd/system').is_dir():
        parser.error('服务器必须由 systemd 管理服务。')
    if args.action in ('status', 'logs'):
        if args.action == 'logs':
            run(['journalctl', '-u', UNITS[0], '-u', UNITS[1], '-n', '100', '--no-pager'])
        else:
            # `status` intentionally preserves systemctl's nonzero exit for stopped services.
            run(['systemctl', 'status', *UNITS, '--no-pager', '--full'])
        return
    with deployment_lock():
        if args.action == 'stop':
            run(['systemctl', 'stop', 'wfs.service', 'wfs-scheduler.service'])
            return
        assert_units_compatible()
        if args.action in ('install', 'configure'):
            assert_stopped()
        if args.action == 'install':
            install(args)
            return
        python = ROOT/'.venv/bin/python'
        if not python.is_file():
            raise ValueError('尚未部署，请先运行 bash deploy.sh。')
        if args.action == 'configure':
            configure(edit=True)
        elif args.action == 'check':
            run([python, '-m', 'pip', 'check'])
            check_database(python, production_environment())
            print('依赖、配置、驱动和平台表检查通过；未修改数据库。')
        elif args.action == 'start':
            check_database(python, production_environment())
            run(['systemctl', 'start', 'wfs-scheduler.service', 'wfs.service'])
            ready(python)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError, EOFError) as exc:
        # Never print command argv or environment: pip config can contain credentials.
        print('\n部署未完成：' + (str(exc) if isinstance(exc, (ValueError, EOFError)) else '外部命令执行失败，请查看上方错误。'), file=sys.stderr)
        print('配置和数据保留，可修正后重新运行。服务日志：bash deploy.sh logs', file=sys.stderr)
        raise SystemExit(1)
