# -*- coding: utf-8 -*-
"""公共数据库连接工厂。

`app.bootstrap.database` 只服务 WFS 平台本体高斯库；这里服务 jobs 任务和公共
工具函数需要访问的业务数据库。当前平台主环境已内置 MySQL 适配器，其它数据库
保留适配器位置，使用时由对应任务环境安装驱动。
"""

from app.common.db.factory import NewDB, get_db

__all__ = ['NewDB', 'get_db']
