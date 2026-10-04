"""One business time basis, including legacy timestamp-without-zone columns.

Existing timestamps retain their meaning; no historical data is rewritten.
"""
import datetime as dt
import os
import time
from pytz import timezone

TIMEZONE_NAME = 'Asia/Shanghai'
BUSINESS_TZ = timezone(TIMEZONE_NAME)
# Libraries producing local timestamps share the same basis on Unix.
os.environ['TZ'] = TIMEZONE_NAME
if hasattr(time, 'tzset'):
    time.tzset()


def business_now():
    return dt.datetime.now(BUSINESS_TZ).replace(tzinfo=None)


def business_time(value):
    """Aware instants become business wall time; legacy naive values stay intact."""
    if isinstance(value, str):
        value = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    return value.astimezone(BUSINESS_TZ).replace(tzinfo=None) if value.tzinfo else value


def instant_iso(value):
    value = business_time(value)
    return BUSINESS_TZ.localize(value).isoformat(timespec='seconds')
