"""Recursive walker over a Figma node tree.

Output: a flat list of {node, path, parent} entries with two normalisations:
  - Redundant single-child passthrough containers (Container/Frame/Group/Wrapper
    with no own fills/strokes/effects) are collapsed.
  - Auto-layout metadata (layoutMode, itemSpacing, paddings, alignments,
    layoutWrap) is surfaced onto every walked node under `_*` keys so
    downstream callers don't re-parse raw Figma fields.
"""
from __future__ import annotations

_LAYOUT_FIELDS = (
    "layoutMode", "itemSpacing",
    "paddingTop", "paddingRight", "paddingBottom", "paddingLeft",
    "primaryAxisAlignItems", "counterAxisAlignItems", "layoutWrap",
    # Sizing semantics — FIXED / FILL / HUG. Drives whether downstream
    # emits `w-[Npx]`, `flex-1`/`w-full`, or nothing on the schema node.
    "layoutSizingHorizontal", "layoutSizingVertical",
    # layoutGrow=1 is the historical equivalent of layoutSizingHorizontal=FILL
    # used by older Figma files.
    "layoutGrow",
)


def _is_passthrough_container(node: dict) -> bool:
    """A passthrough is a Container/Frame/Group/Wrapper with EXACTLY one
    child and NO own visual content."""
    if node.get("type") not in ("FRAME", "GROUP"):
        return False
    name = (node.get("name") or "").strip().lower()
    if name not in {"container", "frame", "group", "wrapper"}:
        return False
    children = node.get("children") or []
    if len(children) != 1:
        return False
    if node.get("fills"):   return False
    if node.get("strokes"): return False
    if node.get("effects"): return False
    return True


def _annotate(node: dict) -> dict:
    """Copy auto-layout fields onto stable `_*` keys."""
    out = dict(node)
    for f in _LAYOUT_FIELDS:
        if f in node:
            out[f"_{f}"] = node[f]
    return out


def _visual_sort_key(child: dict, parent_layout: str | None) -> float:
    """For an auto-layout parent, return the child's primary-axis coordinate.

    Figma's REST API mostly returns children in source-list order, but the
    source-list order is the layer-panel order — which the designer can
    arrange independently of visual order in a few edge cases:
      - Manual reordering in the layers panel after auto-layout was applied
      - Components whose default layer order differs from the override slot

    Sorting defensively by `absoluteBoundingBox.{x,y}` guarantees the schema
    children render in the order a user sees them on screen.
    """
    bbox = child.get("absoluteBoundingBox") or {}
    if parent_layout == "VERTICAL":
        return float(bbox.get("y") or 0)
    if parent_layout == "HORIZONTAL":
        return float(bbox.get("x") or 0)
    return 0.0


def walk_and_flatten(root: dict) -> list[dict]:
    """DFS walk. Skip passthrough containers but keep their children.

    Auto-layout VERTICAL / HORIZONTAL children are sorted by their bbox
    coordinate on the primary axis so the schema always reflects visual
    order regardless of the source layer-panel order in Figma.
    """
    if not root or not isinstance(root, dict):
        return []
    out: list[dict] = []

    def visit_children(node: dict) -> list[dict]:
        kids = list(node.get("children") or [])
        layout = node.get("layoutMode")
        if layout in ("VERTICAL", "HORIZONTAL") and len(kids) > 1:
            kids = sorted(kids, key=lambda c: _visual_sort_key(c, layout))
        return kids

    def go(node: dict, path: list[str], parent: dict | None) -> None:
        if _is_passthrough_container(node):
            for c in visit_children(node):
                go(c, path, parent)
            return
        ann = _annotate(node)
        out.append({"node": ann, "path": list(path) + [ann.get("id", "?")], "parent": parent})
        for c in visit_children(node):
            go(c, list(path) + [ann.get("id", "?")], ann)

    go(root, [], None)
    return out
