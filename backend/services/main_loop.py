"""Capture FastAPI's main event loop so background dispatch from threadpool
tool functions (Smith's ReAct loop calls sync tools in a threadpool) can
schedule coroutines onto the loop that owns the app's asyncpg pool.

Without this, tools that do `asyncio.run(_run())` spin a fresh loop; the
asyncpg pool bound to the FastAPI loop then trips
    RuntimeError: got Future attached to a different loop
on the first DB call. `asyncio.run_coroutine_threadsafe(coro, main_loop)`
sidesteps that entirely.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Optional

logger = logging.getLogger(__name__)

_MAIN_LOOP: Optional[asyncio.AbstractEventLoop] = None


def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _MAIN_LOOP
    _MAIN_LOOP = loop


def get_main_loop() -> Optional[asyncio.AbstractEventLoop]:
    return _MAIN_LOOP


def dispatch_background(coro: Awaitable[None]) -> bool:
    """Schedule `coro` on the main loop. Returns True on success, False if
    the loop wasn't captured (in which case the caller should fall back
    or log). Never blocks the caller.
    """
    loop = _MAIN_LOOP
    if loop is None or loop.is_closed():
        logger.warning("dispatch_background: main loop not captured; dropping coroutine")
        return False
    asyncio.run_coroutine_threadsafe(coro, loop)
    return True
