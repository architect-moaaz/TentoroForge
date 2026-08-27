"""Keep the border language of surface containers coherent per design register.

Each design register (workday, linear, stripe, notion, figma) ships its own
MetricTile / Card / Section variants with a deliberate, self-consistent border
language — e.g. workday is *sharp* (no radius) + hard border, notion is soft +
rounded. Corner radius and border weight are STRUCTURAL: they belong to the
register, not to any individual node (same principle as spec-derived structural
tokens — see design_compiler.derive_structural_tokens).

The page LLM, however, sometimes hangs a per-node `style.radius` (or explicit
`style.border*`) on *some* containers and not others — e.g. it rounds the three
"Claims by Status" cards to radius.lg while the KPI MetricTiles beside them stay
sharp. The page then shows two competing border shapes side by side.

This guard strips those per-node structural border overrides from surface
containers so the register variant governs — one coherent border language across
every container on the page. Semantic fills (`style.background`, e.g. a green
"approved" tint) and layout (`padding`, `gap`) are preserved; only border SHAPE
and WEIGHT are handed back to the register. Deterministic + idempotent.
"""
from __future__ import annotations

import glob

from services.artifact_authority import should_assert_only_any
import json
import os

from services.semantic_field_types import _iter_nodes

# Container / surface node types whose border shape is owned by the register.
# Leaf + interactive components (Button, Avatar, Badge, Input, Icon…) are left
# alone — their radius is intrinsic (a pill button, a round avatar) and not part
# of the page's container border language.
_SURFACE_TYPES = frozenset({
    "Card", "Table", "Section", "Panel", "InspectorPanel", "MetricTile", "Stat",
    "List", "DescriptionList", "KeyValueList", "Kanban", "Calendar", "Timeline",
    "ResourceTimeline", "Tabs", "ActivityFeed", "Banner", "ApprovalStepper",
    "DataTable", "Chart",
})

# Structural border keys handed back to the register. `background`, `padding`,
# `gap`, `shadow`, etc. are intentionally NOT here — those stay author-controlled.
_STRIP_KEYS = ("radius", "border", "borderColor", "borderWidth", "borderStyle")


def _strip_node_border(node: dict) -> int:
    style = node.get("style")
    if not isinstance(style, dict):
        return 0
    removed = 0
    for k in _STRIP_KEYS:
        if k in style:
            style.pop(k, None)
            removed += 1
    if not style:  # don't leave an empty style dict behind
        node.pop("style", None)
    return removed


def harmonize_surface_borders(output_dir: str) -> dict:
    """Strip per-node structural border overrides from surface containers so the
    register owns one coherent border language. Returns {stripped, nodes, files}."""
    sdir = os.path.join(output_dir, "src", "schemas")
    if not os.path.isdir(sdir):
        return {"stripped": 0, "nodes": 0, "files": 0, "asserts_logged": 0}

    stripped = nodes = touched = asserts_logged = 0
    for fp in glob.glob(os.path.join(sdir, "**", "*.json"), recursive=True):
        try:
            schema = json.load(open(fp, encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(schema, dict):
            continue
        # Composer-authored pages are ASSERT-only: the composer's decision is the
    # authority, so log drift instead of rewriting it.
        if should_assert_only_any(schema):
            asserts_logged += 1
            continue
        file_removed = 0
        for node in _iter_nodes(schema):
            if not isinstance(node, dict) or node.get("type") not in _SURFACE_TYPES:
                continue
            n = _strip_node_border(node)
            if n:
                file_removed += n
                nodes += 1
        if file_removed:
            touched += 1
            stripped += file_removed
            with open(fp, "w", encoding="utf-8") as fh:
                json.dump(schema, fh, indent=2)
    return {"stripped": stripped, "nodes": nodes, "files": touched,
            "asserts_logged": asserts_logged}
