"""Post-generate patch: apply ``plan.hints`` directives to page schemas.

Slice 1 of the requirement-as-central-piece direction. The parser
(``services.plan_directive_parser``) extracts structured directives
from the user's prompt and writes them to ``plan.hints``. Nothing else
in the pipeline actually reads them. This module closes that loop:

  ▸ ``hints.row_click_target``    → override Table.rowHref where a
                                     matching page exists.
  ▸ ``hints.filter_dimensions``   → prepend a FilterBar with real
                                     dimension names on the page whose
                                     route ends with the target's entity
                                     path.

Runs as a post-gen pass so it doesn't need plumbing into every
composer's function signature — read the finished schema, patch it,
write it back. Idempotent per schema (marker on root props).
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_MARKER = "data-hints-applied"


def _slug_from_route(route: str) -> str:
    """``/subscriptions/[id]`` → ``subscriptions``. First non-param segment."""
    parts = [p for p in route.split("/") if p and not p.startswith("[")]
    return parts[0] if parts else ""


def _walk(node: Any):
    if isinstance(node, dict):
        yield node
        for c in node.get("children") or []:
            yield from _walk(c)
    elif isinstance(node, list):
        for c in node:
            yield from _walk(c)


def _dim_to_chip(dim: str) -> dict:
    """Turn a raw dimension name into a FilterBar chip. Options are empty
    on purpose — the runtime slice that reads column-enum-values will
    fill them; today just having the correct SHAPE prevents the
    "Vinyasa: Any ▾" broken-chip render class we hit earlier.
    """
    key = re.sub(r"[^a-z0-9]+", "_", dim.lower()).strip("_")
    return {"key": key or "filter", "label": dim, "options": []}


def apply_hints_to_pages(output_dir: str | Path) -> dict[str, Any]:
    """Walk every page schema and apply hints from plan.hints. Returns
    ``{"patched": N, "row_click": N, "filter_bar": N}``. Never raises.
    """
    root = Path(output_dir)
    plan_path = root / "src" / "contracts" / "plan.json"
    if not plan_path.is_file():
        return {"patched": 0, "row_click": 0, "filter_bar": 0}
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[apply-hints] plan unreadable: %s", exc)
        return {"patched": 0, "row_click": 0, "filter_bar": 0}
    hints = plan.get("hints") if isinstance(plan.get("hints"), dict) else {}
    # Fallback: plan.hints often gets clobbered by later plan-persist
    # passes that rewrite plan.json without preserving keys. requirement.json
    # is the authoritative source (Slice 2) and carries the same parsed
    # directives — read from it when plan.hints is missing / partial.
    try:
        req_path = root / "src" / "contracts" / "requirement.json"
        if req_path.is_file():
            req = json.loads(req_path.read_text(encoding="utf-8"))
            req_parsed = req.get("parsed_directives") if isinstance(req.get("parsed_directives"), dict) else {}
            # Fold amendments — most recent wins (same rule the critic uses).
            for a in req.get("amendments") or []:
                if isinstance(a, dict) and isinstance(a.get("parsed_directives"), dict):
                    req_parsed = {**req_parsed, **a["parsed_directives"]}
            # requirement takes priority when plan.hints is missing the key.
            merged: dict = {**req_parsed, **hints}
            hints = merged
    except Exception:  # noqa: BLE001
        pass
    if not hints:
        return {"patched": 0, "row_click": 0, "filter_bar": 0}

    row_target = hints.get("row_click_target") if isinstance(hints.get("row_click_target"), str) else ""
    filter_dims = hints.get("filter_dimensions") if isinstance(hints.get("filter_dimensions"), list) else []
    target_slug = _slug_from_route(row_target) if row_target else ""

    sdir = root / "src" / "schemas"
    if not sdir.is_dir():
        return {"patched": 0, "row_click": 0, "filter_bar": 0}

    patched = row_click_count = filter_bar_count = 0
    for path in sorted(sdir.rglob("*.json")):
        if path.name in ("shell.json", "nav-flow.json"):
            continue
        try:
            schema = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        route = str(schema.get("route") or "")
        if not route:
            continue
        # Only touch primary collection routes (the target's entity list).
        # Detail / new / edit routes are out of scope for row-click + filters.
        page_slug = _slug_from_route(route)
        is_target_collection = (
            target_slug and page_slug == target_slug and
            "/[" not in route and "/new" not in route and "/edit" not in route
        )
        if not is_target_collection and not (filter_dims and page_slug):
            continue

        root_node = schema.get("root")
        if not isinstance(root_node, dict):
            continue
        # Idempotency: skip if already patched by this pass.
        if (root_node.get("props") or {}).get(_MARKER):
            continue

        touched = False

        # ── 1b — row-click override ─────────────────────────────────
        if is_target_collection and row_target:
            for node in _walk(root_node):
                if node.get("type") == "Table":
                    props = node.setdefault("props", {})
                    # Convert /x/[id] template → /x/{id} for the runtime.
                    href = row_target.replace("[id]", "{id}")
                    if props.get("rowHref") != href:
                        props["rowHref"] = href
                        touched = True
                        row_click_count += 1
                    break  # first Table wins

        # ── 1c — FilterBar seeded with real dimension names ────────
        if is_target_collection and filter_dims:
            # Skip when a FilterBar already exists (LLM composer path).
            has_filterbar = any(n.get("type") == "FilterBar" for n in _walk(root_node))
            if not has_filterbar:
                chips = [_dim_to_chip(d) for d in filter_dims]
                fb_node = {
                    "type": "FilterBar",
                    "props": {"showSearch": True, "chips": chips},
                }
                children = root_node.setdefault("children", [])
                # Insert after the first Heading/Row (hero band) if present,
                # else at the top.
                insert_at = 0
                if children and isinstance(children[0], dict):
                    first_type = children[0].get("type")
                    if first_type in ("Row", "Heading", "Hero", "Container"):
                        insert_at = 1
                children.insert(insert_at, fb_node)
                touched = True
                filter_bar_count += 1

        if touched:
            root_node.setdefault("props", {})[_MARKER] = "1"
            try:
                path.write_text(json.dumps(schema, indent=2), encoding="utf-8")
                patched += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("[apply-hints] write failed %s: %s", path, exc)

    if patched:
        logger.info("[apply-hints] patched %d page(s): row_click=%d, filter_bar=%d",
                    patched, row_click_count, filter_bar_count)
    return {"patched": patched, "row_click": row_click_count,
            "filter_bar": filter_bar_count}


__all__ = ["apply_hints_to_pages"]
