# -*- coding=utf-8 -*-
# 全局变量 公共方法 公共工具类 如果需要负载均衡此处代码需要的变量可以存放到redis中
import os
import threading
import uuid
import pathlib

# BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根路径
BASE_DIR = pathlib.Path(__file__).resolve().parents[1]  # 项目根路径

# CONFIG_DIR = os.path.join(BASE_DIR, 'config')
CONFIG_DIR = BASE_DIR/("config")

ROOT_LOG_DIR = str(BASE_DIR.parent / 'logs')

DATA_DIR = str(BASE_DIR.parent / 'data')


# 加密
def encrypt(obj):
    '''
    :param obj: ex:{name:wang,age:18,...} 加密对象
    :return: 返回加密字符串token
    '''
    token = ''
    return token


# 解密
def decrypt(token):
    '''
    :param token: 解密字符串token
    :return: 返回解密对象
    '''
    userobj = {}
    return userobj


# 用于数据库id或唯一编码
def uuidhex() -> str:
    '''
    :return: ex:0def62f0cd7811ea9d66f40f241ab3c9
    '''
    return uuid.uuid1().hex


# 接口统一返回值 失败返回
def error_msg(mes=None):
    '''
    :param mes: 报错对象obj信息
    :return: 返回数据错误对象
    '''
    errObj = {
        "data": {},
        "status": "failure",
        "code": 100,
        "message": '{}'.format(mes) if mes else ''
    }
    return errObj


# 成功返回
def success_msg(data: [str, dict, list] = None):
    '''
    :param data: 前端数据
    :return: 返回对象
    '''
    successObj = {
        "data": data if data is not None else {},
        "status": "success",
        "code": 20000
    }
    return successObj


def println(msg):
    """用于任务脚本中打印含有非ascii码的语句时的乱码问题"""
    if not all(ord(c) < 128 for c in msg):  # 包含非ASCII码
        msg = msg.encode('utf-8').decode('latin-1')
    print(msg)


class RunningState:
    def __init__(self):
        self._peddings = []
        self._lock = threading.Lock()

    def is_running(self, pid):
        with self._lock:
            for p in self._peddings:
                process_id = p.get(pid)
                if process_id:
                    return True
            return False

    def get(self, pid):
        with self._lock:
            for r in self._peddings:
                process_id = r.get(pid)
                if process_id:
                    return r
            return None

    def append(self, obj):
        with self._lock:
            if obj not in self._peddings:
                self._peddings.append(obj)

    def remove(self, obj):
        with self._lock:
            while obj in self._peddings:
                self._peddings.remove(obj)

    def __contains__(self, item):
        with self._lock:
            return item in self._peddings


class IgnoredTask:
    def __init__(self):
        self._task_pids = set()
        self._lock = threading.Lock()

    def add(self, obj):
        with self._lock:
            self._task_pids.add(obj)

    def remove(self, obj):
        with self._lock:
            if obj in self._task_pids:
                self._task_pids.remove(obj)

    def __contains__(self, pid):
        with self._lock:
            return pid in self._task_pids


# 忽略的调度 如停止 已存在的报错调度
ignores = IgnoredTask()

# 记录正在执行中的程序执行完 销毁对象
runnings = RunningState()

# 调度文件所在目录
# TASK_DIR = os.path.join(BASE_DIR, 'jobs')
TASK_DIR = BASE_DIR/("jobs")
