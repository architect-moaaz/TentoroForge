"""Wire Smith's review loop to the real critique and the real re-compose.

``review_loop.run_review_loop`` owns the control flow; this owns the two seams
it drives:

* **critique** — screenshot the built pages and run the vision critic over them,
  returning a report or ``None`` when the app cannot be rendered (no screenshot
  service). Never raises: a review that cannot run is a skipped review, not a
  failed build.
* **re-compose + rebuild** — attach each page's review brief to its contract,
  drop that page's composed layout so the resume re-composes exactly it (see
  ``orchestrator.pending_subjects``), and re-run the build. The composer reads
  the brief through ``a2ui_authority`` and fixes what the review saw.

The doc surgery is split out (``invalidate_for_recompose`` /
``clear_review_briefs``) so it is unit-tested without a build.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Mapping

logger = logging.getLogger(__name__)


import json
from pathlib import Path

#: Where the render loop leaves its per-page verdict for the composer to read on
#: the re-compose. Kept OUT of the Blueprint — a between-builds note needs no
#: declared schema field (and the schema would refuse an undeclared one).
_BRIEFS_FILE = ("contracts", "review-briefs.json")


def invalidate_for_recompose(doc: dict, briefs: Mapping[str, str]) -> list[str]:
    """Drop the flagged pages' composed layouts so a resume re-composes exactly
    them (see ``orchestrator.pending_subjects``). In place; returns the page ids
    invalidated (a brief naming no live page, or empty, does nothing). The brief
    text is written to the transient file separately by ``write_review_briefs``.
    """
    live = {str(p.get("id")) for p in doc.get("pages") or []
            if isinstance(p, dict) and p.get("id")}
    hit = [str(pid) for pid, brief in briefs.items()
           if str(pid) in live and str(brief or "").strip()]
    if hit:
        drop = set(hit)
        doc["pageLayouts"] = [l for l in (doc.get("pageLayouts") or [])
                              if str((l or {}).get("page")) not in drop]
    return hit


def write_review_briefs(output_dir: str, briefs: Mapping[str, str]) -> None:
    """Write ``{page_id: brief}`` to the transient file the composer reads."""
    path = Path(output_dir).joinpath(*_BRIEFS_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(briefs), indent=2), encoding="utf-8")


def clear_review_briefs(output_dir: str) -> None:
    """Remove the transient file once the re-compose has consumed it, so a note
    does not re-apply on a later, unrelated build. Best-effort."""
    try:
        Path(output_dir).joinpath(*_BRIEFS_FILE).unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass


def _run_async(coro) -> Any:
    """Run an async critic from Smith's synchronous build path — on a private
    loop, because the build already occupies the request's loop thread."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _slug_for(route: str, doc: Mapping[str, Any]) -> str:
    """The schema-registry slug the render service loads for a route. The
    projection names schemas by the route's slug; a page carries it when known,
    else it is derived the same way the projection derives it."""
    for p in doc.get("pages") or []:
        if isinstance(p, dict) and str(p.get("route") or "") == route:
            s = p.get("slug") or p.get("schemaSlug")
            if s:
                return str(s)
    seg = [s for s in route.strip("/").split("/") if s and not s.startswith("[")]
    return "-".join(seg) or "index"


def _capture_pages(output_dir: str, doc: Mapping[str, Any]) -> list[dict]:
    """``[{route, png}]`` for the pages that could be screenshotted. Empty when
    no screenshot service is configured — the loop then degrades to a no-op."""
    try:
        from services.page_screenshot import (
            capture_page_screenshot, screenshot_available,
        )
    except Exception:  # noqa: BLE001
        return []
    if not screenshot_available():
        return []
    shots: list[dict] = []
    for p in doc.get("pages") or []:
        if not isinstance(p, dict):
            continue
        route = str(p.get("route") or "").strip()
        if not route or "[" in route:      # dynamic routes need a concrete id
            continue
        try:
            png = capture_page_screenshot(output_dir, _slug_for(route, doc), route)
        except Exception as exc:  # noqa: BLE001 — one bad shot is not the review
            logger.info("[review] screenshot failed for %s: %s", route, exc)
            png = None
        if png:
            shots.append({"route": route, "png": png})
    return shots


def make_critique(output_dir: str, read_doc: Callable[[], Mapping[str, Any]]
                  ) -> Callable[[], dict | None]:
    """A ``critique()`` for the loop: screenshot + vision critic → report, or
    ``None`` when nothing could be rendered/reviewed."""
    def critique() -> dict | None:
        shots = _capture_pages(output_dir, read_doc())
        if not shots:
            return None
        try:
            from services.visual_qa_critic import critique_images
            findings = _run_async(critique_images(shots, identity=None))
        except Exception as exc:  # noqa: BLE001 — a failed review is a skipped one
            logger.warning("[review] visual critic failed: %s", exc)
            return None
        return {"pages_reviewed": [s["route"] for s in shots],
                "findings": findings}
    return critique


__all__ = [
    "invalidate_for_recompose", "write_review_briefs", "clear_review_briefs",
    "make_critique",
]
