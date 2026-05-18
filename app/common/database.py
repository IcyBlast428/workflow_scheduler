# -*- coding: utf-8 -*-
"""公共数据库兼容入口。

历史任务大量使用 `from app.common.database import NewDB`，因此这个文件继续保留。
新实现已拆到 `app.common.db`：`NewDB/get_db` 面向非高斯业务库，平台本体高斯库
仍然由 `app.bootstrap.database.GaussDB` 维护。
"""

from app.bootstrap.database import GaussDB
from app.common.db import NewDB, get_db

__all__ = ['GaussDB', 'NewDB', 'get_db']
