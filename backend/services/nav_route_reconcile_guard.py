"""Reconcile nav-flow route targets against the real generated page files.

THE BUG THIS FIXES
------------------
The sidebar links to `nav-flow.json` `pages[].route`. But that `route` can drift
from the page that was actually generated — e.g. a "dashboard" archetype collapses
two pages' routes to `/dashboard`, or a `watchlist` page's route gets pluralised to
`/watchlist-items`. Meanwhile each page's `schemaFile` still points at the REAL
generated file (`src/schemas/analytics.json`), which is what the schema registry is
keyed on (`/analytics`). Result: the pages exist and resolve, but every nav item
pointing at the drifted route 404s via the `notFound()` in `[entity]/page.tsx`.

THE FIX
-------
`schemaFile` is the ground truth (it names the file on disk = the registry key).
For every nav page we derive the route from its `schemaFile` — using the SAME
`route_from_slug` the registry uses — and rewrite `route` to match. We also repoint
`post_login_redirect` and the root `src/app/page.tsx` redirect at a route that
actually resolves, so the landing page stops 404-ing.

Deterministic, idempotent, and conservative: a page whose route already matches its
schemaFile is left untouched; a page whose schemaFile is missing on disk is skipped.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SCHEMA_PREFIX = "src/schemas/"


def _route_from_schema_file(schema_file: str) -> str | None:
    """`src/schemas/analytics.json` → `/analytics` (registry key form).

    Returns None if the path isn't a schema file we can map.
    """
    if not schema_file:
        return None
    p = schema_file.replace("\\", "/").strip()
    if not p.startswith(_SCHEMA_PREFIX) or not p.endswith(".json"):
        return None
    slug = p[len(_SCHEMA_PREFIX):-len(".json")]
    if not slug:
        return None
    from services.route_slug import route_from_slug
    return route_from_slug(slug)


def _materialize_route_group_landing(root: Path, landing: str) -> bool:
    """If `landing` (like ``/dashboard``) points at a name that only exists as a
    route GROUP (``src/app/(dashboard)/``) and not as a real URL segment, move
    the group's root ``page.tsx`` down into a real ``<name>/`` folder so the
    redirect target becomes a live URL.

    Route groups don't add a path segment, so ``src/app/(dashboard)/page.tsx``
    serves ``/``, not ``/dashboard``. A root-level redirect to ``/dashboard``
    therefore 404s at runtime AND breaks Next.js' build-time trace step
    (``page_client-reference-manifest.js`` not found). Renaming keeps the
    group's shared layout AND makes the URL real. Idempotent: no-ops if the
    real folder already exists or the group root has no page.tsx.
    """
    if not landing or not landing.startswith("/"):
        return False
    seg = landing[1:].split("/", 1)[0]
    if not seg or "/" in seg:
        return False
    app = root / "src" / "app"
    group = app / f"({seg})"
    group_page = group / "page.tsx"
    real = app / seg
    if not group_page.exists() or real.exists():
        return False
    dst_dir = group / seg
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst_page = dst_dir / "page.tsx"
    group_page.rename(dst_page)
    # The template's group-root file was authored for landing="/" and calls
    # `renderSchemaPage("/")`. Once moved DOWN to `<seg>/page.tsx` it now
    # serves `/<seg>`, and the schema pipeline registered the landing schema
    # under `/<seg>` (not `/`) — so the "/" lookup 404s. Rewrite the arg to
    # match the new URL. A regex is used so authoring drift (extra spaces,
    # single quotes, template literals) still matches.
    try:
        src = dst_page.read_text()
        new_src = re.sub(
            r'renderSchemaPage\(\s*["\'`]/["\'`]',
            f'renderSchemaPage("{landing}"',
            src,
        )
        if new_src != src:
            dst_page.write_text(new_src)
    except OSError:  # pragma: no cover — filesystem edge; the move still happened
        pass
    return True


def _purge_unused_route_group_root_pages(root: Path, landing: str | None) -> list[str]:
    """Delete any ``src/app/(<name>)/page.tsx`` that still exists after
    materialization AND that isn't actively serving the app's landing.

    A ``page.tsx`` at the ROOT of a parenthesized route group is the exact
    shape that triggers Next.js #58272 (build emits without a
    ``page_client-reference-manifest.js``; at runtime Next throws
    ``Invariant: Expected clientReferenceManifest to be defined``).

    Two cases where we KEEP the file:
    - Landing is the root (``/``): the group-root ``page.tsx`` is what
      serves ``/``. Deleting it would 404 the landing page. The Next.js
      bug is a separate concern to solve via nested route groups; that's
      out of scope for this guard.
    - Landing is ``/<name>`` matching the group (e.g. ``/dashboard``
      with a ``(dashboard)`` group): :func:`_materialize_route_group_landing`
      has already moved this file DOWN into ``(<name>)/<name>/page.tsx``
      before we run, so the group root is already empty.

    Any surviving group-root page.tsx after those two cases is unreachable
    (the root redirect goes elsewhere) and is a known landmine — delete
    it. Returns the list of deleted paths.
    """
    # Never purge when landing is the root — the group-root page IS the
    # landing page.
    if landing == "/":
        return []
    app = root / "src" / "app"
    if not app.is_dir():
        return []
    deleted: list[str] = []
    for entry in app.iterdir():
        if not entry.is_dir():
            continue
        name = entry.name
        # Route groups are dirs whose name is fully parenthesized.
        if not (name.startswith("(") and name.endswith(")")):
            continue
        page = entry / "page.tsx"
        if page.is_file():
            page.unlink()
            deleted.append(str(page.relative_to(root)))
    return deleted


def _fix_root_redirect(root: Path, landing: str | None) -> bool:
    """Repoint `src/app/page.tsx`'s redirect at `landing`, or DELETE it when the
    landing is the root itself.

    A top-level page.tsx that redirect("/")s the root loops forever
    (ERR_TOO_MANY_REDIRECTS). When home lives at "/", the (dashboard) route group's
    own page.tsx already serves it — so the top-level redirect file is redundant
    and must be removed rather than pointed at "/". Returns True if changed.
    """
    page = root / "src" / "app" / "page.tsx"
    if not page.exists():
        return False
    if not landing or landing == "/":
        # Landing is the root — the (dashboard) group serves "/"; a redirect here
        # can only self-loop. Remove the file.
        page.unlink()
        return True
    # Landing points at a real (or should-be-real) URL. If it only exists as a
    # route group root, materialize it into a real folder before leaving the
    # redirect in place — otherwise the redirect target is a phantom.
    _materialize_route_group_landing(root, landing)
    text = page.read_text()
    m = re.search(r'redirect\(\s*[`"\']([^`"\']*)[`"\']\s*\)', text)
    if not m or m.group(1) == landing:
        return False
    new_text = text[:m.start(1)] + landing + text[m.end(1):]
    page.write_text(new_text)
    return True


def _url_path_for(page: Path, app: Path) -> str | None:
    """The URL a `page.tsx` actually serves, from where it sits.

    Route groups — `(name)` — exist to share a layout and contribute NO URL
    segment, which is exactly why the group-root file legitimately serves "/"
    while a file one level down serves "/<seg>". That distinction is the whole
    bug: both live under `(group)/`, and only the path says which is which.
    """
    try:
        rel = page.parent.relative_to(app)
    except ValueError:
        return None
    segs = [s for s in rel.parts if not (s.startswith("(") and s.endswith(")"))]
    if any(s.startswith("[") for s in segs):
        return None          # a pattern, not a key the page can name literally
    return "/" + "/".join(segs) if segs else "/"


def align_schema_keys_to_routes(output_dir: str) -> dict[str, Any]:
    """Make every page ask the registry for the URL it serves. Best-effort.

    Only the template's `renderSchemaPage("/")` default is rewritten: it is the
    one literal known to be a leftover rather than a decision. Anything else a
    page names is deliberate and left alone.

    Stated as an invariant on the file rather than a step in
    `_materialize_route_group_landing`, which only rewrote pages IT had just
    moved — so a page that reached `<seg>/page.tsx` any other way kept the
    wrong argument and rendered blank. Idempotent: a corrected page no longer
    matches.
    """
    app = Path(output_dir) / "src" / "app"
    if not app.is_dir():
        return {"fixed": 0, "files": []}
    fixed: list[str] = []
    for page in sorted(app.rglob("page.tsx")):
        url = _url_path_for(page, app)
        if not url or url == "/":
            continue             # the group root really does serve "/"
        try:
            src = page.read_text()
        except OSError:
            continue
        new = re.sub(r'renderSchemaPage\(\s*["\'`]/["\'`]',
                     f'renderSchemaPage("{url}"', src)
        if new == src:
            continue
        try:
            page.write_text(new)
        except OSError:          # pragma: no cover — filesystem edge
            continue
        fixed.append(url)
    if fixed:
        logger.info("nav_route_reconcile: pointed %d page(s) at their own "
                    "route key: %s", len(fixed), ", ".join(fixed))
    return {"fixed": len(fixed), "files": fixed}


def reconcile_nav_routes(output_dir: str) -> dict[str, Any]:
    """Rewrite drifted nav-flow routes to match their schemaFile. Returns a report."""
    root = Path(output_dir)
    nav_path = root / "src" / "contracts" / "nav-flow.json"
    if not nav_path.exists():
        return {"remapped": 0, "pages": 0, "landing": None}

    try:
        nav = json.loads(nav_path.read_text())
    except (json.JSONDecodeError, OSError):
        return {"remapped": 0, "pages": 0, "landing": None}

    pages = nav.get("pages")
    if not isinstance(pages, list):
        return {"remapped": 0, "pages": 0, "landing": None}

    id_to_route: dict[str, str] = {}
    remapped = 0

    for page in pages:
        if not isinstance(page, dict):
            continue
        schema_file = page.get("schemaFile")
        derived = _route_from_schema_file(schema_file) if schema_file else None
        if derived is None:
            continue
        # Only trust the derived route if the file it names actually exists on disk.
        if not (root / schema_file).exists():
            continue
        pid = page.get("id")
        if isinstance(pid, str):
            id_to_route[pid] = derived
        if page.get("route") != derived:
            page["route"] = derived
            remapped += 1

    # Choose the landing route for the root redirect. It MUST be a post-login
    # shell page (e.g. /dashboard) — never the unauthenticated entry (/login).
    # The (dashboard) layout's session gate is what sends anonymous users to
    # /login; if the root itself redirected to /login, an authenticated user
    # hitting "/" would loop straight back to the login page. Prefer a top-level
    # (non-param) shell page.
    shell_routes = [
        p["route"] for p in pages
        if isinstance(p, dict) and p.get("shell")
        and isinstance(p.get("route"), str) and "[" not in p["route"]
    ]
    landing: str | None = None
    plr0 = nav.get("post_login_redirect")
    if isinstance(plr0, str) and plr0 in shell_routes:
        landing = plr0
    elif shell_routes:
        landing = shell_routes[0]
    else:
        # No shell pages at all — fall back to the initialPage's route.
        initial = nav.get("initialPage")
        if isinstance(initial, str) and initial in id_to_route:
            landing = id_to_route[initial]

    # Repoint post_login_redirect at the landing route if it no longer resolves,
    # so it agrees with the root redirect (one landing page, not two).
    valid_routes = {
        p["route"] for p in pages if isinstance(p, dict) and isinstance(p.get("route"), str)
    }
    plr = nav.get("post_login_redirect")
    if isinstance(plr, str) and landing and plr not in valid_routes:
        nav["post_login_redirect"] = landing

    if remapped:
        nav_path.write_text(json.dumps(nav, indent=2))

    # Fix the root redirect to land on a real route.
    root_fixed = False
    if landing:
        root_fixed = _fix_root_redirect(root, landing)

    # Purge any surviving ``(<group>)/page.tsx`` — Next.js #58272 landmine.
    # Runs AFTER materialize (which moves a group-root page into a real
    # subroute when landing points at it) so we only delete pages that
    # nothing routes to.
    purged = _purge_unused_route_group_root_pages(root, landing)

    # Every page asks the registry for the URL it serves — checked on the
    # FILE, so it holds however the page got where it is. The materialize step
    # above rewrites the pages it moves itself; this catches the ones it never
    # touched, which is how a 58-node dashboard came to sit beside a route
    # asking for a key that did not exist.
    aligned = align_schema_keys_to_routes(str(root))

    if remapped or root_fixed or purged or aligned.get("fixed"):
        logger.info(
            "nav_route_reconcile: remapped %d nav route(s), landing=%s, "
            "root_redirect_fixed=%s, purged_group_root_pages=%s, "
            "schema_keys_aligned=%s in %s",
            remapped, landing, root_fixed, purged,
            aligned.get("files") or [], output_dir,
        )
    return {
        "remapped": remapped,
        "pages": len(pages),
        "landing": landing,
        "root_fixed": root_fixed,
        "purged_group_root_pages": purged,
        "schema_keys_aligned": aligned.get("files") or [],
    }
