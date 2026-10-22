# -*- coding: utf-8 -*-
"""公共数据库连接工厂。

NewDB 是任务和公共工具的统一业务数据库入口，按连接标识选择数据库类型。
驱动适配、连接池及连接生命周期由本包管理；平台内部数据库由 bootstrap 维护。
"""

from app.common.db.factory import NewDB, get_db

__all__ = ['NewDB', 'get_db']
