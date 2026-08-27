"""Page-level navigation — breadcrumbs on nested pages.

The shell tells you which section of the app you're in. Nothing told
you where you are *inside* that section: measured across 173 generated
apps, 3365 page schemas sit at depth >= 2 and only 6.3% carry a
Breadcrumb. The component has been in the library all along; no pass
emitted it, because until services.route_tree existed nothing knew the
app had a hierarchy to express.

Scope is deliberately just breadcrumbs:

* **Pagination is already solved.** Table paginates internally — pageSize
  defaults to 25 and it renders its own pager once rows exceed that.
  Emitting a standalone Pagination node would add dead chrome next to a
  working one.
* **Sub-resource tabs have an owner** — services.record_subresource_tabs.

Two invariants:

1. Crumb hrefs come from ``RouteTree.ancestors()``, which returns only
   routes that EXIST. Splitting a path instead produces links to
   ``/products/[id]`` in apps that never registered it, and a crumb that
   404s is worse than no crumb.
2. Labels are always static text. A heading bound to ``{{product.name}}``
   renders as literal braces before hydration, so bindings are rejected
   as label sources and the leaf falls back to a plain word.

Report: contracts/page-nav.json. Additive and idempotent — an authored
Breadcrumb is never rewritten.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from services.entity_names import singularize
from services.route_tree import build_route_tree
from services.transition_materializer import _humanize

logger = logging.getLogger(__name__)

_SKIP_KINDS = frozenset({"auth", "root"})
_DYNAMIC_LEAF_LABEL = "Details"


def _is_param(segment: str) -> bool:
    """`[id]` (Next) or `:id` (Express-style) — both ship in the corpus."""
    return segment.startswith("[") or segment.startswith(":")


def _walk(node):
    """Every dict node in the tree, depth-first."""
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def _has_breadcrumb(doc: dict) -> bool:
    return any(n.get("type") == "Breadcrumb" for n in _walk(doc.get("root")))


def _container(doc: dict) -> list | None:
    """The root node's children list, when it has one."""
    root = doc.get("root")
    if not isinstance(root, dict):
        return None
    kids = root.get("children")
    return kids if isinstance(kids, list) else None


def _is_static_text(s) -> bool:
    """Reject bindings and template braces — they render literally."""
    return (isinstance(s, str) and s.strip() != ""
            and "{{" not in s and "{" not in s and len(s) <= 60)


def _heading_label(doc: dict) -> str | None:
    for n in _walk(doc.get("root")):
        if n.get("type") in ("Heading", "PageHeader", "Title"):
            props = n.get("props")
            if not isinstance(props, dict):
                continue
            for key in ("text", "title", "label"):
                if _is_static_text(props.get(key)):
                    return props[key].strip()
    return None


def _segment_label(segment: str) -> str:
    return _humanize(segment)


def _ancestor_label(route: str) -> str:
    """Label for an ancestor crumb.

    A dynamic ancestor (`/categories/[id]`) is one record of the
    collection above it, so it reads as "Category" — never "[id]",
    which is what naive humanising produced on 19 crumbs.
    """
    segs = [s for s in route.split("/") if s]
    if not segs:
        return _DYNAMIC_LEAF_LABEL
    if _is_param(segs[-1]):
        if len(segs) >= 2 and not _is_param(segs[-2]):
            return _segment_label(singularize(segs[-2]))
        return _DYNAMIC_LEAF_LABEL
    return _segment_label(segs[-1])


def _current_label(doc: dict, segments: tuple[str, ...]) -> str:
    """Label for the page you are on — static text, never a binding."""
    heading = _heading_label(doc)
    if heading:
        return heading
    leaf = segments[-1] if segments else ""
    if _is_param(leaf):
        # `/products/[id]` with no usable heading: the record's name lives
        # in data we cannot read at build time.
        return _DYNAMIC_LEAF_LABEL
    return _segment_label(leaf)


def _build_items(doc: dict, route: str, ancestors: list[str],
                 segments: tuple[str, ...]) -> list[dict]:
    items = [{"label": _ancestor_label(a), "href": a} for a in ancestors]
    items.append({"label": _current_label(doc, segments)})
    return items


def apply_page_nav(output_dir: str | Path) -> dict:
    """Inject breadcrumbs on nested pages. Returns the report dict."""
    root = Path(output_dir)
    sdir = root / "src" / "schemas"
    findings: list[dict] = []
    if not sdir.is_dir():
        return {"findings": findings}

    tree = build_route_tree(root)

    for route, node in sorted(tree.nodes.items()):
        if node.kind in _SKIP_KINDS or node.depth < 2 or not node.schema_name:
            continue
        ancestors = tree.ancestors(route)
        if not ancestors:
            # Nothing real to link up to — a crumb here would 404.
            findings.append({"slot": "breadcrumb", "route": route,
                             "action": "reported",
                             "detail": "nested page with no reachable ancestor route"})
            continue
        path = sdir / f"{node.schema_name}.json"
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - one bad file, not a dead pass
            continue
        if not isinstance(doc, dict) or not isinstance(doc.get("root"), dict):
            continue
        if _has_breadcrumb(doc):
            continue                       # authored or already injected
        container = _container(doc)
        if container is None:
            findings.append({"slot": "breadcrumb", "route": route,
                             "action": "reported",
                             "detail": "root node has no children list to insert into"})
            continue

        items = _build_items(doc, route, ancestors, node.segments)
        container.insert(0, {
            "id": f"nav_crumb_{route.strip('/').replace('/', '_')}",
            "type": "Breadcrumb",
            "props": {"items": items},
        })
        try:
            path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            logger.warning("[page-nav] could not write %s: %s", path, exc)
            continue
        findings.append({"slot": "breadcrumb", "route": route,
                         "action": "injected",
                         "trail": [i.get("href") for i in items[:-1]]})

    injected = [f for f in findings if f["action"] == "injected"]
    if injected:
        logger.info("[page-nav] injected %d breadcrumb(s)", len(injected))
    report = {
        "findings": findings,
        "summary": {
            "breadcrumbs_injected": len(injected),
            "reported": len(findings) - len(injected),
        },
    }
    try:
        out = root / "contracts" / "page-nav.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    return report


# ── the shipped contract ────────────────────────────────────────────

def write_route_tree_contract(output_dir: str | Path) -> dict:
    """Persist the route hierarchy where the running app can read it.

    300 nested routes across the corpus are hand-written .tsx that no
    JSON pass can patch. Rather than regex-rewriting React source — which
    would be fragile and undone by the next regeneration — the app shell
    reads this artifact and renders the crumb itself for any route the
    schema layer doesn't already own.

    ``owned_by_schema`` is the anti-duplication flag: true when the page
    schema already carries a Breadcrumb (authored, or injected by
    ``apply_page_nav``), so the shell stays out of the way.

    ``parent`` is the nearest EXISTING route, never a synthesized path,
    so a shell-rendered crumb can't link to a 404.
    """
    root = Path(output_dir)
    tree = build_route_tree(root)
    sdir = root / "src" / "schemas"

    routes: dict[str, dict] = {}
    for route, node in sorted(tree.nodes.items()):
        owned = False
        if node.schema_name:
            try:
                doc = json.loads(
                    (sdir / f"{node.schema_name}.json").read_text(encoding="utf-8"))
                owned = isinstance(doc, dict) and _has_breadcrumb(doc)
            except Exception:  # noqa: BLE001
                owned = False
        routes[route] = {
            "parent": node.parent,
            "label": _ancestor_label(route),
            "kind": node.kind,
            "dynamic": node.dynamic,
            "owned_by_schema": owned,
        }

    if not routes:
        return {"routes": 0}

    try:
        out = root / "src" / "contracts" / "route-tree.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"routes": routes}, indent=2, sort_keys=True),
                       encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.warning("[page-nav] could not write route-tree contract: %s", exc)
        return {"routes": 0}
    return {"routes": len(routes)}


__all__ = ["apply_page_nav", "write_route_tree_contract"]
