# -*- coding: utf-8 -*-
"""Task-facing database API; explicit access lazily loads platform drivers."""

from app.common.db import NewDB, get_db

__all__ = ['GaussDB', 'NewDB', 'get_db']  # noqa: F822 - resolved by __getattr__


def __getattr__(name):
    # Business tasks need neither the platform driver nor its Nacos client.
    if name == 'GaussDB':
        from app.bootstrap.database import GaussDB
        return GaussDB
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
