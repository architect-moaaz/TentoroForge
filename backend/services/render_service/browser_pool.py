"""Long-lived Playwright browser instance + per-acquire isolated contexts.

Why a pool: Playwright's Chromium boot is ~800ms — too slow to do per-render.
A single warm browser process serves many renders; each render gets its own
context (cookies, storage, cache) so they're isolated. Contexts are closed on
release."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

from playwright.async_api import Browser, BrowserContext, async_playwright


class BrowserPool:
    """Holds one warm Chromium instance; vends BrowserContext per acquire."""

    def __init__(self, headless: bool = True):
        self._headless = headless
        self._browser: Browser | None = None
        self._playwright = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        async with self._lock:
            if self._browser is not None:
                return
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=self._headless)

    async def stop(self) -> None:
        async with self._lock:
            if self._browser is not None:
                await self._browser.close()
                self._browser = None
            if self._playwright is not None:
                await self._playwright.stop()
                self._playwright = None

    @asynccontextmanager
    async def acquire(self, viewport_w: int = 1280, viewport_h: int = 800) -> AsyncIterator[BrowserContext]:
        if self._browser is None:
            raise RuntimeError("BrowserPool not started — call start() first")
        ctx = await self._browser.new_context(viewport={"width": viewport_w, "height": viewport_h})
        try:
            yield ctx
        finally:
            await ctx.close()
