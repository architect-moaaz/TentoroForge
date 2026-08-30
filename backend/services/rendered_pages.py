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

Two kinds of page are skipped outright, each for a reason the document states
rather than one guessed at here:

* ``presentation`` of ``drawer`` or ``modal`` — §34's page contract says these
  open over their caller and do not own a route. Visiting one as a URL renders
  a 404, and a critique of a 404 is worse than no critique.
* ``DEPRECATED`` — §22 keeps these for history, not as obligations.

A dynamic segment (``/candidates/[id]``) is not skipped, it is *resolved*. A
detail page needs a real record to be a detail page, and inventing an id would
screenshot the empty-state-that-is-really-a-404 and score it as a design
failure belonging to the fixture. So the id is read back from the running app:
``page.data.primaryEntity`` names the entity, ``apis`` names the collection
endpoint for it, and the first seeded row's id is what the route is visited
with. Derived from the document, and reproducible because ``project_seed``
writes derived rather than random rows for exactly this reason. A route whose
id cannot be read back is skipped and says so.

Everything skipped is *reported*. A capture that silently visited eleven of a
Blueprint's eighteen pages and returned a clean bill would be the most
expensive kind of green.

Landing where you asked
-----------------------
A page whose ``access`` is not ``public`` redirects to a sign-in screen when
nobody is signed in, and the browser will happily screenshot that. Every
protected page then comes back looking identical and scoring identically, which
reads as a strikingly consistent design language.

`access` defaults to ``authenticated``, so signed out this reviewed roughly the
pages that had opted into ``public`` — on a real application, close to nothing.
So the browser is signed in: :mod:`services.preview_session` mints the cookie
NextAuth expects, and pages are swept in role groups so a ``role_restricted``
page is visited by a session carrying a role rather than by a stranger.

The redirect check stays, and matters more now than it did. It is what catches
a session that was not accepted — a wrong secret, an app somebody else booted —
instead of returning a set of identical login screenshots and a clean report.
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
    #: ROLE ids the page is addressed to. Only consulted for
    #: ``role_restricted`` — an ``authenticated`` page is for whoever is
    #: signed in, and sweeping it once per role would pay for the same
    #: screenshot as many times as the application has roles.
    users: tuple[str, ...] = ()
    #: ENTITY id behind the page, when it has one. What a dynamic segment is
    #: resolved through.
    entity: str = ""

    @property
    def is_dynamic(self) -> bool:
        return "[" in self.route

    @property
    def role(self) -> str:
        """The role this page must be visited as, or "" for any session."""
        if self.access != "role_restricted":
            return ""
        return self.users[0] if self.users else ""


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
        else:
            targets.append(Target(
                page_id=page_id, route=route,
                access=page.get("access") or "authenticated",
                users=tuple(page.get("users") or ()),
                entity=((page.get("data") or {}).get("primaryEntity") or ""),
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


def collection_endpoint(doc: dict, entity: str) -> str:
    """The GET path that lists ``entity``, or "" when nothing lists it.

    Derived, not guessed. §28 has ``apis`` produced from what the workflows and
    widgets actually need, so the endpoint that lists an entity is a fact the
    document already holds — and pluralising the entity name into a URL by
    convention would be a second, quieter source of truth that is wrong the
    first time a resource is not named what its table is.

    The collection endpoint, not the item one: an item path carries the
    parameter this exists to fill in.
    """
    paths = sorted(
        (a.get("path") or "").strip()
        for a in (doc.get("apis") or [])
        if isinstance(a, dict)
        and a.get("entity") == entity
        and (a.get("method") or "GET").upper() == "GET"
        and a.get("status") != "DEPRECATED"
    )
    for path in paths:
        if path and "[" not in path and ":" not in path and "{" not in path:
            return path if path.startswith("/") else "/" + path
    return ""


def first_id(body: Any) -> str:
    """The id of the first record in a list response, or "".

    Tolerant of the shapes a generated API actually returns — a bare array, or
    an object wrapping one under `data`/`items`/`results`. Not tolerant of
    guessing: an object with no list in it returns "" and the route is skipped
    with a reason, rather than reaching for the first string that looks like an
    id.
    """
    rows = body
    if isinstance(body, dict):
        for key in ("data", "items", "results", "rows", "records"):
            if isinstance(body.get(key), list):
                rows = body[key]
                break
        else:
            rows = None
    if not isinstance(rows, list) or not rows:
        return ""
    first = rows[0]
    if not isinstance(first, dict):
        return ""
    for key in ("id", "uuid", "slug"):
        value = first.get(key)
        if isinstance(value, (str, int)) and str(value).strip():
            return str(value)
    return ""


def fill_route(route: str, record_id: str) -> str:
    """`/candidates/[id]` + `c-1` -> `/candidates/c-1`.

    Every segment, because a nested detail route carries more than one and a
    URL left holding a literal `[id]` is a 404 that would be critiqued as a
    page.
    """
    import re

    return re.sub(r"\[\.{0,3}(\w+)\]", record_id, route)


async def _shoot(
    base_url: str, targets: Sequence[Target], *,
    doc: dict | None = None,
    sessions: dict[str, Any] | None = None,
    secret: str = "",
    viewport: dict | None = None, timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> Capture:
    """Visit each target once and photograph it.

    One browser context per role rather than one for the run: a cookie is set
    on the context, and a `role_restricted` page visited by a session carrying
    the wrong role is the failure this whole path exists to avoid.
    """
    from playwright.async_api import async_playwright

    from services.preview_session import cookie as session_cookie

    doc = doc or {}
    out = Capture()
    groups: dict[str, list[Target]] = {}
    for target in targets:
        groups.setdefault(target.role, []).append(target)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            for role, group in sorted(groups.items()):
                session = (sessions or {}).get(role) or (sessions or {}).get("")
                context = await browser.new_context(
                    viewport=viewport or DEFAULT_VIEWPORT)
                if session is not None:
                    await context.add_cookies([session_cookie(
                        session, base_url=base_url, secret=secret)])
                page = await context.new_page()
                try:
                    await _sweep(page, base_url, group, doc, out,
                                 timeout_ms=timeout_ms)
                finally:
                    await context.close()
        finally:
            await browser.close()
    return out


async def _resolve(page: Any, base_url: str, target: Target, doc: dict) -> str:
    """The route with its dynamic segments filled in, or "" with a reason set.

    Fetched through the *browser*, not a bare HTTP client, so the request
    carries the same session cookie the page visit will. An endpoint that is
    itself gated would otherwise answer the sweep with a redirect to login and
    no rows, and the detail page would be reported as having no records when
    what it had was no session.
    """
    import json as _json

    if not target.entity:
        return ""
    path = collection_endpoint(doc, target.entity)
    if not path:
        return ""
    try:
        response = await page.request.get(base_url.rstrip("/") + path)
        body = _json.loads(await response.text())
    except Exception:  # noqa: BLE001 — a route, never the run
        return ""
    record_id = first_id(body)
    return fill_route(target.route, record_id) if record_id else ""


async def _sweep(
    page: Any, base_url: str, targets: Sequence[Target], doc: dict,
    out: Capture, *, timeout_ms: int,
) -> None:
    for target in targets:
        route = target.route
        if target.is_dynamic:
            route = await _resolve(page, base_url, target, doc)
            if not route:
                out.skipped[target.route] = (
                    "no seeded record to open it with — the page needs one, "
                    "and inventing an id would photograph a 404"
                )
                continue

        try:
            await page.goto(base_url.rstrip("/") + route, timeout=timeout_ms,
                            wait_until="networkidle")
        except Exception as exc:  # noqa: BLE001 — one route, not the run
            out.skipped[target.route] = f"did not load: {exc}"
            continue

        moved = landed(route, page.url)
        if moved:
            out.skipped[target.route] = moved
            continue

        png = await page.screenshot(full_page=True)
        # The tree is what the critique reads for structure it cannot see — a
        # heading that is only bold, a button that is a div.
        snapshot = await page.accessibility.snapshot()
        # Reported under the route the Blueprint declares, not the one that was
        # visited: `shots_for` binds back by route, and `/candidates/c-1` is
        # not a page any Blueprint claims.
        out.rendered.append((target.route, png, _render_tree(snapshot)))


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
    authenticate: bool = True,
    secret: str = "",
) -> Capture:
    """Boot the projected app if it is not already up, and photograph it.

    Returns a :class:`Capture` whatever happens. A missing Playwright, an app
    that will not boot, a route that times out, a detail page with no seeded
    record — each is reported as a reason against the routes it cost, because
    the caller's next move is a critique and a critique of nothing should say
    so rather than come back empty and look like agreement.

    ``authenticate`` signs the browser in. Off, this reviews the pages that
    declared themselves public and reports a sign-in gate against everything
    else — honest, and on a real application close to nothing, since `access`
    defaults to ``authenticated``.
    """
    import asyncio

    from services.preview_session import PREVIEW_SECRET, boot_env, sessions_for

    targets, skipped = plan_routes(doc)
    if not targets:
        return Capture(skipped=skipped)

    try:
        from playwright.async_api import async_playwright  # noqa: F401
    except ImportError:
        skipped.update({t.route: "playwright is not installed" for t in targets})
        return Capture(skipped=skipped)

    from services.journey_verifier.boot import BootError, booted_app

    secret = secret or PREVIEW_SECRET
    sessions = (
        sessions_for(doc, {t.role for t in targets if t.role})
        if authenticate else None
    )

    app_root = Path(output_dir)
    try:
        with booted_app(app_root, base_url=base_url,
                        boot_timeout_s=boot_timeout_s,
                        env_extra=boot_env(base_url, secret) if authenticate
                        else None) as info:
            logger.info("[capture] %s (booted=%s)", info["url"], info["booted"])
            if authenticate and not info["booted"]:
                # It was already listening, so it was started by somebody else
                # and with somebody else's secret. Say so once here rather than
                # let it surface as every gated page reporting a sign-in gate.
                logger.warning(
                    "[capture] %s was already running, so it does not have the "
                    "secret this session was minted against; gated pages will "
                    "report a sign-in gate unless it was booted with %r",
                    base_url, secret,
                )
            try:
                shot = asyncio.run(_shoot(
                    base_url, targets, doc=doc, sessions=sessions,
                    secret=secret, viewport=viewport))
            except Exception as exc:  # noqa: BLE001
                # The package imports and the browser binary is a separate
                # install, so "playwright is present" does not mean a browser
                # will launch. Whatever went wrong with the browser itself, it
                # cost every route, and saying so is the contract.
                skipped.update({t.route: f"the browser did not run: {exc}"
                                for t in targets})
                return Capture(skipped=skipped)
    except BootError as exc:
        skipped.update({t.route: f"the app did not boot: {exc}" for t in targets})
        return Capture(skipped=skipped)

    shot.skipped.update(skipped)
    return shot
