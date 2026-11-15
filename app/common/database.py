# -*- coding: utf-8 -*-
"""Tasks use NewDB for all business database families.

The legacy GaussDB attribute remains for old frozen releases/importers only;
new task publications reject direct platform/driver access with migration help.
"""

from app.common.db import NewDB, get_db

__all__ = ['GaussDB', 'NewDB', 'get_db']  # noqa: F822 - resolved by __getattr__


def __getattr__(name):
    # Business tasks need neither the platform driver nor its Nacos client.
    if name == 'GaussDB':
        from app.bootstrap.database import GaussDB
        return GaussDB
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
