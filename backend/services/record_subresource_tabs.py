"""Sub-resource workspace tabs on parent detail pages.

The pipeline authors nested child routes (``/events/[id]/sessions``,
``/events/[id]/attendees``, ``/events/[id]/check-in`` …) but nothing on the
parent detail page links to them — on qeqorfii the event detail page had
ZERO navigate targets, leaving six child workspaces reachable only by
typing URLs. This pass makes the aggregate root a real hub: every detail
page whose route has static nested children gets a tab-style link row
(Overview + one link per child) injected right under its header.

Deterministic + idempotent: a re-run replaces the previously injected row
(tagged ``data-subresource-tabs``) so child routes added later show up.
Interpolation uses the page's record dataSource (``/{slug}/{{record.id}}/…``)
— the same proven pattern deterministic_pages uses for Edit buttons.

Children come from ``services.route_tree`` — the union of src/app, the
route registry and page schemas — not from nav-flow. nav-flow is a
derived persona/job view, not the route inventory: measured on the
corpus, 13 aggregate roots have >= 2 sub-resources and 8 have a
patchable detail schema, but only 2 apps ever got a tab row, because
the children were missing from nav-flow (and the pass bailed outright
when nav-flow.json was unreadable). The routes were there all along.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from services.route_tree import build_route_tree

logger = logging.getLogger(__name__)

_TAB_ROW_TAG = "data-subresource-tabs"


def _is_param(segment: str) -> bool:
    """`[id]` (Next) or `:id` (Express-style) — both ship in the corpus."""
    return segment.startswith("[") or segment.startswith(":")


def _humanize(segment: str) -> str:
    pieces = re.split(r"[-_\s]+", segment.strip())
    return " ".join(p.capitalize() for p in pieces if p)


def _record_var(schema: dict) -> str | None:
    """Name of the detail page's record dataSource (``record`` in the
    deterministic builders), used for ``{{var.id}}`` interpolation."""
    for d in schema.get("dataSources") or []:
        if not isinstance(d, dict):
            continue
        if d.get("op") in ("get", "record", "detail") and d.get("name"):
            return str(d["name"])
    for d in schema.get("dataSources") or []:
        if isinstance(d, dict) and d.get("name"):
            return str(d["name"])
    return None


def _child_segments(tree, nav_flow: dict, slug: str) -> list[str]:
    """Static child segments under ``/{slug}/<param>/`` in stable order.

    ``/events/[id]/sessions`` → ``sessions``. Both param flavours the
    corpus ships are accepted (``[id]`` and ``:id``). Create/edit forms
    are not workspaces — they're actions — so ``new``/``edit`` are out.

    The route tree is the primary source; nav-flow is UNIONED in rather
    than replaced. nav-flow can declare a child route that is planned but
    not yet registered, and dropping it would regress the hub for exactly
    the aggregate roots this pass was built for.
    """
    out: list[str] = []

    def _offer(seg: str) -> None:
        if seg and seg not in ("new", "edit") and seg not in out:
            out.append(seg)

    def _child_of(segs) -> str | None:
        if (len(segs) == 3 and segs[0] == slug
                and _is_param(segs[1]) and not _is_param(segs[2])):
            return segs[2]
        return None

    # nav-flow FIRST, in declaration order. That order is authored intent
    # — "Sessions" before "Attendees" is a judgement about which workspace
    # matters most — and alphabetising it throws that away.
    for p in (nav_flow or {}).get("pages") or []:
        if not isinstance(p, dict):
            continue
        seg = _child_of([x for x in str(p.get("route") or "").split("/") if x])
        if seg:
            _offer(seg)

    # Then routes nav-flow never mentioned, sorted so the result is stable.
    extras = sorted({
        seg for node in tree.nodes.values()
        if (seg := _child_of(node.segments)) and seg not in out
    })
    for seg in extras:
        _offer(seg)

    return out


def _build_tab_row(slug: str, var: str, children: list[str]) -> dict:
    tabs: list[dict] = [{
        "type": "Button",
        "props": {
            "label": "Overview", "variant": "secondary", "size": "sm",
            "navigate": f"/{slug}/{{{{{var}.id}}}}",
        },
    }]
    for seg in children:
        tabs.append({
            "type": "Button",
            "props": {
                "label": _humanize(seg), "variant": "ghost", "size": "sm",
                "navigate": f"/{slug}/{{{{{var}.id}}}}/{seg}",
            },
        })
    return {
        "type": "Row",
        "props": {
            _TAB_ROW_TAG: "true",
            "gap": "tokens.spacing.1",
            "className": "flex-wrap border-b pb-2",
        },
        "children": tabs,
    }


def _strip_existing(children: list) -> list:
    return [
        c for c in children
        if not (isinstance(c, dict) and (c.get("props") or {}).get(_TAB_ROW_TAG))
    ]


def _insert_index(children: list) -> int:
    """After the leading header block: skip initial Heading/Text/Button/Row
    nodes that contain no Card/Table (page header + action row), insert
    before the first content surface. Falls back to position 0."""
    surface = {"Card", "Table", "Grid", "Section", "Stack", "Split",
               "DescriptionList", "Tabs", "Chart", "Stepper"}
    for i, c in enumerate(children):
        if isinstance(c, dict) and c.get("type") in surface:
            return i
    return 0


def inject_subresource_tabs(output_dir: str) -> dict:
    """Inject/refresh the tab row on every detail page with nested static
    children. Returns ``{pages: [routes], tabs: int, skipped: [...]}``."""
    root = Path(output_dir)
    sdir = root / "src" / "schemas"
    if not sdir.is_dir():
        return {"pages": [], "tabs": 0, "skipped": []}

    tree = build_route_tree(root)
    nav_flow: dict = {}
    for cand in (root / "src" / "contracts" / "nav-flow.json",
                 root / "contracts" / "nav-flow.json"):
        if cand.is_file():
            try:
                nav_flow = json.loads(cand.read_text(encoding="utf-8")) or {}
            except Exception:  # noqa: BLE001 - a bad nav-flow must not bail
                nav_flow = {}
            break

    # Every collection slug that owns a record-scoped child route, from
    # either source.
    slugs: set[str] = {
        n.segments[0] for n in tree.nodes.values()
        if len(n.segments) == 3 and _is_param(n.segments[1])
        and not _is_param(n.segments[2])
    }
    for p in (nav_flow or {}).get("pages") or []:
        if not isinstance(p, dict):
            continue
        segs = [x for x in str(p.get("route") or "").split("/") if x]
        if (len(segs) == 3 and _is_param(segs[1]) and not _is_param(segs[2])):
            slugs.add(segs[0])
    slugs = sorted(slugs)

    done: list[str] = []
    skipped: list[dict] = []
    total = 0
    for slug in slugs:
        children = _child_segments(tree, nav_flow, slug)
        if len(children) < 2:
            continue  # one child isn't a workspace; a link inline suffices

        detail = next(
            (n for n in tree.nodes.values()
             if len(n.segments) == 2 and n.segments[0] == slug
             and _is_param(n.segments[1])),
            None)
        if detail is None or not detail.schema_name:
            # The children exist but the hub page does not, or ships as
            # hand-written .tsx this JSON pass cannot patch. Say so rather
            # than dropping it silently — that is how six of eight
            # eligible roots went unnoticed.
            skipped.append({"slug": slug, "children": children,
                            "reason": "no patchable detail schema"})
            continue

        detail_fp = sdir / f"{detail.schema_name}.json"
        try:
            schema = json.loads(detail_fp.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            skipped.append({"slug": slug, "reason": "unreadable detail schema"})
            continue
        var = _record_var(schema)
        if not var:
            skipped.append({"slug": slug, "reason": "no record dataSource"})
            continue
        node = schema.get("root") if isinstance(schema.get("root"), dict) else schema
        kids = node.get("children")
        if not isinstance(kids, list):
            skipped.append({"slug": slug, "reason": "root has no children list"})
            continue
        kids = _strip_existing(kids)
        row = _build_tab_row(slug, var, children)
        kids.insert(_insert_index(kids), row)
        node["children"] = kids
        try:
            detail_fp.write_text(json.dumps(schema, indent=2), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            logger.warning("[subresource-tabs] write failed for %s: %s", detail_fp, exc)
            continue
        done.append(detail.route)
        total += len(children)

    if done:
        logger.info("[subresource-tabs] hub row on %d detail page(s)", len(done))
    return {"pages": done, "tabs": total, "skipped": skipped}


__all__ = ["inject_subresource_tabs"]
