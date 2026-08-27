"""The route-hierarchy contract — one tree that knows the app has depth.

Every page-nav guarantee we ship is keyed to ``src/schemas/*.json``.
That directory is flat: measured across 173 generated apps, 1365 of
1440 page schemas are single-segment routes and exactly ONE carries a
dynamic route. Meanwhile ``src/app`` holds 921 real ``[id]`` detail
routes and 203 three-segment routes.

The hierarchy is real; the authoring layer just can't see it. So
page_anatomy's back-affordance rule fires on ~1 of 921 detail pages,
0 of 86 nested schema routes get a Breadcrumb, and 1 of 714 list
pages gets Pagination — not because those rules are wrong, but
because they're reading the wrong directory.

This module unions the three places a route can be defined:

  1. ``src/app/**/page.tsx``   — real Next routes, including the
     template-injected detail pages (runtime_injector) that never
     touch the schema layer
  2. ``src/schemas/registry.ts`` — the authoritative live-route map
     for schema-rendered pages (see delivery_gate._load_registry_routes)
  3. page-schema ``route`` fields — belt-and-braces for schemas not
     yet in the registry

and links them into real parent/child relationships.

The invariant that matters most is in ``ancestors()``: it returns
only routes that EXIST. Breadcrumbs built by string-splitting a path
happily link to ``/products/[id]`` when no such route is registered,
and a crumb that 404s is worse than no crumb at all.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Leaf segments that name an action rather than a resource.
_CREATE_LEAVES = frozenset({"new", "create", "add", "upload"})
_EDIT_LEAVES = frozenset({"edit", "update"})
_AUTH_LEAVES = frozenset({"login", "signup", "signin", "signout",
                          "logout", "register", "forgot-password",
                          "reset-password"})

_ROUTE_GROUP = re.compile(r"^\(.*\)$")
#: A path parameter, in either flavour the corpus ships: Next's `[id]`
#: and the Express-style `:id` that some emitted routes still use.
_PARAM = re.compile(r"^(\[|:)")
_REGISTRY_KEY = re.compile(r'"(/[^"]*)"\s*:\s*\(\)\s*=>')


@dataclass(frozen=True)
class RouteNode:
    """One reachable destination in the app."""

    route: str
    segments: tuple[str, ...]
    depth: int
    #: Nearest EXISTING ancestor route, or None. Never a synthesized path.
    parent: str | None
    kind: str          # root | list | detail | create | edit | sub | auth
    dynamic: bool
    #: Schema file stem when this route is schema-rendered, else None —
    #: the difference between "a nav pass can patch this" and "this is
    #: hand-written .tsx and needs a different seam".
    schema_name: str | None
    #: Path to the src/app page file, relative to the app root, when this
    #: route is a real .tsx page. The .tsx seam needs it; a JSON pass can
    #: at least read it to avoid reporting a back affordance that is
    #: already there in JSX.
    page_path: str | None
    has_page_file: bool


@dataclass
class RouteTree:
    nodes: dict[str, RouteNode] = field(default_factory=dict)

    def children(self, route: str) -> list[str]:
        return sorted(r for r, n in self.nodes.items() if n.parent == route)

    def ancestors(self, route: str) -> list[str]:
        """Existing ancestor routes, root-first — the breadcrumb trail.

        Only real routes. A gap in the path is skipped, never invented.
        """
        out: list[str] = []
        node = self.nodes.get(route)
        seen: set[str] = set()
        while node is not None and node.parent:
            if node.parent in seen:      # defensive: never loop
                break
            seen.add(node.parent)
            out.append(node.parent)
            node = self.nodes.get(node.parent)
        return list(reversed(out))

    def detail_routes(self) -> list[str]:
        return sorted(r for r, n in self.nodes.items() if n.kind == "detail")

    def nested_routes(self) -> list[str]:
        return sorted(r for r, n in self.nodes.items() if n.depth >= 2)

    def by_kind(self, kind: str) -> list[str]:
        return sorted(r for r, n in self.nodes.items() if n.kind == kind)


# ── route normalisation ─────────────────────────────────────────────

def _segments(rel: str) -> list[str] | None:
    """Path relative to src/app → route segments, or None if not a route.

    Drops Next.js scaffolding that carries no route meaning: route
    groups ``(dashboard)``, private ``_folders``, API handlers, and the
    ``[...slug]`` catch-all (which is the schema-page renderer itself,
    not a destination a user navigates to).
    """
    raw = [s for s in rel.replace("\\", "/").split("/") if s and s != "."]
    out: list[str] = []
    for s in raw:
        if _ROUTE_GROUP.match(s):
            continue
        if s.startswith("_") or s.startswith("."):
            return None
        if s.startswith("[..."):
            return None
        out.append(s)
    if out and out[0] == "api":
        return None
    # A LEADING dynamic segment means a generic renderer, not a page:
    # `/[entity]` and `/[entity]/[id]` are the schema router parameterised
    # by entity name, shipped alongside [...slug]. Counting them as detail
    # pages made the anatomy pass report three phantom dead ends per app.
    if out and _PARAM.match(out[0]):
        return None
    return out


def _norm(route: str) -> str:
    segs = [s for s in (route or "").split("/") if s]
    return "/" + "/".join(segs) if segs else "/"


def _classify(segs: tuple[str, ...]) -> str:
    if not segs:
        return "root"
    last = segs[-1].lower()
    if last in _AUTH_LEAVES:
        return "auth"
    if last in _CREATE_LEAVES:
        return "create"
    if last in _EDIT_LEAVES:
        return "edit"
    if _PARAM.match(last):
        return "detail"
    # A static leaf under a dynamic parent is a child collection of one
    # record (/sessions/[id]/votes), not a top-level list.
    if any(_PARAM.match(s) for s in segs[:-1]):
        return "sub"
    return "list"


def _nearest_existing_parent(segs: tuple[str, ...], known: set[str]) -> str | None:
    """Walk up until a route that actually exists. Never synthesize."""
    for cut in range(len(segs) - 1, 0, -1):
        cand = "/" + "/".join(segs[:cut])
        if cand in known:
            return cand
    return None


# ── source readers ──────────────────────────────────────────────────

def _routes_from_app_dir(root: Path) -> dict[str, str]:
    """{route: page-file path relative to the app root}."""
    app = root / "src" / "app"
    if not app.is_dir():
        return {}
    out: dict[str, str] = {}
    for page in sorted(app.rglob("page.tsx")):
        try:
            rel = page.parent.relative_to(app).as_posix()
        except ValueError:  # pragma: no cover - rglob guarantees containment
            continue
        segs = _segments(rel)
        if segs is None:
            continue
        out["/" + "/".join(segs) if segs else "/"] = page.relative_to(root).as_posix()
    return out


def _routes_from_registry(root: Path) -> set[str]:
    p = root / "src" / "schemas" / "registry.ts"
    if not p.is_file():
        return set()
    try:
        return {_norm(r) for r in _REGISTRY_KEY.findall(p.read_text(encoding="utf-8"))}
    except Exception:  # noqa: BLE001 - a broken registry must not sink the tree
        logger.warning("route_tree: unreadable registry.ts at %s", p)
        return set()


def _routes_from_schemas(root: Path) -> dict[str, str]:
    """{route: schema id} for every page schema on disk.

    The id is the path relative to src/schemas without the suffix
    ("products", "documents/[id]") so a caller can reopen the file.

    Two shapes in the wild: most schemas declare an explicit ``route``,
    but nested ones (``documents/[id].json``) rely on their path being
    the route. Honour the declared route when present, fall back to the
    path otherwise — the fallback is what reaches detail schemas.
    """
    sdir = root / "src" / "schemas"
    if not sdir.is_dir():
        return {}
    out: dict[str, str] = {}
    for p in sorted(sdir.rglob("*.json")):
        if p.stem in ("registry", "shell"):
            continue
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - one bad file, not a dead tree
            logger.debug("route_tree: skipping unparseable schema %s", p.name)
            continue
        if not isinstance(doc, dict):
            continue
        sid = p.relative_to(sdir).with_suffix("").as_posix()
        route = doc.get("route")
        if isinstance(route, str) and route.strip():
            out[_norm(route)] = sid
        else:
            out["/" if sid == "index" else _norm(sid)] = sid
    return out


# ── entry point ─────────────────────────────────────────────────────

def build_route_tree(root: Path | str) -> RouteTree:
    """Union every route source into one tree with real parent links."""
    root = Path(root)
    from_app = _routes_from_app_dir(root)
    from_schemas = _routes_from_schemas(root)
    known = set(from_app) | _routes_from_registry(root) | set(from_schemas)
    if not known:
        return RouteTree()

    nodes: dict[str, RouteNode] = {}
    for route in sorted(known):
        segs = tuple(s for s in route.split("/") if s)
        nodes[route] = RouteNode(
            route=route,
            segments=segs,
            depth=len(segs),
            parent=_nearest_existing_parent(segs, known),
            kind=_classify(segs),
            dynamic=any(_PARAM.match(s) for s in segs),
            schema_name=from_schemas.get(route),
            page_path=from_app.get(route),
            has_page_file=route in from_app,
        )
    return RouteTree(nodes=nodes)
