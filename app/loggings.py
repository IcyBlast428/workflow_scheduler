# setup logging
import logging
import socket
from logging import Formatter

from app.bootstrap.helpers import load_config


def get_local_ip():
    hostname = socket.gethostname()
    ip_addr = socket.gethostbyname(hostname)
    return ip_addr


def init_log():
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    if any(getattr(handler, '_wfs_handler', False) for handler in root_logger.handlers):
        return
    # Gunicorn/systemd capture stderr; avoid rotating one shared file in several workers.
    rfh = logging.StreamHandler()
    rfh._wfs_handler = True

    app_id = load_config('basic', 'app_id')
    formatter = Formatter(
        '[{0}] [{1}] [%(asctime)s] [%(name)s] [%(levelname)s] %(message)s  %(module)s:%(lineno)d'.format(app_id,
                                                                                                        get_local_ip())
    )
    rfh.setFormatter(formatter)
    rfh.setLevel(logging.INFO)
    root_logger.addHandler(rfh)
