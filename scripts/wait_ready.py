"""Bounded systemd startup check; validates readiness, not just an HTTP response."""
import argparse
import json
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener


def wait(url, timeout=90, interval=1):
    parsed = urlsplit(url)
    if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1') or parsed.username or parsed.password:
        raise ValueError('Readiness must use a loopback HTTP endpoint without credentials')
    deadline = time.monotonic() + timeout
    opener = build_opener(ProxyHandler({}))
    while time.monotonic() < deadline:
        try:
            with opener.open(url, timeout=min(5, max(.1, deadline - time.monotonic()))) as response:
                data = json.loads(response.read(65537))
                if response.status == 200 and data.get('data', {}).get('ready') is True:
                    print('Workflow Scheduler is ready', flush=True)
                    return True
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, AttributeError):
            pass
        time.sleep(min(interval, max(0, deadline - time.monotonic())))
    print('Readiness timed out; inspect the service journal and database connectivity.', file=sys.stderr)
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--timeout', type=float, default=90)
    arguments = parser.parse_args()
    if not 0 < arguments.timeout <= 600:
        parser.error('timeout must be between 0 and 600 seconds')
    return 0 if wait(arguments.url, arguments.timeout) else 1


if __name__ == '__main__':
    raise SystemExit(main())
