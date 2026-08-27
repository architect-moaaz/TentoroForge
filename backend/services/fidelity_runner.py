"""Runs fidelity scoring over generated pages.

Takes screenshots of each page via Playwright (against the running scaffold
at scaffold_base_url), scores each against the reference for its
(domain, page_type), yields {page, page_type, score} dicts. Pages without
references yield {page, page_type, score: None, reason: "no_reference"}.

Errors per-page are swallowed and surfaced as {error: ...} entries so a
single broken page can't kill the scoring loop. Scoring is advisory and
MUST NOT raise into the caller.
"""
from __future__ import annotations
from pathlib import Path
from typing import AsyncIterator
import asyncio
import logging
import tempfile

from services.fidelity_mapper import fidelity_page_type_for
from services.fidelity_scorer import score_against_reference

logger = logging.getLogger(__name__)


async def run_fidelity_scoring(
    *,
    output_dir: str,
    project_id: str,
    plan: dict,
    scaffold_base_url: str = "http://localhost:6503",
    viewport: tuple[int, int] = (1280, 800),
    page_load_timeout_ms: int = 15_000,
) -> AsyncIterator[dict]:
    """Yield one event dict per page. Caller wraps in SSE."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        yield {"type": "skip", "reason": "playwright_unavailable"}
        return

    # The planner emits industry prose ("E-Commerce & Retail"); the
    # reference index keys on design families. Without this every page
    # skips with "no reference" and scoring is a no-op.
    from services.fidelity_scorer import normalize_domain
    domain = normalize_domain((plan or {}).get("domain"))
    pages = (plan or {}).get("pages", [])

    if not pages:
        yield {"type": "skip", "reason": "no_pages"}
        return

    async with async_playwright() as pw:
        try:
            browser = await pw.chromium.launch(headless=True)
        except Exception as e:
            yield {"type": "skip", "reason": f"browser_launch_failed: {e}"}
            return
        try:
            context = await browser.new_context(
                viewport={"width": viewport[0], "height": viewport[1]}
            )
            page = await context.new_page()

            for p in pages:
                route = p.get("route") or p.get("path") or ""
                role = p.get("role") or p.get("description") or ""
                page_type = fidelity_page_type_for(route, role)

                if page_type is None:
                    yield {
                        "type": "skip",
                        "page": route,
                        "reason": "no_fidelity_page_type",
                    }
                    continue

                slug = route.lstrip("/").replace("/", "-") or "home"
                url = f"{scaffold_base_url}/p/{project_id}/{slug}"

                screenshot_path = Path(tempfile.gettempdir()) / f"fidelity-{project_id}-{slug}.png"
                try:
                    await page.goto(url, wait_until="networkidle", timeout=page_load_timeout_ms)
                    await page.screenshot(path=str(screenshot_path), full_page=True)
                except Exception as e:
                    yield {
                        "type": "error",
                        "page": route,
                        "page_type": page_type,
                        "error": f"navigation_failed: {e}",
                    }
                    continue

                try:
                    # Run the (blocking) scorer in a thread so we don't stall the loop
                    score = await asyncio.to_thread(
                        score_against_reference,
                        screenshot_path, domain, page_type, route,
                    )
                except Exception as e:
                    yield {
                        "type": "error",
                        "page": route,
                        "page_type": page_type,
                        "error": f"scoring_failed: {e}",
                    }
                    continue

                if score is None:
                    yield {
                        "type": "skip",
                        "page": route,
                        "page_type": page_type,
                        "reason": "no_reference_or_malformed_response",
                    }
                else:
                    yield {
                        "type": "score",
                        "page": route,
                        "page_type": page_type,
                        "domain": domain,
                        "score_0_to_10": score.score_0_to_10,
                        "color_match_score": score.color_match_score,
                        "layout_score": score.layout_score,
                        "density_score": score.density_score,
                        "polish_score": score.polish_score,
                        "qualitative_notes": score.qualitative_notes,
                        # Routable defects for this page, already filtered to
                        # the known taxonomy. The caller collects them across
                        # pages and repairs once — the passes are app-wide.
                        "findings": score.findings,
                    }
        finally:
            try:
                await browser.close()
            except Exception:
                pass
