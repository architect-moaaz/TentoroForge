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
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping

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
                                "width": 1440, "height": 900, "waitMs": 1800},
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


def layouts_of(doc: Mapping[str, Any], page_ids: Iterable[str]) -> dict[str, dict]:
    """``{page_id: layout}`` for the pages about to be invalidated — the
    pre-image a refused re-compose is restored from."""
    want = {str(p) for p in page_ids}
    return {str(l.get("page")): l for l in (doc.get("pageLayouts") or [])
            if isinstance(l, dict) and str(l.get("page")) in want}


def restore_refused_layouts(doc: dict, before: Mapping[str, dict],
                            refused: Iterable[str]) -> list[str]:
    """Put the previous layout back for every page whose re-compose was
    refused. ``invalidate_for_recompose`` drops a layout so the resume
    re-composes it; when the composer then produces nothing the contract
    accepts, the page is left with NO tree — a route that cannot render, in
    the source of truth, from a verify meant to fix it. The old tree was at
    least a page. In place; returns the page ids restored."""
    have = {str(l.get("page")) for l in (doc.get("pageLayouts") or [])
            if isinstance(l, dict)}
    put: list[str] = []
    for pid in refused:
        pid = str(pid)
        if pid in before and pid not in have:
            doc.setdefault("pageLayouts", []).append(dict(before[pid]))
            put.append(pid)
    return put


@dataclass
class Rebuilt:
    """What a re-compose round could not bring round. ``refused``: the
    contract accepted no tree (the page keeps its previous one).
    ``unrepaired``: a tree landed, but the observer spent its rounds and the
    page still fails a requirement — the composer's best answer stands.
    Neither is sent round again: the next review round would pay the same
    chain of compose and verdict for the same verdict."""
    refused: dict[str, str] = field(default_factory=dict)
    unrepaired: dict[str, str] = field(default_factory=dict)


def unrepaired_pages(built: Mapping[str, Any] | None) -> dict[str, str]:
    """``{page_id: why}`` for the page_layouts subjects the observer flagged
    unrepaired in a build — read off the report, the same way the panel
    reads it."""
    out: dict[str, str] = {}
    for f in ((built or {}).get("report") or {}).get("unrepaired") or []:
        node = str((f or {}).get("node") or "")
        if node.startswith("page_layouts:"):
            out[node.split(":", 1)[1]] = str((f or {}).get("why") or "unrepaired")
    return out


def refused_pages(built: Mapping[str, Any] | None) -> dict[str, str]:
    """``{page_id: why}`` for the page_layouts subjects a build report says
    failed — what ``_run_dag`` returns, read the same way the panel reads it."""
    out: dict[str, str] = {}
    for f in ((built or {}).get("report") or {}).get("failed") or []:
        node = str((f or {}).get("node") or "")
        if node.startswith("page_layouts:"):
            out[node.split(":", 1)[1]] = str((f or {}).get("why") or "refused")
    return out


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


def _capture_pages(output_dir: str, doc: Mapping[str, Any],
                   routes: Iterable[str] | None = None) -> list[dict]:
    """``[{route, png}]`` for the pages the sidecar could screenshot. Empty when
    nothing rendered — the loop then degrades to a clean no-op. Dynamic routes
    (``/x/[id]``) are skipped: they need a concrete id to serve. ``routes``
    narrows the review to those pages — "verify only the current page"."""
    only = {str(r).rstrip("/") or "/" for r in routes} if routes else None
    shots: list[dict] = []
    for p in doc.get("pages") or []:
        if not isinstance(p, dict):
            continue
        route = str(p.get("route") or "").strip()
        if not route or "[" in route:
            continue
        if only is not None and (route.rstrip("/") or "/") not in only:
            continue
        png = _screenshot(_preview_url(output_dir, route, doc))
        if png:
            shots.append({"route": route, "png": png})
    return shots


def _functional_findings(output_dir: str, doc: Mapping[str, Any]) -> list[dict]:
    """Faults from driving the app's REAL controls — do the buttons, forms,
    lists and links actually work. forge-verify clicks them against the served
    app and reports what did nothing or errored. ``[]`` on any failure or when
    there is nothing to drive, so the visual review still stands on its own.

    Findings share the ``{route, kind, severity, note}`` shape of the visual
    ones, so the window shows them beside each page and the same bridge turns
    them into re-compose briefs — a control wired to the wrong action is a page
    the composer can fix.
    """
    try:
        from services.interaction_extractor import extract_interactions
        from services.forge_verify_client import ForgeVerifyClient
    except Exception:  # noqa: BLE001
        return []
    short_id = str((doc.get("application") or {}).get("id") or Path(output_dir).name)
    base = os.getenv(_PREVIEW_BASE, "http://localhost:6503/p").rstrip("/")
    base_url = f"{base}/{short_id}"
    try:
        interactions = extract_interactions(output_dir)
    except Exception as exc:  # noqa: BLE001
        logger.info("[review] interaction extract failed: %s", exc)
        return []
    if not interactions:
        return []

    async def _go() -> dict:
        async with ForgeVerifyClient() as c:
            if not await c.healthz():
                return {}
            rid = await c.run(short_id, "preview", base_url, list(interactions))
            return await c.poll_until_done(rid, timeout=240)

    try:
        report = _run_async(_go())
    except Exception as exc:  # noqa: BLE001 — a functional check is best-effort
        logger.warning("[review] functional check failed: %s", exc)
        return []

    out: list[dict] = []
    for f in ((report or {}).get("report") or report or {}).get("faults") or []:
        if not isinstance(f, dict) or f.get("passed") or f.get("flaky"):
            continue
        it = f.get("interaction") or {}
        route = str(it.get("route") or "").strip()
        if not route:
            continue
        label = str(it.get("label") or it.get("kind") or "control")
        ev = f.get("evidence") or {}
        reason = str(ev.get("reason") or ev.get("classification")
                     or ev.get("note") or "did nothing when used")
        out.append({"route": route, "kind": "dead_control", "severity": "error",
                    "note": f"{label} ({it.get('kind')}) — {reason}"[:400]})
    return out


def _contract_findings(doc: Mapping[str, Any],
                       routes: Iterable[str] | None = None) -> list[dict]:
    """The Blueprint's own verdict on each page — every control does what it
    says, every field collects what its column holds — in the critique's
    ``{route, kind, severity, note}`` shape.

    The review used to see only what it could screenshot. A dynamic route
    (``/x/[id]``) is never captured, so a fault the contract could see there
    was never sent round: the edit page's list field stayed a textarea while
    the create form beside it was re-composed with the right control. The
    contract needs no screenshot; what it flags is a page the composer can fix
    (and is held to — a re-composition that repeats the fault is refused, so
    this cannot spin). Advisory rules are not findings a composer can act on.
    """
    from services.blueprint.functional_completeness import ADVISORY_PAGE_RULES, page_findings
    only = {str(r).rstrip("/") or "/" for r in routes} if routes else None
    route_of = {str(p.get("id")): str(p.get("route") or "").strip()
                for p in doc.get("pages") or [] if isinstance(p, dict)}
    out: list[dict] = []
    for f in page_findings(dict(doc)):
        rule = str(f.get("rule") or "")
        route = route_of.get(str(f.get("page") or ""), "")
        if not rule or rule in ADVISORY_PAGE_RULES or not route:
            continue
        if only is not None and (route.rstrip("/") or "/") not in only:
            continue
        out.append({"route": route, "kind": rule, "severity": "error",
                    "note": str(f.get("detail") or "").strip()[:400]})
    return out


def make_critique(
    output_dir: str,
    read_doc: Callable[[], Mapping[str, Any]],
    emit: Callable[[str, dict], None] | None = None,
    routes: Iterable[str] | None = None,
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
        shots = _capture_pages(output_dir, doc, routes)
        # The contract's findings need no screenshot — they reach the pages
        # the capture cannot (a dynamic route) and stand when nothing rendered.
        contract = _contract_findings(doc, routes)
        if not shots and not contract:
            return None
        if shots and emit is not None:
            emit("review", {"phase": "shots", "pages": [
                {"route": s["route"], "image": _data_uri(s["png"])}
                for s in shots]})
        # Visual + domain: does it look right and match what was asked.
        visual: list = []
        if shots:
            try:
                from services.visual_qa_critic import critique_images
                visual = _run_async(critique_images(
                    shots, identity=_domain_identity(doc)))
            except Exception as exc:  # noqa: BLE001 — a failed review is a skipped one
                logger.warning("[review] visual critic failed: %s", exc)
                visual = []
        # Functional: do the buttons, forms, lists and links actually work.
        functional = _functional_findings(output_dir, doc) if shots else []
        findings = list(visual) + list(functional) + list(contract)
        # The ledger never sees the critique, so what sent a page round again
        # was unrecoverable afterwards. One line per finding, in the log.
        for f in findings:
            logger.info("[review] %s finding %s/%s %s: %s", Path(output_dir).name,
                        f.get("route"), f.get("kind"), f.get("severity"),
                        str(f.get("note") or "")[:300])
        if emit is not None:
            emit("review", {"phase": "analysis", "findings": findings})
        reviewed = [s["route"] for s in shots]
        reviewed += sorted({c["route"] for c in contract} - set(reviewed))
        return {"pages_reviewed": reviewed, "findings": findings}
    return critique


__all__ = [
    "_contract_findings", "invalidate_for_recompose", "write_review_briefs", "clear_review_briefs",
    "make_critique", "layouts_of", "restore_refused_layouts", "refused_pages",
    "unrepaired_pages", "Rebuilt",
]
