"""Spec C2 — Signature-move registry.

The brief carries a small list of ``signature_moves`` (kind + detail).
Each ``kind`` maps here to a pure ``(node, brief) -> node`` renderer +
an applicability predicate that decides which nodes the renderer
should mutate.

Add a move = one new file with a predicate + renderer + register()
call. Nothing else. No schema change, no spec change. The apply pass
walks page schemas, matches nodes by predicate, applies the renderer.

Unknown kinds in the brief are logged and skipped, never crash.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

log = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────
# Registry
# ────────────────────────────────────────────────────────────

Applicability = Callable[[dict[str, Any], dict[str, Any]], bool]
"""``(node, ctx) -> bool``. ``ctx`` is a shared dict — entities,
brief, current entity slug — so predicates can consult sibling info."""

Renderer = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]
"""``(node, ctx) -> node``. Returns a NEW dict (may mutate in-place
for simple prop additions — the apply pass doesn't rely on identity)."""


class MoveEntry:
    __slots__ = ("kind", "applies_to", "render", "description")

    def __init__(
        self,
        kind: str,
        applies_to: Applicability,
        render: Renderer,
        description: str = "",
    ) -> None:
        self.kind = kind
        self.applies_to = applies_to
        self.render = render
        self.description = description


_REGISTRY: dict[str, MoveEntry] = {}


def register(kind: str, applies_to: Applicability, render: Renderer,
             description: str = "") -> None:
    """Add a move kind to the registry. Overwrites on duplicate kind
    (last write wins — useful for tests, harmless otherwise)."""
    _REGISTRY[kind] = MoveEntry(kind, applies_to, render, description)


def get(kind: str) -> MoveEntry | None:
    return _REGISTRY.get(kind)


def known_kinds() -> list[str]:
    """The list handed to brief_author so it only emits registered kinds."""
    return sorted(_REGISTRY.keys())


def describe_all() -> list[dict[str, str]]:
    """LLM-prompt-friendly manifest. Each entry = {kind, description}."""
    return [{"kind": e.kind, "description": e.description}
            for e in sorted(_REGISTRY.values(), key=lambda x: x.kind)]


# ────────────────────────────────────────────────────────────
# Built-in moves — small starter set. Grows organically per Spec C2.
# ────────────────────────────────────────────────────────────

def _is_table_node(node: dict, ctx: dict) -> bool:
    return isinstance(node, dict) and node.get("type") in ("Table", "DataGrid")


def _is_card_wrapping_data(node: dict, ctx: dict) -> bool:
    if not isinstance(node, dict) or node.get("type") != "Card":
        return False
    for child in _flatten_children(node):
        t = child.get("type") if isinstance(child, child.__class__) else None
        if t in ("Table", "Stat", "Chart", "Kanban", "List", "DescriptionList"):
            return True
    return False


def _is_stat_node(node: dict, ctx: dict) -> bool:
    return isinstance(node, dict) and node.get("type") == "Stat"


def _flatten_children(node: dict):
    """Yield the node itself and every descendant (dict) in DFS order."""
    if isinstance(node, dict):
        yield node
        for v in node.values():
            if isinstance(v, list):
                for item in v:
                    yield from _flatten_children(item)
            elif isinstance(v, dict):
                yield from _flatten_children(v)


def _has_status_column(node: dict, ctx: dict) -> bool:
    """A Table whose columns include a status-family field."""
    if not _is_table_node(node, ctx):
        return False
    props = node.get("props") or {}
    cols = props.get("columns")
    if isinstance(cols, list):
        for c in cols:
            name = ""
            if isinstance(c, dict):
                name = str(c.get("field") or c.get("name") or "")
            elif isinstance(c, str):
                name = c
            low = name.lower()
            if low == "status" or low.endswith("status") or low.endswith("state"):
                return True
    return False


# ── ledger_row: 4px left-border on Table rows in a data-heavy card ──
def _render_ledger_row(node: dict, ctx: dict) -> dict:
    """Add rowStyle.borderLeft (brand-tinted) to a Table so rows look
    like ledger entries. Runtime Table honours arbitrary rowStyle props."""
    node.setdefault("props", {})
    row_style = node["props"].setdefault("rowStyle", {})
    row_style["borderLeft"] = "4px solid hsl(var(--primary) / 0.6)"
    row_style["paddingLeft"] = "12px"
    return node


register(
    "ledger_row",
    applies_to=_is_table_node,
    render=_render_ledger_row,
    description="4px brand-tinted left border on every Table row so lists "
                "read as ledger entries (property mgmt, finance, ops).",
)


# ── keyline_breadcrumb: hairline rule under any Heading level 1 ──
def _is_h1(node: dict, ctx: dict) -> bool:
    if not isinstance(node, dict) or node.get("type") != "Heading":
        return False
    props = node.get("props") or {}
    return props.get("level") in (1, "1", "h1")


def _render_keyline(node: dict, ctx: dict) -> dict:
    node.setdefault("props", {})
    style = node["props"].setdefault("style", {})
    style["borderBottom"] = "1px solid hsl(var(--border))"
    style["paddingBottom"] = "8px"
    return node


register(
    "keyline_breadcrumb",
    applies_to=_is_h1,
    render=_render_keyline,
    description="Hairline rule beneath H1 headings for a broadsheet feel.",
)


# ── velocity_sparkline: hint a Stat to render its trend as a sparkline ──
def _render_velocity_sparkline(node: dict, ctx: dict) -> dict:
    node.setdefault("props", {})
    node["props"].setdefault("trendVariant", "sparkline")
    return node


register(
    "velocity_sparkline",
    applies_to=_is_stat_node,
    render=_render_velocity_sparkline,
    description="Every Stat's trend renders as a compact sparkline "
                "(dashboards feel motion-aware, not static).",
)


# ── status_stripe: color-code a status-carrying Table with a stripe column ──
def _render_status_stripe(node: dict, ctx: dict) -> dict:
    node.setdefault("props", {})
    node["props"].setdefault("statusStripe", True)
    return node


register(
    "status_stripe",
    applies_to=_has_status_column,
    render=_render_status_stripe,
    description="Add a color stripe on rows of any Table with a status "
                "column so state is scannable without reading text.",
)


# ── card_elevation: subtle shadow on data cards (elevates them off bg) ──
def _render_card_elevation(node: dict, ctx: dict) -> dict:
    node.setdefault("props", {})
    node["props"].setdefault("variant", "elevated")
    return node


register(
    "card_elevation",
    applies_to=_is_card_wrapping_data,
    render=_render_card_elevation,
    description="Data-carrying Cards get an elevated shadow variant "
                "(playful/consumer briefs).",
)


# ── warm_serif_h1: swap H1 display font to the brief's display face ──
# Structural: brief.typography.display_family already reaches CSS; this
# move ensures the Heading node opts into the display class explicitly
# so shell headers reliably use it even when a page override intervenes.
def _render_warm_serif_h1(node: dict, ctx: dict) -> dict:
    node.setdefault("props", {})
    cls = str(node["props"].get("className") or "")
    if "font-display" not in cls:
        node["props"]["className"] = (cls + " font-display").strip()
    return node


register(
    "warm_serif_h1",
    applies_to=_is_h1,
    render=_render_warm_serif_h1,
    description="H1 uses the brief's display face (warm serif / display "
                "sans) with generous line-height. Editorial voice.",
)


__all__ = [
    "MoveEntry", "describe_all", "get", "known_kinds", "register",
]
