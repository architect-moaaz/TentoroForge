"""Flag / repair bare surface containers that render as blank space.

Root cause this addresses: LLM-authored schemas sometimes contain
Card / Section / Stack nodes with zero real content or with just a
Heading and no body — they take full surface width but render as
essentially empty rectangles. B-022.5's "blank spaces" symptom.

Fix: a small deterministic guard that:

  1. Removes truly-empty containers (no children AND no `content` prop).
  2. On a Card / Section with ONLY a Heading child, appends a subtle
     `EmptyState` with a machine-generated line so the surface reads
     as intentional ("Nothing here yet.") instead of dead.
  3. Applies to Section / Card / Cluster / Split shells.

Rules (not-a-bandaid):
  * Structural — reads schema nodes only. No LLM.
  * Additive — never removes user-authored content nodes.
  * Idempotent — running twice creates no duplicates. Uses an `_id`
    marker so re-runs identify their own additions.
  * Conservative — only touches surfaces the schema plainly left bare;
    a Card with children continues untouched.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from services.artifact_authority import should_assert_only_any
from typing import Any

logger = logging.getLogger(__name__)

# Marker so re-runs detect their own additions.
_MARKER = "b022_5_bare"

# Container node types that hold children. These are the surfaces we watch.
_CONTAINERS: frozenset[str] = frozenset({
    "Card", "Section", "Cluster", "Split", "Stack", "Row", "Grid", "Container",
})

# The "heading_only" rule is narrower than _CONTAINERS, and deliberately so.
#
# A Card or Section is a SURFACE: it paints a background and a border, so one
# holding nothing but a title really does render as a dead rectangle, which is
# what this guard exists to fix.
#
# Stack / Row / Grid / Container are invisible LAYOUT wrappers. A Stack whose
# only child is a Heading is ordinary chrome — a page title, a nav brand, a
# card header — and appending "Nothing here yet." to it states something false.
# On 6q7oqejv that is exactly what happened: the shell's brand Stack (logo +
# app title) got an EmptyState wedged in beside the app name in the header.
#
# Empty-container REMOVAL still applies to every type in _CONTAINERS; a truly
# childless Grid is junk whatever it is.
_SURFACE_CONTAINERS: frozenset[str] = frozenset({
    "Card", "Section", "Cluster", "Split",
})

# Schemas that are app chrome rather than page content. The shell holds the
# nav frame, brand and header slots — none of it is a content surface, and a
# guard written for page bodies has no business rewriting it.
_NON_PAGE_SCHEMAS: frozenset[str] = frozenset({"shell.json"})

# Content types that count as "real" — a Heading alone isn't enough to make
# a container non-bare.
_REAL_CONTENT: frozenset[str] = frozenset({
    "Text", "Image", "Chart", "Table", "DataGrid", "List", "Stat", "MetricTile",
    "Timeline", "ActivityFeed", "Gauge", "Heatmap", "Schematic", "Stepper",
    "DescriptionList", "KeyValueList", "SplitArc", "Kanban", "ResourceTimeline",
    "Calendar", "Carousel", "Form", "Button", "Link", "IconButton", "NavLink",
    "Alert", "Banner", "Badge", "Tag", "Input", "Select", "Textarea", "Checkbox",
    "Switch", "RadioGroup", "DatePicker", "FileUpload", "Rating",
    "Avatar", "Divider", "Progress", "Spinner", "EmptyState", "EmptyStateRich",
    "Combobox", "MultiSelect", "TimePicker", "ColorPicker", "InputOTP",
    "MaskedInput", "SegmentedControl", "Tree", "Transfer", "Cascader",
    "RichTextEditor", "Lightbox", "CodeBlock", "QRCode", "CameraCapture",
    "Scanner", "ValidationChecklist", "Tabs", "TabPanel", "Accordion",
    "AccordionPanel", "AddToCart", "CartBadge", "CartPanel", "CartPage",
})


# --------------------------------------------------------------------------
# helpers                                                                    #
# --------------------------------------------------------------------------

def _get_children(node: dict) -> list | None:
    """Prefer `children`, then `nodes`, then `items`. Returns the list ref
    or None if the container has no populated child list."""
    for key in ("children", "nodes", "items"):
        v = node.get(key)
        if isinstance(v, list):
            return v
    return None


def _child_types(children: list) -> list[str]:
    out: list[str] = []
    for c in children or []:
        if isinstance(c, dict) and c.get("type"):
            out.append(str(c.get("type")))
    return out


def _looks_bare(node: dict) -> str | None:
    """Return `"empty"` / `"heading_only"` / None. Only classifies
    containers — everything else returns None."""
    if not isinstance(node, dict):
        return None
    if node.get("type") not in _CONTAINERS:
        return None
    # A Card with a title prop AND no children is a decorative empty card —
    # still bare.
    children = _get_children(node)
    types = _child_types(children or [])
    if not children:
        # Container with no children. If it has a title/heading in its own
        # props we still show the chrome; otherwise it's truly empty.
        props = node.get("props") or {}
        has_title = bool(props.get("title")) or bool(props.get("heading"))
        return "empty_with_title" if has_title else "empty"
    real = [t for t in types if t in _REAL_CONTENT]
    if not real:
        # Only decorative children (Heading only, or dividers, etc.).
        # Restricted to painted surfaces — a layout wrapper around a title
        # is chrome, not a dead surface. See _SURFACE_CONTAINERS.
        if (node.get("type") in _SURFACE_CONTAINERS
                and all(t in ("Heading", "Divider", "Spacer") for t in types)):
            return "heading_only"
    return None


def _make_empty_state_child() -> dict:
    return {
        "_id": f"{_MARKER}_empty",
        "type": "EmptyState",
        "props": {"title": "Nothing here yet.", "message": ""},
    }


def _has_marker_child(children: list) -> bool:
    for c in children or []:
        if isinstance(c, dict) and str(c.get("_id", "")).startswith(_MARKER):
            return True
    return False


# --------------------------------------------------------------------------
# main pass                                                                  #
# --------------------------------------------------------------------------

def _walk_and_fix(nodes: list, result: dict) -> None:
    """Walk a list of nodes in place. For each bare container:
        * `heading_only` / `empty_with_title` → append EmptyState child.
        * `empty` (no props of interest) → mark for pruning by the caller.
    Returns via the shared `result` counters."""
    i = 0
    while i < len(nodes):
        n = nodes[i]
        if not isinstance(n, dict):
            i += 1
            continue

        # Recurse first so we fix from the leaves up.
        for key in ("children", "nodes", "items"):
            child_list = n.get(key)
            if isinstance(child_list, list):
                _walk_and_fix(child_list, result)

        state = _looks_bare(n)
        if state in ("heading_only", "empty_with_title"):
            children = _get_children(n)
            if children is None:
                # Container carries its title but has no child list — add one.
                n["children"] = [_make_empty_state_child()]
                result["empty_states_added"] += 1
            elif not _has_marker_child(children):
                children.append(_make_empty_state_child())
                result["empty_states_added"] += 1
            i += 1
            continue

        if state == "empty":
            # Nothing on it — prune the container entirely.
            nodes.pop(i)
            result["empty_removed"] += 1
            continue

        i += 1


def apply_bare_container_guard(output_dir: str) -> dict:
    root = Path(output_dir)
    result: dict = {"files_touched": [], "empty_removed": 0,
                    "empty_states_added": 0, "asserts_logged": 0}
    schemas_dir = root / "src" / "schemas"
    if not schemas_dir.exists():
        return result

    for schema_path in sorted(schemas_dir.glob("*.json")):
        if schema_path.name in _NON_PAGE_SCHEMAS:
            continue
        try:
            doc = json.loads(schema_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        # Composer-authored pages are ASSERT-only: the composer's decision is the
    # authority, so log drift instead of rewriting it.
        if should_assert_only_any(doc):
            result["asserts_logged"] += 1
            continue

        # Snapshot counters so we know if this file was touched.
        before = result["empty_removed"] + result["empty_states_added"]

        for key in ("children", "nodes"):
            top = doc.get(key)
            if isinstance(top, list):
                _walk_and_fix(top, result)

        if (result["empty_removed"] + result["empty_states_added"]) > before:
            try:
                schema_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
                result["files_touched"].append(schema_path.name)
            except Exception:
                logger.exception("bare_container_guard: failed to write %s", schema_path)

    return result
