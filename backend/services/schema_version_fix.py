"""Coerce invalid page schemaVersion values to the canonical "1"/"2".

The page agent (and older synthesizers) sometimes emit `"schemaVersion": "2.0"`,
which fails the schema's `z.literal("1") | z.literal("2")` discriminator. The
renderer then falls back to "render as-is", skipping normalization — which can
mis-render parts of the tree (e.g. a detail page's Card). Normalize every page
schema's version to a bare major so it validates and normalizes properly.
"""
from __future__ import annotations

import json
from pathlib import Path

_MAP = {"2.0": "2", "2.0.0": "2", "1.0": "1", "1.0.0": "1"}


def fix_schema_versions(output_dir: str | Path) -> dict:
    root = Path(output_dir) / "src" / "schemas"
    fixed: list[str] = []
    if not root.is_dir():
        return {"fixed": fixed}
    for f in root.rglob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        v = data.get("schemaVersion")
        if isinstance(v, (int, float)):
            v = str(v)
        new = _MAP.get(v) if isinstance(v, str) else None
        # Also handle e.g. "2" already fine; only rewrite when it differs.
        if new and new != data.get("schemaVersion"):
            data["schemaVersion"] = new
            f.write_text(json.dumps(data, indent=2), encoding="utf-8")
            fixed.append(str(f.relative_to(root)))
    return {"fixed": fixed}
