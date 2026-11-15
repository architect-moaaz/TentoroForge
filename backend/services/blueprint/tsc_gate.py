"""How many TypeScript checks may run at the same moment.

A build checks every page's code with its own ``tsc`` process, and the build's workers start them all together. On a laptop that is
fine; on a small server ten of them at once (150-360 MB each) use up the memory, the machine starts swapping, every check runs far past
its time limit, and the page is retried, which makes it worse.

``FORGE_TSC_PARALLEL`` sets the limit. Unset or 0 means no limit (the previous behaviour). The wait for a free place happens BEFORE the
check starts, so a check's time limit only counts the time it is actually running.
"""
from __future__ import annotations

import os
import threading
from contextlib import contextmanager


def _limit() -> int:
    try:
        return max(0, int(os.environ.get("FORGE_TSC_PARALLEL", "0")))
    except ValueError:
        return 0


_LIMIT = _limit()
_SLOTS = threading.BoundedSemaphore(_LIMIT) if _LIMIT else None


@contextmanager
def tsc_slot():
    """Hold one place while a TypeScript check runs (a no-op when no limit is set)."""
    if _SLOTS is None:
        yield
        return
    with _SLOTS:
        yield
