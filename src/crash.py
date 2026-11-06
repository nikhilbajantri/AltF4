"""Crash points: named injection points for deterministic crash testing.

Owner: Nikhil

KVDB_CRASH="name:n" (read once at import) SIGKILLs this process on the nth hit
of point `name`. Unset means every point is a no-op.
"""

import os
import random
import signal


def _parse(spec):
    if not spec:
        return None, 0
    name, _, n = spec.partition(":")
    return name, int(n or 1)


_NAME, _N = _parse(os.environ.get("KVDB_CRASH"))
_hits = 0


def _hit(name):
    global _hits
    if name != _NAME:
        return False
    _hits += 1
    return _hits == _N


def kill():
    os.kill(os.getpid(), signal.SIGKILL)


def point(name):
    if _hit(name):
        kill()


def torn_write_prefix(frame):
    """On the nth "torn_write" hit, return a 1..len-1 byte prefix to write before kill()."""
    if _hit("torn_write"):
        return frame[:random.randint(1, len(frame) - 1)]
    return None
