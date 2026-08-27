import asyncio

import pytest

from services.render_service.browser_pool import BrowserPool


@pytest.mark.asyncio
async def test_pool_starts_and_serves_a_context():
    pool = BrowserPool()
    await pool.start()
    try:
        async with pool.acquire() as ctx:
            page = await ctx.new_page()
            await page.set_content("<h1>hello</h1>")
            assert await page.title() == ""  # no <title> in markup
            text = await page.text_content("h1")
            assert text == "hello"
    finally:
        await pool.stop()


@pytest.mark.asyncio
async def test_pool_serves_concurrent_acquires():
    pool = BrowserPool()
    await pool.start()
    try:
        async def fetch_text() -> str:
            async with pool.acquire() as ctx:
                page = await ctx.new_page()
                await page.set_content("<p>concurrent</p>")
                return await page.text_content("p") or ""
        results = await asyncio.gather(*[fetch_text() for _ in range(3)])
        assert results == ["concurrent"] * 3
    finally:
        await pool.stop()
