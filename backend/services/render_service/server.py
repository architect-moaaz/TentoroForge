"""FastAPI app for the render-service. POST /render → PNG + a11y tree."""
from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .browser_pool import BrowserPool
from .cache import RenderCache


VIEWPORT_DIMENSIONS = {
    "mobile":  (375,  667),
    "tablet":  (768,  1024),
    "desktop": (1280, 800),
}


class RenderRequest(BaseModel):
    projectId: str
    pageRoute: str
    viewport: Literal["mobile", "tablet", "desktop"] = "desktop"
    waitFor: Literal["networkidle", "load", "domcontentloaded"] = "networkidle"
    captureMode: Literal["fullPage", "aboveFold"] = "fullPage"
    fixturesProfile: Literal["auto", "minimal", "rich"] = "auto"


class RenderResponse(BaseModel):
    pngBase64: str
    pngBytes: int
    htmlSnapshot: str
    accessibilityTree: str
    renderTimeMs: int
    consoleWarnings: list[str] = Field(default_factory=list)
    networkFailures: list[str] = Field(default_factory=list)


def build_app(scaffold_url: str = "http://localhost:6503", cache_root: Path | str = "/tmp/render-cache") -> FastAPI:
    app = FastAPI(title="render-service")
    pool = BrowserPool()
    cache = RenderCache(root=cache_root)

    @app.on_event("startup")
    async def _startup() -> None:
        await pool.start()

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        await pool.stop()

    @app.get("/health")
    async def _health() -> dict[str, str]:
        return {"status": "ok"}

    @app.delete("/cache")
    async def _clear_cache() -> dict[str, str]:
        cache.clear()
        return {"status": "cleared"}

    @app.post("/render")
    async def _render(req: RenderRequest) -> RenderResponse:
        cache_key = RenderCache.make_key(req.model_dump())
        cached = cache.get(cache_key)
        if cached is not None:
            return RenderResponse(
                pngBase64=base64.b64encode(cached).decode("ascii"),
                pngBytes=len(cached), htmlSnapshot="", accessibilityTree="",
                renderTimeMs=0,
            )

        w, h = VIEWPORT_DIMENSIONS[req.viewport]
        target_url = f"{scaffold_url}/p/{req.projectId}{req.pageRoute}?preview=true"
        warnings: list[str] = []
        failures: list[str] = []
        start = asyncio.get_event_loop().time()
        try:
            async with pool.acquire(viewport_w=w, viewport_h=h) as ctx:
                page = await ctx.new_page()
                page.on("console", lambda msg: warnings.append(f"{msg.type}: {msg.text}") if msg.type in ("warning", "error") else None)
                page.on("requestfailed", lambda r: failures.append(f"{r.method} {r.url}: {r.failure}"))
                try:
                    await page.goto(target_url, wait_until=req.waitFor, timeout=15_000)
                except Exception as e:
                    raise HTTPException(status_code=422, detail={"error": f"navigation failed: {e}"})
                png = await page.screenshot(full_page=(req.captureMode == "fullPage"))
                html = await page.content()
                a11y_handle = await page.query_selector("#__a11y_tree__")
                a11y_tree: str = ""
                if a11y_handle is not None:
                    txt = await a11y_handle.text_content() or ""
                    try:
                        import json as _json
                        parsed = _json.loads(txt)
                        a11y_tree = parsed if isinstance(parsed, str) else txt
                    except Exception:
                        a11y_tree = txt
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=422, detail={"error": f"render failed: {e}"})

        duration_ms = int((asyncio.get_event_loop().time() - start) * 1000)
        cache.set(cache_key, png)
        return RenderResponse(
            pngBase64=base64.b64encode(png).decode("ascii"),
            pngBytes=len(png),
            htmlSnapshot=html[:200_000],
            accessibilityTree=a11y_tree[:50_000],
            renderTimeMs=duration_ms,
            consoleWarnings=warnings[:50],
            networkFailures=failures[:50],
        )

    return app
