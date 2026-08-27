"""Ensure dashboard pages have enough content that they don't render "bare".

Root cause this addresses: the deterministic dashboard builder emits the
minimum-viable widget set (whatever the plan declares). When the plan is
skimpy — e.g. one Stat and one Chart — the rendered page has vast blank
space with a hero and two tiles. B-022.10's "Dashboard UI is bare" report
is exactly this.

Fix: a post-gen top-up pass. If a dashboard page has fewer than N useful
content sections, append a standard set of "signal" sections drawn from
registered library components and bound to the plan's actual entities.
Never invents entities or bindings — only composes what's already there.

Rules (not-a-bandaid):
  * Deterministic — same plan → same output.
  * Additive — never removes user-authored content.
  * Uses only registered library components (MetricTile / Stat / Card /
    Table / Row / Grid / Heading / ActivityFeed).
  * Idempotent — running twice creates no duplicates. Uses `_id`s so a
    second run can identify sections it already added.
  * Conservative — only touches pages whose `type` is dashboard (or
    whose route is `/` / `/dashboard` / `/home`).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Minimum number of usable content nodes a dashboard should have before we
# consider it "populated enough". Below this, the top-up pass kicks in.
_MIN_SECTIONS = 3

# Marker prefix so re-runs can identify their own additions and not duplicate.
_MARKER = "b022_10_dashboard_topup"

# Node types that count as "content" (not chrome). Empty pages tend to be
# just Heading + Text + Card; those don't count on their own.
_CONTENT_TYPES: frozenset[str] = frozenset({
    "Stat", "MetricTile", "Chart", "Table", "DataGrid", "List",
    "Kanban", "ResourceTimeline", "ActivityFeed", "Timeline",
    "Gauge", "Heatmap", "Schematic", "Stepper",
    "DescriptionList", "KeyValueList", "SplitArc",
    "Calendar", "Carousel",
})


# --------------------------------------------------------------------------
# helpers                                                                    #
# --------------------------------------------------------------------------

def _load_plan(root: Path) -> dict:
    for c in (root / "src" / "contracts" / "plan.json", root / "contracts" / "plan.json"):
        if c.exists():
            try:
                return json.loads(c.read_text(encoding="utf-8"))
            except Exception:
                logger.exception("dashboard_completeness: failed to read %s", c)
    return {}


def _slug_from_route(route: str) -> str:
    r = (route or "").strip("/").replace("/", "-").replace("[", "").replace("]", "")
    return r or "home"


def _iter_nodes(root: Any):
    if isinstance(root, dict):
        yield root
        for v in root.values():
            yield from _iter_nodes(v)
    elif isinstance(root, list):
        for item in root:
            yield from _iter_nodes(item)


def _count_content_nodes(page_schema: dict) -> int:
    n = 0
    for node in _iter_nodes(page_schema):
        if isinstance(node, dict) and node.get("type") in _CONTENT_TYPES:
            n += 1
    return n


def _has_topup_marker(page_schema: dict) -> bool:
    for node in _iter_nodes(page_schema):
        if isinstance(node, dict) and node.get("_id", "").startswith(_MARKER):
            return True
    return False


def _is_dashboard_page(plan_page: dict) -> bool:
    if not isinstance(plan_page, dict):
        return False
    t = str(plan_page.get("type") or plan_page.get("archetype") or "").lower()
    if t == "dashboard":
        return True
    r = str(plan_page.get("route") or "").strip().rstrip("/")
    return r in ("", "/", "/dashboard", "/home", "/overview")


def _primary_entities(plan: dict) -> list[str]:
    """Entity names that make sense as dashboard KPIs. Skips lookup/system
    entities."""
    entities = plan.get("entities")
    if not isinstance(entities, dict):
        return []
    _SKIP = {"user", "users", "role", "roles", "auth", "session", "sessions",
             "audit", "auditlog", "audit_log", "log", "logs",
             "notification", "notifications", "workflow_task", "workflow_tasks"}
    out: list[str] = []
    for name in entities.keys():
        if not isinstance(name, str):
            continue
        if name.strip().lower() in _SKIP:
            continue
        out.append(name)
    return out


def _label(name: str) -> str:
    """CamelCase → 'Camel Case'; snake_case → 'Snake Case'."""
    if not name:
        return name
    s = name.replace("_", " ").replace("-", " ")
    import re as _re
    s = _re.sub(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", s)
    return " ".join(p[:1].upper() + p[1:] for p in s.split() if p)


def _table_slug(name: str) -> str:
    """Guess the dataSource slug — plural lowercased. Matches how the
    schema pipeline names its resources. Conservative; the schema author
    can override by leaving the source as-is."""
    lc = name.lower()
    if lc.endswith("y") and len(lc) > 1 and lc[-2] not in "aeiou":
        return lc[:-1] + "ies"
    if lc.endswith(("s", "x", "z", "ch", "sh")):
        return lc + "es"
    return lc + "s"


# --------------------------------------------------------------------------
# top-up composers                                                           #
# --------------------------------------------------------------------------

def _make_kpi_row(entities: list[str]) -> dict:
    """Row of MetricTile counts for up to 4 primary entities."""
    from services.text_templates import entity_label_plural
    tiles: list[dict] = []
    for i, e in enumerate(entities[:4]):
        tiles.append({
            "_id": f"{_MARKER}_kpi_{i}",
            "type": "MetricTile",
            "props": {
                "label": f"Total {entity_label_plural(e)}",
                "value": f"{{{{aggregate.{_table_slug(e)}.count}}}}",
                "format": "number",
            },
        })
    return {
        "_id": f"{_MARKER}_kpi_row",
        "type": "Row",
        "props": {"gap": "md"},
        "children": tiles,
    }


def _make_recent_items(entity: str) -> dict:
    """Card + Table of most-recent rows from the flagship entity."""
    slug = _table_slug(entity)
    return {
        "_id": f"{_MARKER}_recent_{entity.lower()}",
        "type": "Card",
        "props": {"title": f"Recent {_label(entity)}"},
        "children": [{
            "type": "Table",
            "props": {
                "dataSource": slug,
                "columns": [],
                "pageSize": 5,
                "emptyText": f"No {slug} yet.",
            },
        }],
    }


def _make_quick_actions(entities: list[str]) -> dict:
    """Row of Create buttons for the top primary entities."""
    buttons: list[dict] = []
    for i, e in enumerate(entities[:3]):
        buttons.append({
            "_id": f"{_MARKER}_qa_{i}",
            "type": "Button",
            "props": {
                "text": f"Create {_label(e)}",
                "variant": "primary" if i == 0 else "outline",
                "navigate": f"/{_table_slug(e)}/new",
            },
        })
    return {
        "_id": f"{_MARKER}_quick_actions",
        "type": "Row",
        "props": {"gap": "sm", "align": "center"},
        "children": buttons,
    }


def _make_section_heading(text: str, suffix: str) -> dict:
    return {
        "_id": f"{_MARKER}_heading_{suffix}",
        "type": "Heading",
        "props": {"content": text, "level": 3},
    }


# --------------------------------------------------------------------------
# main pass                                                                  #
# --------------------------------------------------------------------------

def apply_dashboard_completeness(output_dir: str) -> dict:
    root = Path(output_dir)
    plan = _load_plan(root)
    result: dict = {"pages_touched": [], "sections_added": 0, "asserts_logged": 0}
    if not plan.get("pages"):
        return result
    schemas_dir = root / "src" / "schemas"
    if not schemas_dir.exists():
        return result

    # Phase 3 (Dashboard Authority) — composer-authored schemas run in
    # ASSERT-only mode; log the fact and skip the top-up. The composer's
    # output is the authority and completeness's mechanical top-up would
    # only add noise on top of an already-designed dashboard.
    from services.dashboard_authority import should_assert_only

    primary = _primary_entities(plan)

    for page in plan.get("pages") or []:
        if not _is_dashboard_page(page):
            continue
        route = page.get("route") or "/"
        slug = _slug_from_route(route)
        schema_path = schemas_dir / f"{slug}.json"
        if not schema_path.exists():
            continue
        try:
            doc = json.loads(schema_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        # Assert-only mode wins over everything else — the composer wrote
        # this schema and completeness shouldn't second-guess it.
        if should_assert_only(doc):
            current_count = _count_content_nodes(doc)
            if current_count < _MIN_SECTIONS:
                logger.info(
                    "[dashboard-completeness] ASSERT %s: composer-authored "
                    "schema has %d content node(s) (< %d); leaving as-is "
                    "(dashboard authority)",
                    schema_path.name, current_count, _MIN_SECTIONS,
                )
                result["asserts_logged"] += 1
            continue

        # Skip if this page already carries our top-up marker (idempotency).
        if _has_topup_marker(doc):
            continue

        # Recipe-composed pages are USUALLY authoritative — but only when they
        # actually produced content. When `build_recipe_page` drops unimplemented
        # anchors (impl_status != "v1"), a recipe-marked dashboard can ship with
        # a single tile and nothing else — that's the case captured in
        # output/zg2d7vag (only a "0 Upcoming Classes" MetricTile). Trust the
        # recipe if it hit the content floor; otherwise fall through to the
        # top-up so the user gets a usable dashboard.
        if isinstance(doc, dict) and \
           isinstance(doc.get("meta"), dict) and \
           doc["meta"].get("recipe"):
            recipe_content = _count_content_nodes(doc)
            if recipe_content >= _MIN_SECTIONS:
                logger.debug(
                    "[dashboard-completeness] trusting recipe on %s — "
                    "meta.recipe=%s, content=%d (>= %d)",
                    slug, doc["meta"].get("recipe"), recipe_content, _MIN_SECTIONS,
                )
                continue
            logger.info(
                "[dashboard-completeness] recipe %s left %s sparse "
                "(content=%d < %d) — running top-up",
                doc["meta"].get("recipe"), slug, recipe_content, _MIN_SECTIONS,
            )

        # Sprint 2 — Designer-authored pages skip completeness top-up.
        # When the Design Context Pack primed the authoring turn, the LLM
        # composed the page as a designer (hero, hierarchy, empty states)
        # and this pass would silently rewrite that composition to hit a
        # widget-count floor. Trust the Designer; let a real design critic
        # (Sprint 3) flag insufficient dashboards instead of a mechanical
        # completeness top-up here.
        if isinstance(doc, dict) and doc.get("_designer_authored") is True:
            logger.debug(
                "[dashboard-completeness] skipping %s — schema is "
                "designer-authored (marker present)", slug,
            )
            continue

        current = _count_content_nodes(doc)
        if current >= _MIN_SECTIONS:
            continue  # already populated enough

        # Cannot use `or` here — an empty list is falsy and would fall
        # through to children, missing the top-up completely.
        nodes = doc["nodes"] if isinstance(doc.get("nodes"), list) else \
                doc["children"] if isinstance(doc.get("children"), list) else None
        if nodes is None:
            continue

        # Determine what to add based on primary entities available.
        added = 0
        if primary:
            # KPI row across up to 4 primary entities.
            nodes.append(_make_section_heading("Overview", "overview"))
            nodes.append(_make_kpi_row(primary))
            added += 2
            # Quick actions row.
            nodes.append(_make_section_heading("Quick actions", "quick"))
            nodes.append(_make_quick_actions(primary))
            added += 2
            # Recent items card for the flagship entity.
            nodes.append(_make_recent_items(primary[0]))
            added += 1

        if not added:
            continue

        # Preserve pointer (nodes vs children).
        if "nodes" in doc:
            doc["nodes"] = nodes
        else:
            doc["children"] = nodes

        try:
            schema_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
            result["pages_touched"].append(schema_path.name)
            result["sections_added"] += added
        except Exception:
            logger.exception("dashboard_completeness: failed to write %s", schema_path)

    return result
