"""detail_polish — modernise record-detail pages.

The schema agent hand-rolls detail pages as a Card wrapping a Stack of Rows,
each Row being two Text nodes (a static label + a bound value). Rendered, that
reads as oversized, sparse key/value pairs — an "archaic" look. The library
already ships a compact, divided ``DescriptionList`` component; the agent just
doesn't use it.

This deterministic pass rewrites those label/value Row groups into a single
``DescriptionList`` (horizontal orientation) so every detail page — full-page or
inside the routed drawer — gets the tidy divided layout for free. Bindings in the
value survive the move: the renderer deep-interpolates props, including
``items[].description``. Idempotent, and it only touches the recognised
label/value pattern, so anything richer the agent produced is left untouched.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _text_content(node: dict) -> str:
    p = node.get("props", {}) or {}
    v = p.get("content", p.get("text", ""))
    return v if isinstance(v, str) else ""


_ROW_TYPES = {"Row", "Flex", "Group", "Stack"}


def _is_kv_row(node: Any) -> bool:
    """A row that is exactly two Text nodes — a label/value pair."""
    if not isinstance(node, dict) or node.get("type") not in _ROW_TYPES:
        return False
    kids = [c for c in (node.get("children") or []) if isinstance(c, dict)]
    return len(kids) == 2 and all(c.get("type") == "Text" for c in kids)


def _to_item(row: dict) -> dict:
    texts = [c for c in row["children"] if isinstance(c, dict) and c.get("type") == "Text"]
    a, b = _text_content(texts[0]), _text_content(texts[1])
    # The value is the bound one ({{...}}); labels are static. If the value came
    # first, swap so term=label, description=value.
    if "{{" in a and "{{" not in b:
        a, b = b, a
    return {"term": a.strip(), "description": b}


def _polish_node(node: Any) -> int:
    """Recursively convert contiguous label/value rows to a DescriptionList."""
    if not isinstance(node, dict):
        return 0
    changed = 0
    kids = node.get("children")
    if isinstance(kids, list):
        rows = [c for c in kids if _is_kv_row(c)]
        if len(rows) >= 2:
            dl = {
                "type": "DescriptionList",
                "props": {"items": [_to_item(r) for r in rows], "orientation": "horizontal"},
            }
            new_kids: list = []
            inserted = False
            for c in kids:
                if _is_kv_row(c):
                    if not inserted:
                        new_kids.append(dl)
                        inserted = True
                else:
                    new_kids.append(c)
            node["children"] = new_kids
            kids = new_kids
            changed += 1
        for c in kids:
            changed += _polish_node(c)
    return changed


def polish_detail_schema(schema: dict) -> int:
    """Polish one page schema in place. Returns the number of groups converted."""
    root = schema.get("root", schema)
    return _polish_node(root)


def polish_detail_schemas(output_dir: str | Path) -> dict:
    """Rewrite every record-detail page's label/value rows into a DescriptionList.

    Targets ``src/schemas/**/[id].json`` (the dynamic record-detail routes).
    Returns {files, converted, changed_files:[...]}."""
    base = Path(output_dir)
    schemas = base / "src" / "schemas"
    if not schemas.exists():
        return {"files": 0, "converted": 0, "changed_files": []}

    files = 0
    converted = 0
    changed_files: list[str] = []
    for p in sorted(schemas.rglob("[[]id[]].json")):
        files += 1
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        n = polish_detail_schema(data)
        if n:
            p.write_text(json.dumps(data, indent=2), encoding="utf-8")
            converted += n
            changed_files.append(str(p.relative_to(schemas)))
    return {"files": files, "converted": converted, "changed_files": changed_files}
