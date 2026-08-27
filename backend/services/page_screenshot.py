"""Page screenshot capture — Sprint 8 of Forge Great Again (capture side).

Sprint 8's page critic accepts optional screenshot bytes so it can score
the rendered page as a user would see it, not just the schema. This
module provides the CAPTURE side of that seam.

Slice-1 status
--------------
This module ships as an interface + graceful stub. The real capture
pipeline needs:
  1. A rendering endpoint that turns a schema + design_spec into an
     HTML preview (Forge already has this — render-service on :6502).
  2. A Playwright headless browser that hits that URL and screenshots
     (Forge already has forge-verify on :6600).

Wiring those together is a follow-up slice. For now:
  · The function returns ``None`` when capture isn't available.
  · The page critic gracefully falls back to text-only when bytes
    are None.

This means Sprint 8's vision seam is fully wired and testable (via
injected bytes) without depending on capture infrastructure. The
capture wiring is one PR away.

Environment
-----------
  FORGE_PAGE_SCREENSHOT_URL — base URL of a render preview service.
                              When set, this module POSTs the schema
                              and requests a screenshot back.
  FORGE_PAGE_SCREENSHOT_TIMEOUT_S — HTTP timeout (default 15).

Return contract
---------------
capture_page_screenshot(...) -> bytes | None
  bytes: PNG image
  None:  capture unavailable, disabled, or failed (all silent)
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_URL_ENV = "FORGE_PAGE_SCREENSHOT_URL"
_TIMEOUT_ENV = "FORGE_PAGE_SCREENSHOT_TIMEOUT_S"
_DEFAULT_TIMEOUT_S = 15.0


def screenshot_available() -> bool:
    """True when a screenshot service URL is configured. Callers can
    short-circuit rather than paying the round-trip when disabled."""
    return bool(os.getenv(_URL_ENV, "").strip())


def capture_page_screenshot(
    output_dir: str,
    slug: str,
    route: str,
) -> Optional[bytes]:
    """Capture a PNG of the rendered page. Returns ``None`` when the
    capture service isn't configured or the request fails.

    Args:
        output_dir: Absolute path of the generated app (for the render
            service to load design-spec and schemas).
        slug: Schema-registry slug (matches the file name under
            ``src/schemas/<slug>.json``).
        route: URL path the page serves (e.g. ``/dashboard``).

    Returns:
        PNG bytes on success; None on any failure. Never raises.
    """
    url = os.getenv(_URL_ENV, "").strip()
    if not url:
        return None

    try:
        timeout = float(os.getenv(_TIMEOUT_ENV, str(_DEFAULT_TIMEOUT_S)))
    except (TypeError, ValueError):
        timeout = _DEFAULT_TIMEOUT_S

    try:
        import httpx  # imported here so tests without httpx still load the module
    except Exception:  # noqa: BLE001
        logger.debug("[page-screenshot] httpx unavailable — capture skipped")
        return None

    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(
                url.rstrip("/") + "/screenshot",
                json={
                    "output_dir": output_dir,
                    "slug": slug,
                    "route": route,
                },
            )
        if resp.status_code != 200:
            logger.debug(
                "[page-screenshot] %s returned %s for %s",
                url, resp.status_code, slug,
            )
            return None
        body = resp.content
        if not body:
            return None
        # Cheap sanity: PNG signature is 8 bytes 89 50 4E 47 0D 0A 1A 0A.
        if not body.startswith(b"\x89PNG\r\n\x1a\n"):
            logger.debug(
                "[page-screenshot] %s returned non-PNG payload for %s",
                url, slug,
            )
            return None
        return body
    except Exception:  # noqa: BLE001 — screenshot is best-effort
        logger.debug(
            "[page-screenshot] capture failed for %s (silent)", slug,
            exc_info=True,
        )
        return None


__all__ = [
    "screenshot_available",
    "capture_page_screenshot",
]
