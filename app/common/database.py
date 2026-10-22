# -*- coding: utf-8 -*-
"""公共数据库兼容入口。

历史任务大量使用 `from app.common.database import NewDB`，因此这个文件继续保留。
新实现已拆到 `app.common.db`：NewDB/get_db 按标识统一访问业务数据库。
GaussDB 保留为历史平台内部接口；任务应使用独立的业务连接标识。
"""

from app.bootstrap.database import GaussDB
from app.common.db import NewDB, get_db

__all__ = ['GaussDB', 'NewDB', 'get_db']
