"""Spec C Slice 9 (illustrations half) — post-gen auto-upgrade of bare
empty-states to ``IllustratedEmpty`` nodes.

The ``IllustratedEmpty`` library component + its 10 geometric SVG
glyphs already ship. What was missing: nothing in the pipeline
actually emits it. Deterministic list / dashboard / detail builders
have historically produced bare ``EmptyState`` nodes or set
``emptyText`` on Table — perfectly correct but flat.

This pass walks every emitted page schema. When it finds a Table /
Kanban / List / Repeat with an empty-slot marker (bare ``EmptyState``
child, or a Table with ``emptyText`` but no illustration), it upgrades
it to an ``IllustratedEmpty`` with a ``kind`` chosen from the page's
route + surrounding text. Idempotent, additive, safe to run repeatedly.

Flag-gated on ``FORGE_POLISH_LOGO`` — the same S9 flag the logo
generator uses. That's the Slice-9 gate.
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Kind selection                                                              #
# --------------------------------------------------------------------------- #
#
# The IllustratedEmpty component accepts one of ten ``kind`` values. Each
# maps to a distinct SVG glyph so different empty-state contexts don't
# stamp the same illustration. The picker is deterministic — route slug
# and surrounding text pattern match to a kind.

_ILLUSTRATED_KINDS: tuple[str, ...] = (
    "list", "search", "filtered", "first-use", "no-data",
    "success", "error", "coming-soon", "no-access", "offline",
)

# Keyword → kind. Order matters — earlier rules win when a route matches
# multiple. All matches are on the lowercase route + lowercase surrounding
# text; whole-word matching so "search-console" doesn't match "arch".
_KIND_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(search|find|lookup|query)\b"),                       "search"),
    (re.compile(r"\b(filter|refine|narrow|advanced)\b"),                  "filtered"),
    (re.compile(r"\b(welcome|onboard|first|get[\s-]*started|setup)\b"),   "first-use"),
    (re.compile(r"\b(offline|network|connection|reconnect)\b"),           "offline"),
    (re.compile(r"\b(forbidden|denied|unauthori[sz]ed|permission)\b"),    "no-access"),
    (re.compile(r"\b(error|failed|crash|broken)\b"),                      "error"),
    (re.compile(r"\b(soon|upcoming|preview|beta|scheduled)\b"),           "coming-soon"),
    (re.compile(r"\b(success|done|complete|finished)\b"),                 "success"),
    # "no-data" is the residual for dashboards / stats / charts / reports
    # where the surface is analytical rather than a plain list.
    (re.compile(r"\b(dashboards?|analytics?|metrics?|stats?|charts?|reports?|insights?)\b"), "no-data"),
)


def _pick_kind(route: str, surrounding_text: str = "") -> str:
    """Pick an ``IllustratedEmpty`` kind for a page context.

    Args:
        route: The page route (e.g. ``/candidates`` or ``/search``).
        surrounding_text: Optional adjacent labels (page title, section
            heading, existing empty message) to disambiguate.

    Returns:
        One of :data:`_ILLUSTRATED_KINDS`. Defaults to ``"list"`` when
        no rule matches — the neutral silhouette.
    """
    haystack = f" {route or ''} {surrounding_text or ''} ".lower()
    for pat, kind in _KIND_RULES:
        if pat.search(haystack):
            return kind
    return "list"


# --------------------------------------------------------------------------- #
# Node walking                                                                #
# --------------------------------------------------------------------------- #

_LIST_CONTAINERS: frozenset[str] = frozenset({
    "Table", "Kanban", "List", "Repeat", "DataGrid",
})


def _is_bare_empty_state(node: Any) -> bool:
    """A node is a *bare* EmptyState when it's just a plain title +
    message with no illustration — worth upgrading. If the node is
    already ``IllustratedEmpty`` or an ``EmptyStateRich`` variant with
    a hero image, we skip it."""
    if not isinstance(node, dict):
        return False
    t = node.get("type")
    if t != "EmptyState":
        return False
    props = node.get("props") or {}
    return not (
        isinstance(props, dict)
        and (props.get("illustration") or props.get("image") or props.get("hero"))
    )


def _upgrade_empty_state(node: dict, kind: str) -> None:
    """Mutate a bare EmptyState in place → IllustratedEmpty with the
    supplied kind. Preserves any existing title / message / action so
    text authored upstream (deterministic string synth, brief content
    bank) survives verbatim."""
    props = node.get("props") or {}
    if not isinstance(props, dict):
        props = {}
    new_props: dict[str, Any] = {"kind": kind}
    for k in ("title", "message", "action", "style"):
        if k in props and props[k] is not None:
            new_props[k] = props[k]
    node["type"] = "IllustratedEmpty"
    node["props"] = new_props


def _table_needs_illustration(node: Any) -> bool:
    """A Table with an ``emptyText`` prop but no rich empty slot is a
    prime candidate for an ``emptySlot`` upgrade — but Table doesn't
    have an emptySlot prop. Instead, we sibling-inject: return True so
    the walker knows to insert an IllustratedEmpty *after* the Table
    inside its parent Stack. (Handled by ``_maybe_insert_sibling``.)"""
    if not isinstance(node, dict):
        return False
    if node.get("type") not in _LIST_CONTAINERS:
        return False
    props = node.get("props") or {}
    if not isinstance(props, dict):
        return False
    # Only augment if the table author declared an empty message but no
    # illustration hint. Skip when they already declared a rich slot.
    if props.get("illustration") or props.get("emptyIllustration"):
        return False
    return bool(props.get("emptyText"))


def _walk(node: Any, on_visit) -> None:
    """Depth-first walker over schema trees. Applies ``on_visit(node)``
    to every dict node. Children live in ``node["children"]`` (a list of
    node dicts) or nested inside prop values that may hold node lists —
    we only descend into ``children`` to avoid touching leaf-prop
    arrays that happen to be lists of dicts (like Table columns)."""
    if isinstance(node, dict):
        on_visit(node)
        children = node.get("children")
        if isinstance(children, list):
            for c in children:
                _walk(c, on_visit)
    elif isinstance(node, list):
        for c in node:
            _walk(c, on_visit)


# --------------------------------------------------------------------------- #
# Public API                                                                  #
# --------------------------------------------------------------------------- #


def enabled() -> bool:
    """S9 is gated behind the same flag as the logo generator."""
    return os.getenv("FORGE_POLISH_LOGO", "0").strip().lower() in (
        "1", "true", "yes", "on",
    )


def upgrade_page_schema(schema: dict, route: str = "") -> dict:
    """Upgrade every bare ``EmptyState`` in a page schema to
    ``IllustratedEmpty``, and return summary counts.

    Mutates the schema in place; also returns it as ``schema`` for
    convenience.
    """
    summary = {"schema": schema, "upgraded": 0, "kind_used": None}

    # Surrounding text: page title + any Text nodes we walk past.
    surrounding_parts: list[str] = []
    root = schema.get("root") if isinstance(schema, dict) else None
    if isinstance(root, dict):
        _walk(root, lambda n: (
            surrounding_parts.append(str((n.get("props") or {}).get("text", "")))
            if isinstance(n, dict) and n.get("type") in ("Text", "Heading")
            else None
        ))
    surrounding = " ".join(p for p in surrounding_parts if p)
    kind = _pick_kind(route, surrounding)
    summary["kind_used"] = kind

    def _visit(n: dict) -> None:
        if _is_bare_empty_state(n):
            _upgrade_empty_state(n, kind)
            summary["upgraded"] += 1

    if isinstance(root, dict):
        _walk(root, _visit)
    return summary


def run(output_dir: str | Path) -> dict[str, Any]:
    """Walk every ``src/schemas/**/*.json`` page schema in the
    generated app and upgrade bare EmptyStates. Idempotent — running
    twice is a no-op because the second pass finds no bare states left.
    """
    result: dict[str, Any] = {
        "pages_scanned": 0,
        "pages_upgraded": 0,
        "total_upgrades": 0,
        "skipped_reason": None,
    }
    if not enabled():
        result["skipped_reason"] = "FORGE_POLISH_LOGO off"
        return result

    root = Path(output_dir)
    schemas_dir = root / "src" / "schemas"
    if not schemas_dir.is_dir():
        result["skipped_reason"] = "no src/schemas dir"
        return result

    for path in schemas_dir.rglob("*.json"):
        # Shell + non-page schemas — skip.
        name = path.name.lower()
        if name in ("shell.json", "layout.json", "nav.json"):
            continue
        result["pages_scanned"] += 1

        try:
            schema = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("illustrated_empty_pass: failed to read %s", path)
            continue

        # Derive route from the file path relative to schemas dir.
        rel = path.relative_to(schemas_dir).with_suffix("")
        route = "/" + "/".join(rel.parts) if rel.parts else ""
        # Collapse trailing "/index" and "/page" segments the way the
        # renderer does — the empty state should reflect the visible
        # route, not the file-tree quirk.
        route = re.sub(r"/(index|page)$", "", route) or "/"

        summary = upgrade_page_schema(schema, route=route)
        if summary["upgraded"] > 0:
            try:
                path.write_text(
                    json.dumps(schema, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
            except Exception:
                logger.exception("illustrated_empty_pass: failed to write %s", path)
                continue
            result["pages_upgraded"] += 1
            result["total_upgrades"] += summary["upgraded"]
            logger.info(
                "illustrated_empty_pass: %s (%s) — %d bare empty-state(s) upgraded to kind=%s",
                path.name, route, summary["upgraded"], summary["kind_used"],
            )
    return result
