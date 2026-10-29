"""Fail-closed systemd user units with private PID/user/mount namespaces.

No privileged helper or broad sudo/polkit rule is installed. Kernel/systemd
namespace support and a user manager are required; process mode stays explicit.
"""
import json
import os
from pathlib import Path
import re
import subprocess

_units={}

def unit_name(run_id):
    if not re.fullmatch(r'[a-f0-9]{32}',run_id): raise ValueError('执行编号无效。')
    return 'wfs-task-'+run_id+'.service'

def wrapper(command,environment,task_root,sdk_root,data_dir,output_dir,run_id,limits):
    if os.name=='nt' or not sdk_root: raise ValueError('systemd 隔离仅用于 Linux 上已准备并冻结 SDK 的版本。')
    if not os.environ.get('XDG_RUNTIME_DIR'): raise ValueError('未检测到 systemd 用户会话；请配置任务用户管理器。')
    if 'WFS_TASK_CONNECTIONS_JSON' not in environment: raise ValueError('systemd 隔离要求启用任务的指定连接授权。')
    profiles=json.loads(environment['WFS_TASK_CONNECTIONS_JSON'])
    if any(p.get('dialect')=='sqlite' for p in profiles.values()):
        raise ValueError('当前隔离模式不开放共享 SQLite 业务文件；请使用独立数据库服务。')
    from app.bootstrap.global_vars import DATA_DIR,BASE_DIR
    unit=unit_name(run_id)
    base=Path(DATA_DIR).resolve();project=BASE_DIR.parent.resolve()
    # Hide both Linux and Windows-mounted user homes and all platform data.
    properties=['PrivateUsers=yes','PrivatePIDs=yes','ProtectSystem=strict','ProtectHome=tmpfs',
        'PrivateTmp=yes','PrivateDevices=yes','PrivateIPC=yes','ProtectControlGroups=yes',
        'NoNewPrivileges=yes','RestrictSUIDSGID=yes','RestrictNamespaces=yes','CapabilityBoundingSet=',
        'UMask=0077','KillMode=control-group','TasksMax='+str(int(limits.get('processes',64))),
        'MemoryMax='+str(int(limits.get('memory_mb') or 512))+'M','CPUQuota='+str(int(limits.get('cpu_percent',100)))+'%']
    for hidden in (base,Path('/mnt/c/Users')):
        if hidden.is_dir(): properties.append('TemporaryFileSystem='+str(hidden)+':ro')
    secrets=[Path('/etc/wfs'),project/'.git',project/'app/config',project/'logs']+list(project.glob('.env*'))
    properties.append('InaccessiblePaths='+' '.join('-'+str(p) for p in secrets))
    readonly=[Path(task_root),Path(sdk_root),Path(command[0]).absolute().parent.parent,Path(__file__).with_name('worker.py')]
    readonly.extend(Path(p['ssl_ca']).resolve() for p in profiles.values() if p.get('ssl_ca'))
    def path_value(paths):
        return ' '.join('"'+str(p).replace('\\','\\\\').replace('"','\\"')+'"' for p in paths)
    properties.append('BindReadOnlyPaths='+path_value(readonly))
    properties.append('BindPaths='+path_value([Path(data_dir),Path(output_dir)]))
    properties.append('ReadWritePaths='+path_value([Path(data_dir),Path(output_dir)]))
    # Remove all manager-imported variables which are not explicitly passed.
    manager=subprocess.check_output(['systemctl','--user','show-environment'],timeout=5,text=True)
    remove=[line.split('=',1)[0] for line in manager.splitlines() if '=' in line and line.split('=',1)[0] not in environment]
    if remove: properties.append('UnsetEnvironment='+' '.join(remove))
    args=['systemd-run','--user','--wait','--pipe','--collect','--quiet','--service-type=exec','--unit='+unit,
          '--working-directory='+str(task_root)]
    for value in properties: args+=['--property='+value]
    for key in environment: args+=['--setenv='+key]
    args+=['--',*command]
    env=dict(environment)
    for key in ('XDG_RUNTIME_DIR','DBUS_SESSION_BUS_ADDRESS'):
        if os.environ.get(key): env[key]=os.environ[key]
    return args,env,unit

def register(pid,unit): _units[pid]=unit

def stop(unit,force=True):
    if not re.fullmatch(r'wfs-task-[a-f0-9]{32}\.service',str(unit)): return
    signal='SIGKILL' if force else 'SIGTERM'
    try:
        subprocess.run(['systemctl','--user','kill','--kill-whom=all','--signal='+signal,unit],timeout=5,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False)
        if force:
            subprocess.run(['systemctl','--user','stop','--no-block',unit],timeout=5,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False)
    except (OSError,subprocess.SubprocessError):
        if not force: raise

def stop_process(pid,force=False):
    unit=_units.get(pid)
    if unit: stop(unit,force)
    if force: _units.pop(pid,None)


def probe():
    if os.name=='nt': return {'available':False,'message':'需要 Linux systemd 用户管理器。'}
    try:
        result=subprocess.run(['systemd-run','--user','--wait','--pipe','--collect','--quiet',
            '-p','PrivateUsers=yes','-p','PrivatePIDs=yes','-p','ProtectSystem=strict','-p','PrivateTmp=yes',
            '/usr/bin/true'],capture_output=True,timeout=15)
        return {'available':result.returncode==0,'message':'基础命名空间能力可用；任务启动仍逐次校验。' if result.returncode==0 else '命名空间探测未通过，不会回退到普通进程。'}
    except (OSError,subprocess.SubprocessError): return {'available':False,'message':'无法访问 systemd 用户管理器。'}
