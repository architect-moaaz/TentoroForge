"""Post-generate guard: wrap bare data-display nodes in a padded Card.

The generator often drops a Table / Chart / list straight into a structural
container (Stack / Grid / Section) with no padded surface around it, so the
component renders flush against the container edges — content touching the
boundary. This guard wraps such a node in a Card (which supplies the border +
inner padding), but ONLY when it isn't already inside a padded surface, so it
never double-wraps a table that's already in a card.

Deterministic + idempotent (a wrapped node gains a Card ancestor, so a second
pass skips it). Best-effort — never raises.
"""
from __future__ import annotations

import glob
import json
import os

# Data-display components that should sit inside a padded surface, not flush.
_DATA_DISPLAYS = frozenset({
    "Table", "DataGrid", "Chart", "Sparkline", "List", "DescriptionList",
    "ActivityFeed", "Timeline",
})

# Components that already provide a padded surface — a descendant of one of these
# needs no extra Card.
_SURFACE_TYPES = frozenset({"Card", "PersonCard", "FeatureCard"})


def _wrap_children(node: dict, has_surface: bool) -> int:
    """Recurse `node`, wrapping bare data-display children in a Card. Returns the
    number of nodes wrapped. `has_surface` is True when an ancestor already
    provides a padded surface."""
    if not isinstance(node, dict):
        return 0
    surface_now = has_surface or node.get("type") in _SURFACE_TYPES
    wrapped = 0

    def process_list(arr: list) -> list:
        nonlocal wrapped
        out = []
        for child in arr:
            if (
                isinstance(child, dict)
                and child.get("type") in _DATA_DISPLAYS
                and not surface_now
            ):
                # Recurse into the child as if already carded, then wrap it.
                wrapped += _wrap_children(child, True)
                cid = child.get("id")
                card = {
                    "type": "Card",
                    "props": {"elevation": "sm"},
                    "children": [child],
                }
                if cid:
                    card["id"] = f"{cid}-surface"
                out.append(card)
                wrapped += 1
            else:
                wrapped += _wrap_children(child, surface_now)
                out.append(child)
        return out

    kids = node.get("children")
    if isinstance(kids, list):
        node["children"] = process_list(kids)

    slots = node.get("slots")
    if isinstance(slots, dict):
        for k, arr in slots.items():
            if isinstance(arr, list):
                slots[k] = process_list(arr)

    return wrapped


def wrap_bare_data_displays(output_dir: str) -> dict:
    """Wrap flush Table/Chart/list nodes in a padded Card across all page schemas.

    Returns {"wrapped": int, "files": int}.
    """
    sdir = os.path.join(output_dir, "src", "schemas")
    if not os.path.isdir(sdir):
        return {"wrapped": 0, "files": 0}

    # Phase 3 + Phase 6 authority — when the schema was written by ANY
    # composer whose flag is currently on (dashboard/collection/record),
    # this guard runs in ASSERT-only mode: log the count of nodes it
    # WOULD wrap without mutating. Composer's output is the authority.
    # ``should_assert_only_any`` covers all three artifact markers +
    # flags uniformly (see services.artifact_authority).
    from services.artifact_authority import should_assert_only_any as should_assert_only

    total = 0
    files = 0
    asserts_logged = 0
    for fp in glob.glob(os.path.join(sdir, "*.json")):
        try:
            with open(fp, encoding="utf-8") as fh:
                schema = json.load(fh)
        except Exception:
            continue
        root = schema.get("root")
        if not isinstance(root, dict):
            continue
        # The root itself is a structural container; its children have no surface.
        # Dry-run count first so authority mode can log without mutating.
        # We deep-copy root because _wrap_children mutates in place — the
        # dry-run must NOT touch the on-disk state.
        import copy
        would_wrap = _wrap_children(copy.deepcopy(root), False)
        if would_wrap and should_assert_only(schema):
            # Assert-only mode: log drift, don't mutate.
            import logging
            logging.getLogger(__name__).info(
                "[surface_wrap_guard] ASSERT %s: composer-authored schema "
                "would receive %d Card wrap(s); leaving as-is (dashboard authority)",
                os.path.basename(fp), would_wrap,
            )
            asserts_logged += 1
            continue
        n = _wrap_children(root, False)
        if n:
            total += n
            files += 1
            try:
                with open(fp, "w", encoding="utf-8") as fh:
                    json.dump(schema, fh, indent=2)
            except Exception:
                pass

    return {"wrapped": total, "files": files, "asserts_logged": asserts_logged}
