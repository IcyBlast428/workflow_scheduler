# setup logging
import logging
import os
import socket
from logging import Formatter
from logging.handlers import RotatingFileHandler

from app.bootstrap.global_vars import ROOT_LOG_DIR
from app.bootstrap.helpers import load_config


def get_local_ip():
    hostname = socket.gethostname()
    ip_addr = socket.gethostbyname(hostname)
    return ip_addr


def init_log():
    if not os.path.exists(ROOT_LOG_DIR):
        os.makedirs(ROOT_LOG_DIR)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    rfh = RotatingFileHandler(os.path.join(ROOT_LOG_DIR, 'app.log'),
                            maxBytes=1024 * 10,
                            backupCount=5, encoding='utf8')

    app_id = load_config('basic', 'app_id')
    formatter = Formatter(
        '[{0}] [{1}] [%(asctime)s] [%(name)s] [%(levelname)s] %(message)s  %(module)s:%(lineno)d'.format(app_id,
                                                                                                        get_local_ip())
    )
    rfh.setFormatter(formatter)
    rfh.setLevel(logging.INFO)
    root_logger.addHandler(rfh)
