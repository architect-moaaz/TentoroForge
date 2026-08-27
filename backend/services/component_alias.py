"""Rename hallucinated component types to their registered equivalents.

The page agent occasionally emits a component name that isn't in the library
registry — e.g. `TableSortable` for the real `Table`, which has the same
prop shape (`columns` + `caption`). The renderer then shows a ⚠ unknown-component
fallback. Map the common inventions onto real components so they render.
"""
from __future__ import annotations

import json
from pathlib import Path

# bad type -> registered type with a compatible prop shape
_ALIASES = {
    "TableSortable": "Table",
    "SortableTable": "Table",
    "SortableDataTable": "Table",
    "DataTable": "Table",
    "DataGrid": "Table",
}


def normalize_component_aliases(output_dir: str | Path) -> dict:
    root = Path(output_dir) / "src" / "schemas"
    changed: list[str] = []
    if not root.is_dir():
        return {"changed": changed}
    for f in root.rglob("*.json"):
        try:
            s = f.read_text(encoding="utf-8")
        except Exception:
            continue
        new = s
        for bad, good in _ALIASES.items():
            # Only the node's `type` field — never touch labels/content/strings.
            new = new.replace(f'"type": "{bad}"', f'"type": "{good}"')
            new = new.replace(f'"type":"{bad}"', f'"type":"{good}"')
        if new != s:
            f.write_text(new, encoding="utf-8")
            changed.append(str(f.relative_to(root)))
    return {"changed": changed}
