"""Screenshot the application the Blueprint says exists — §66, §107 step 21.

:mod:`services.blueprint.visual_verification` says what it needs and why it
cannot get it itself: a critique needs a rendered page, and §28's graph has no
way to produce one. This is the other half. It boots the projected app, visits
the routes the *Blueprint* claims, and returns what
``visual_verification.shots_for`` binds back to page artifacts.

Deliberately outside ``services.blueprint``. That package is constructible from
an ``output_dir`` and nothing else — no database, no network, no browser — and
that property is what lets a Blueprint load from a fixture or an export inside
a test. A Playwright import in there would end it.

Which routes, and which not
---------------------------
From the document, not from the filesystem. Walking ``src/app`` finds the
routes that were *generated*; the question a visual verification asks is
whether what the Blueprint promised is what a user sees, and that question is
only asked properly against the Blueprint's own list.

Three kinds of page are skipped, and each is skipped for a reason the document
states rather than one guessed at here:

* ``presentation`` of ``drawer`` or ``modal`` — §34's page contract says these
  open over their caller and do not own a route. Visiting one as a URL renders
  a 404, and a critique of a 404 is worse than no critique.
* A dynamic segment (``/candidates/[id]``) — a detail page needs a real record
  to be a detail page. Substituting an id here would be inventing data, and
  screenshotting the empty-state-that-is-really-a-404 would be scored as a
  design failure that belongs to the fixture rather than the page.
* ``DEPRECATED`` — §22 keeps these for history, not as obligations.

Everything skipped is *reported*. A capture that silently visited eleven of a
Blueprint's eighteen pages and returned a clean bill would be the most
expensive kind of green.

Landing where you asked
-----------------------
A page whose ``access`` is not ``public`` will redirect to a sign-in screen
when nobody is signed in, and the browser will happily screenshot that. Every
protected page then comes back looking identical and scoring identically,
which reads as a strikingly consistent design language. So the final URL is
compared with the requested one and a page that moved is reported as skipped
rather than critiqued — a fact observed, not a rule about which pages are
allowed to redirect.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

#: A route the app owns as its own URL. §34's other two presentations open over
#: a caller and have nothing to visit.
ROUTED = "page"

DEFAULT_VIEWPORT = {"width": 1440, "height": 900}

#: Long enough for a dev-server route to compile on first hit, which is the
#: usual reason a first visit is slow and every later one is not.
DEFAULT_TIMEOUT_MS = 30_000


@dataclass(frozen=True)
class Target:
    """One page the Blueprint says has a URL of its own."""

    page_id: str
    route: str
    access: str = "authenticated"


@dataclass
class Capture:
    """What was photographed, and what was not.

    ``rendered`` is in ``visual_verification.shots_for``'s shape on purpose:
    the two modules meet here and nowhere else.
    """

    rendered: list[tuple[str, bytes, str]] = field(default_factory=list)
    #: route -> why it was not photographed. Never silently empty.
    skipped: dict[str, str] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        return {"captured": len(self.rendered), "skipped": dict(self.skipped)}


def plan_routes(doc: dict) -> tuple[list[Target], dict[str, str]]:
    """(what to visit, what was left out and why) — derived from the document."""
    targets: list[Target] = []
    skipped: dict[str, str] = {}

    for page in doc.get("pages") or []:
        if not isinstance(page, dict):
            continue
        route = (page.get("route") or "").strip()
        page_id = page.get("id") or ""
        if not route:
            if page_id:
                skipped[page_id] = "the page declares no route"
            continue

        if page.get("status") == "DEPRECATED":
            skipped[route] = "deprecated (§22 keeps it for history, not as an obligation)"
        elif (page.get("presentation") or ROUTED) != ROUTED:
            skipped[route] = (
                f"presentation is {page['presentation']!r}; it opens over its "
                "caller and does not own a route (§34)"
            )
        elif "[" in route:
            skipped[route] = (
                "dynamic segment — a detail page needs a real record, and "
                "substituting an id would be inventing data"
            )
        else:
            targets.append(Target(
                page_id=page_id, route=route,
                access=page.get("access") or "authenticated",
            ))

    return targets, skipped


def landed(requested: str, final_url: str) -> str:
    """"" when the browser stayed put, otherwise why the shot is not usable.

    Compared by path. A query string or fragment the app adds to its own route
    is still that route; a different path is a different page, and the usual
    reason is a sign-in redirect on a page whose ``access`` is not public.
    """
    if not final_url:
        return "the browser reported no URL"
    got = urlsplit(final_url).path.rstrip("/") or "/"
    want = (requested or "").rstrip("/") or "/"
    if got == want:
        return ""
    return (
        f"redirected to {got} — most likely a sign-in gate; a screenshot of "
        "the login screen would be scored as this page's design"
    )


async def _shoot(
    base_url: str, targets: Sequence[Target], *,
    viewport: dict | None = None, timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> Capture:
    """Visit each target once and photograph it. One browser, one context."""
    from playwright.async_api import async_playwright

    out = Capture()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport=viewport or DEFAULT_VIEWPORT)
        page = await context.new_page()
        try:
            for target in targets:
                url = base_url.rstrip("/") + target.route
                try:
                    await page.goto(url, timeout=timeout_ms,
                                    wait_until="networkidle")
                except Exception as exc:  # noqa: BLE001 — one route, not the run
                    out.skipped[target.route] = f"did not load: {exc}"
                    continue

                moved = landed(target.route, page.url)
                if moved:
                    out.skipped[target.route] = moved
                    continue

                png = await page.screenshot(full_page=True)
                # The tree is what the critique reads for structure it cannot
                # see — a heading that is only bold, a button that is a div.
                snapshot = await page.accessibility.snapshot()
                out.rendered.append((target.route, png, _render_tree(snapshot)))
        finally:
            await context.close()
            await browser.close()
    return out


def _render_tree(node: Any, depth: int = 0) -> str:
    """The accessibility snapshot as indented text, for the prompt."""
    if not isinstance(node, dict):
        return ""
    role = node.get("role", "")
    name = (node.get("name") or "").strip()
    line = "  " * depth + (f"{role}: {name}" if name else role)
    parts = [line] if role else []
    for child in node.get("children") or []:
        sub = _render_tree(child, depth + 1 if role else depth)
        if sub:
            parts.append(sub)
    return "\n".join(parts)


def capture_rendered(
    doc: dict, output_dir: str | Path, *,
    base_url: str = "http://localhost:3000",
    boot_timeout_s: int = 90,
    viewport: dict | None = None,
) -> Capture:
    """Boot the projected app if it is not already up, and photograph it.

    Returns a :class:`Capture` whatever happens. A missing Playwright, an app
    that will not boot, a route that times out — each is reported as a reason
    against the routes it cost, because the caller's next move is a critique
    and a critique of nothing should say so rather than come back empty and
    look like agreement.
    """
    import asyncio

    targets, skipped = plan_routes(doc)
    if not targets:
        return Capture(skipped=skipped)

    try:
        from playwright.async_api import async_playwright  # noqa: F401
    except ImportError:
        skipped.update({t.route: "playwright is not installed" for t in targets})
        return Capture(skipped=skipped)

    from services.journey_verifier.boot import BootError, booted_app

    app_root = Path(output_dir)
    try:
        with booted_app(app_root, base_url=base_url,
                        boot_timeout_s=boot_timeout_s) as info:
            logger.info("[capture] %s (booted=%s)", info["url"], info["booted"])
            shot = asyncio.run(_shoot(base_url, targets, viewport=viewport))
    except BootError as exc:
        skipped.update({t.route: f"the app did not boot: {exc}" for t in targets})
        return Capture(skipped=skipped)

    shot.skipped.update(skipped)
    return shot
