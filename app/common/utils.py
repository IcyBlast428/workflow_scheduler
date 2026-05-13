# utilities for logging and file

import os
import re
import json
import socket
import logging
import requests
from datetime import datetime
from logging import Formatter
from logging.handlers import RotatingFileHandler

from app.bootstrap.global_vars import ROOT_LOG_DIR, DATA_DIR
from app.common.nacos import Nacos


def get_local_ip():
    hostname = socket.gethostname()
    ip_addr = socket.gethostbyname(hostname)
    return ip_addr


def wfs_print(*msg):
    try:
        print(datetime.now().strftime('%F %X'), *msg, end='\n')
    except UnicodeEncodeError:
        print(datetime.now().strftime('%Y-%m-%d %H:%M:%S'), *tuple(str(i).encode('utf-8').decode('latin-1') for i in msg), end='\n')


def get_data_dir(job_entry_file):
    group_dir_name, job_dir_name, pid = get_basic_dir(job_entry_file)
    job_data_dir = os.path.join(DATA_DIR, group_dir_name, job_dir_name)
    if not os.path.exists(job_data_dir):
        os.makedirs(job_data_dir)
    return job_data_dir


def init_logger(job_entry_file, level=logging.INFO):
    group_dir_name, job_dir_name, pid = get_basic_dir(job_entry_file)
    print(group_dir_name, job_dir_name, pid)
    job_log_dir = os.path.join(ROOT_LOG_DIR, group_dir_name, job_dir_name)
    print(job_log_dir)

    if not os.path.exists(job_log_dir):
        os.makedirs(job_log_dir)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    rfh = RotatingFileHandler(os.path.join(job_log_dir, job_dir_name + '.log'),
                              maxBytes=1024 * 1024 * 10,
                              backupCount=5, encoding='utf8')
    formatter = Formatter(
        '[{0}] [{1}] [%(asctime)s] [%(name)s] [%(levelname)s] %(message)s  %(module)s:%(lineno)d'.format(
            'S1-WFS-' + pid,
            get_local_ip())
    )

    rfh.setFormatter(formatter)
    rfh.setLevel(level)
    root_logger.addHandler(rfh)


# 获取项目所有在的分组目录和项目目录
def get_basic_dir(job_entry_file):
    job_dir = os.path.split(job_entry_file)[0]
    job_dir_name = os.path.basename(job_dir)
    group_dir = os.path.split(job_dir)[0]
    group_dir_name = os.path.basename(group_dir)
    pid = job_dir_name
    return group_dir_name, job_dir_name, pid


def get_prom_user_password():
    # prometheus鉴权获取用户名密码
    import base64
    from app.config.database.db_nacos_conf import db_nacos_conf_dic
    tenant = db_nacos_conf_dic['prom']['tenant']
    data_id = db_nacos_conf_dic['prom']['data_id']
    group = db_nacos_conf_dic['prom']['group']
    prom_conf: dict = Nacos().get_nacos_configs(tenant = tenant, data_id = data_id, group = group)

    user = prom_conf['user']
    prom_pass = prom_conf['pass']
    password = base64.b64decode(prom_pass).decode('utf-8')
    return user, password
