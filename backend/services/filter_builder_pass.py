"""filter_builder_pass — Spec E Wave 3 (advanced UX patterns).

When the planner declares ``page.list.filter_fields`` on a list page,
this deterministic post-gen pass injects a ``FilterBuilder`` node
above the page's primary ``Table`` and wires the URL param through
the data-source so refreshes carry the filter query.

Flag-gated on ``FORGE_E_PATTERNS`` — no-op unless the operator opts
in. Additive + idempotent: safe to re-run.

Design notes
------------
* The FilterBuilder serialises its expression to a URL query param
  (default ``filter``). The runtime's data hook reads that param and
  the API's `/api/data/[...path]` handler already accepts a
  ``filter`` query on list endpoints, so no route work is needed —
  the FilterBuilder just needs to exist above the Table.
* We do NOT touch a page that already contains a FilterBuilder or a
  FilterBar — that would double-render the same affordance.
* We do NOT overwrite the plan's ``filter_fields`` — the sanitiser
  in ``agents.planner`` already normalised them.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)


def is_enabled() -> bool:
    return os.getenv("FORGE_E_PATTERNS", "0").strip().lower() in {
        "1", "true", "yes", "on",
    }


def _iter_nodes(node: Any) -> Iterable[dict]:
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _iter_nodes(v)
    elif isinstance(node, list):
        for v in node:
            yield from _iter_nodes(v)


def _has_filter_builder(schema: dict) -> bool:
    for n in _iter_nodes(schema):
        if isinstance(n, dict) and n.get("type") in ("FilterBuilder", "FilterBar"):
            return True
    return False


def _first_table_parent(root: Any) -> tuple[dict | None, int]:
    """Find the immediate parent that CONTAINS a Table in its children,
    plus the Table's index in that container.

    Only descends into dicts / lists of dicts — bail early on unknown
    shapes to keep the traversal cheap. Returns (None, -1) when no
    Table exists in the tree.
    """
    if isinstance(root, dict):
        children = root.get("children")
        if isinstance(children, list):
            for i, child in enumerate(children):
                if isinstance(child, dict) and child.get("type") == "Table":
                    return root, i
            for child in children:
                parent, idx = _first_table_parent(child)
                if parent is not None:
                    return parent, idx
    elif isinstance(root, list):
        for item in root:
            parent, idx = _first_table_parent(item)
            if parent is not None:
                return parent, idx
    return None, -1


def _build_filter_builder_node(filter_fields: list[dict], param_key: str) -> dict:
    return {
        "type": "FilterBuilder",
        "props": {
            "fields": filter_fields,
            "paramKey": param_key,
        },
    }


def _apply_to_schema_file(schema_path: Path) -> bool:
    try:
        raw = schema_path.read_text(encoding="utf-8")
        schema = json.loads(raw)
    except Exception:
        return False
    if not isinstance(schema, dict):
        return False
    if _has_filter_builder(schema):
        return False

    plist = schema.get("list") if isinstance(schema.get("list"), dict) else None
    if not plist:
        return False
    ff = plist.get("filter_fields")
    if not (isinstance(ff, list) and ff):
        return False

    param_key = "filter"
    fb_node = _build_filter_builder_node(ff, param_key)

    # Prefer to inject above the Table's immediate parent container.
    root = schema.get("root")
    if root is None:
        # Top-level component list variants.
        for key in ("components", "nodes"):
            arr = schema.get(key)
            if isinstance(arr, list):
                # Insert before the first Table entry, else at position 0.
                idx = 0
                for i, n in enumerate(arr):
                    if isinstance(n, dict) and n.get("type") == "Table":
                        idx = i
                        break
                arr.insert(idx, fb_node)
                _annotate(schema)
                _write(schema_path, schema)
                return True
        return False

    parent, table_idx = _first_table_parent(root)
    if parent is None:
        # No Table — attach at the top of the root's children if it has any,
        # else wrap it.
        if isinstance(root, dict) and isinstance(root.get("children"), list):
            root["children"].insert(0, fb_node)
        else:
            schema["root"] = {"type": "Stack", "props": {}, "children": [fb_node, root]}
    else:
        parent["children"].insert(table_idx, fb_node)

    # Advertise the URL param on any list dataSource so the data hook can
    # thread ?filter=<expr> to the API. Non-destructive: only adds a
    # ``filter_query_param`` hint, doesn't rewrite existing filters.
    for ds in (schema.get("dataSources") or []):
        if isinstance(ds, dict) and ds.get("op") in ("list", None):
            ds.setdefault("filter_query_param", param_key)

    _annotate(schema)
    _write(schema_path, schema)
    return True


def _annotate(schema: dict) -> None:
    schema.setdefault("_wave3", {})["filter_builder_applied"] = True


def _write(path: Path, schema: dict) -> None:
    path.write_text(json.dumps(schema, indent=2), encoding="utf-8")


def run(output_dir: str) -> dict[str, Any]:
    """Inject FilterBuilder into every page schema declaring filter_fields."""
    report: dict[str, Any] = {
        "enabled": is_enabled(),
        "pages_touched": [],
    }
    if not is_enabled():
        return report

    root = Path(output_dir)
    schemas_dir = root / "src" / "schemas"
    if not schemas_dir.exists():
        return report

    for fp in schemas_dir.glob("**/*.json"):
        try:
            if _apply_to_schema_file(fp):
                report["pages_touched"].append(str(fp.relative_to(root)))
        except Exception as exc:  # noqa: BLE001 — best-effort; never blocks
            logger.warning("filter_builder_pass: failed on %s: %s", fp, exc)

    if report["pages_touched"]:
        logger.info(
            "filter_builder_pass: applied to %d page(s)",
            len(report["pages_touched"]),
        )
    return report
