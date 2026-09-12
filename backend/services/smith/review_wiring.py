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
import base64
import logging
import os
from pathlib import Path
from typing import Any, Callable, Mapping

logger = logging.getLogger(__name__)

#: The warm Playwright sidecar that screenshots a URL headless (POST /screenshot).
_VERIFY_URL = "FORGE_VERIFY_URL"
#: Where the generated apps are served, with the /p base path render-scaffold
#: mounts. A page's URL is ``<base>/<short_id><route>``.
_PREVIEW_BASE = "FORGE_PREVIEW_BASE_URL"


def _preview_url(output_dir: str, route: str, doc: Mapping[str, Any]) -> str:
    base = os.getenv(_PREVIEW_BASE, "http://localhost:6503/p").rstrip("/")
    short_id = str((doc.get("application") or {}).get("id")
                   or Path(output_dir).name)
    r = route if route.startswith("/") else "/" + route
    return f"{base}/{short_id}{r}"


def _screenshot(url: str) -> bytes | None:
    """PNG of ``url`` from the Playwright sidecar, or ``None`` on any failure."""
    verify = os.getenv(_VERIFY_URL, "http://localhost:6600").rstrip("/")
    try:
        import httpx
    except Exception:  # noqa: BLE001
        return None
    try:
        resp = httpx.post(f"{verify}/screenshot",
                          json={"url": url, "fullPage": True,
                                "width": 1440, "height": 900, "waitMs": 600},
                          timeout=45.0)
    except Exception as exc:  # noqa: BLE001
        logger.info("[review] screenshot request failed for %s: %s", url, exc)
        return None
    if resp.status_code != 200 or resp.content[:8] != b"\x89PNG\r\n\x1a\n":
        logger.info("[review] screenshot %s -> %s", url, resp.status_code)
        return None
    return resp.content


def _data_uri(png: bytes) -> str:
    return "data:image/png;base64," + base64.standard_b64encode(png).decode()


def _domain_identity(doc: Mapping[str, Any]) -> dict:
    """What this app IS, for the critic to judge the render against — not taste,
    but 'does this page look like THIS application and do what it said'. The
    domain (entities + their real fields), the purpose, and the requirements the
    pages are meant to satisfy. Kept compact; the critic caps it anyway."""
    app = doc.get("application") or {}
    product = doc.get("product") or {}
    entities = []
    for e in ((doc.get("data") or {}).get("entities") or []):
        if not isinstance(e, dict):
            continue
        fields = [str(f.get("name")) for f in (e.get("fields") or e.get("columns") or [])
                  if isinstance(f, dict) and f.get("name")]
        entities.append({"entity": str(e.get("name") or e.get("id") or ""),
                         "fields": fields[:14]})
    reqs = []
    for r in (doc.get("requirements") or []):
        if not isinstance(r, dict):
            continue
        t = r.get("text") or r.get("statement") or r.get("title") or r.get("description")
        if t:
            reqs.append(str(t)[:160])
    return {
        "app": str(app.get("name") or product.get("name") or ""),
        "purpose": str(product.get("description") or app.get("description")
                       or product.get("summary") or "")[:500],
        "entities": entities[:10],
        "requirements": reqs[:14],
    }


import json

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
    """``[{route, png}]`` for the pages the sidecar could screenshot. Empty when
    nothing rendered — the loop then degrades to a clean no-op. Dynamic routes
    (``/x/[id]``) are skipped: they need a concrete id to serve."""
    shots: list[dict] = []
    for p in doc.get("pages") or []:
        if not isinstance(p, dict):
            continue
        route = str(p.get("route") or "").strip()
        if not route or "[" in route:
            continue
        png = _screenshot(_preview_url(output_dir, route, doc))
        if png:
            shots.append({"route": route, "png": png})
    return shots


def make_critique(
    output_dir: str,
    read_doc: Callable[[], Mapping[str, Any]],
    emit: Callable[[str, dict], None] | None = None,
) -> Callable[[], dict | None]:
    """A ``critique()`` for the loop: screenshot the built pages, show them in the
    review panel, run the vision critic, show its analysis, and return the report
    — or ``None`` when nothing could be rendered/reviewed.

    ``emit`` streams ``review`` events the panel renders: the screenshots as
    they are taken, then the findings per page. The window is the user watching
    Smith look at what it built.
    """
    def critique() -> dict | None:
        doc = read_doc()
        shots = _capture_pages(output_dir, doc)
        if not shots:
            return None
        if emit is not None:
            emit("review", {"phase": "shots", "pages": [
                {"route": s["route"], "image": _data_uri(s["png"])}
                for s in shots]})
        try:
            from services.visual_qa_critic import critique_images
            findings = _run_async(critique_images(
                shots, identity=_domain_identity(doc)))
        except Exception as exc:  # noqa: BLE001 — a failed review is a skipped one
            logger.warning("[review] visual critic failed: %s", exc)
            if emit is not None:
                emit("review", {"phase": "analysis", "findings": []})
            return None
        if emit is not None:
            emit("review", {"phase": "analysis", "findings": findings})
        return {"pages_reviewed": [s["route"] for s in shots],
                "findings": findings}
    return critique


__all__ = [
    "invalidate_for_recompose", "write_review_briefs", "clear_review_briefs",
    "make_critique",
]
