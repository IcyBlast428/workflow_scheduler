"""One status vocabulary for history, counters, diagnostics and the matrix."""
SKIPPED = -10001
MISSED = -10002
NON_FAILURE = (0, -15, -1, SKIPPED, MISSED)
FAILURE_SQL = 'state IS NOT NULL AND state NOT IN (0,-15,-1,-10001,-10002)'


def state_status(state):
    if state is None:
        return 'unknown'
    return {0: 'success', -9: 'timed_out', -15: 'cancelled', -1: 'interrupted',
            SKIPPED: 'skipped', MISSED: 'missed'}.get(int(state), 'failed')


def is_failure(state):
    return state is not None and int(state) not in NON_FAILURE
